#!/usr/bin/env python3
"""
HTB Helper 4.0 — local field notebook.

A stdlib-only localhost GUI (127.0.0.1) so notes can be real Markdown,
plus a logged shell in the terminal this process was started from.

Not a network service. Binds loopback only. No pip packages.
"""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
import argparse
import ipaddress
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import threading
import time
import webbrowser

import htb_helper as engine
from session_capture import decode_log_bytes, run_logged_shell
from tools_catalog import COMMON_WORDLISTS, TOOL_GROUPS, TOOL_INFO

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"
APP_VERSION = "4.0.0"
DEFAULT_PORT = 8765

STATE = {
    "config": None,
    "config_path": ROOT / "config.json",
    "workspace": None,
    "session_log": None,
    "session_active": False,
    "port": DEFAULT_PORT,
    "tool_lock": threading.Lock(),
    "notes_lock": threading.Lock(),
}


def human_ts():
    return engine.human_timestamp()


def is_configured(config):
    if not config:
        return False
    sid = str(config.get("student_id") or "").strip()
    name = str(config.get("machine_name") or "").strip()
    ip = str(config.get("target_ip") or "").strip()
    if not sid or sid == "YOUR_STUDENT_ID":
        return False
    if not name or name == "MachineName":
        return False
    if not ip:
        return False
    try:
        ipaddress.ip_address(ip)
    except ValueError:
        return False
    return True


def load_or_none(path: Path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def save_config(path: Path, config: dict):
    path.write_text(json.dumps(config, indent=4) + "\n", encoding="utf-8")


def apply_config(config, config_path: Path):
    STATE["config"] = config
    STATE["config_path"] = config_path
    if is_configured(config):
        STATE["workspace"] = engine.setup_workspace(config)
    else:
        STATE["workspace"] = None


def detect_os():
    info = {}
    path = Path("/etc/os-release")
    if path.exists():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if "=" in line:
                key, val = line.split("=", 1)
                info[key] = val.strip().strip('"')
    return info.get("ID", ""), info.get("ID_LIKE", ""), info.get("PRETTY_NAME", sys.platform)


def helper_packages():
    """Packages the helper itself needs. Pentest tools stay on the VM image."""
    if os.name == "nt":
        return []
    return ["python3", "nmap", "bsdutils", "xdg-utils"]


def try_bootstrap(packages=None):
    packages = packages or helper_packages()
    if os.name == "nt" or not packages:
        return {"ok": True, "installed": [], "message": "No apt bootstrap on Windows."}

    missing = []
    mapping = {"python3": "python3", "nmap": "nmap", "script": "bsdutils", "xdg-open": "xdg-utils"}
    if shutil.which("python3") is None and shutil.which("python") is None:
        missing.append("python3")
    if shutil.which("nmap") is None:
        missing.append("nmap")
    if shutil.which("script") is None:
        missing.append("bsdutils")
    if shutil.which("xdg-open") is None:
        missing.append("xdg-utils")

    os_id, like, pretty = detect_os()
    debian_like = os_id in {"debian", "ubuntu", "kali", "parrot", "parrotsec"} or "debian" in like
    if not missing:
        return {"ok": True, "installed": [], "message": f"{pretty}: helper packages already present."}
    if not debian_like:
        return {
            "ok": False,
            "installed": [],
            "message": f"Unknown distro ({pretty}). Install: {' '.join(missing)}",
        }

    apt = shutil.which("apt-get") or shutil.which("apt")
    if not apt:
        return {"ok": False, "installed": [], "message": "apt not found."}

    sudo = [] if hasattr(os, "geteuid") and os.geteuid() == 0 else (["sudo"] if shutil.which("sudo") else [])
    env = os.environ.copy()
    env["DEBIAN_FRONTEND"] = "noninteractive"
    try:
        subprocess.run(sudo + [apt, "update", "-qq"], check=False, env=env)
        result = subprocess.run(
            sudo + [apt, "install", "-y"] + missing,
            check=False,
            env=env,
            capture_output=True,
            text=True,
            errors="replace",
        )
        if result.returncode != 0:
            return {
                "ok": False,
                "installed": [],
                "message": result.stderr.strip() or result.stdout.strip() or "apt install failed",
            }
        return {"ok": True, "installed": missing, "message": f"Installed: {', '.join(missing)}"}
    except OSError as exc:
        return {"ok": False, "installed": [], "message": str(exc)}


def existing_wordlists():
    found = [p for p in COMMON_WORDLISTS if Path(p).is_file()]
    return found


def notes_path():
    ws = STATE["workspace"]
    if not ws:
        return None
    return ws / "notes" / "notes.md"


def json_bytes(payload, status=200):
    body = json.dumps(payload).encode("utf-8")
    return status, "application/json; charset=utf-8", body


def read_notes():
    path = notes_path()
    if not path or not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def write_notes(text: str):
    path = notes_path()
    if not path:
        raise RuntimeError("Workspace is not configured yet.")
    with STATE["notes_lock"]:
        path.write_text(text, encoding="utf-8")


def append_student_note(category: str, body: str):
    ws = STATE["workspace"]
    if not ws:
        raise RuntimeError("Workspace is not configured yet.")
    category = (category or "OTHER").strip().upper()
    body = (body or "").rstrip()
    if not body:
        raise RuntimeError("Note body is empty.")
    block = f"\n### [{human_ts()}] [{category}]\n\n{body}\n"
    path = notes_path()
    with STATE["notes_lock"]:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(block)
    engine.manifest_add(ws, "notes", {
        "time": human_ts(),
        "category": category,
        "origin": "student",
        "summary": body[:400],
    })
    return block


def stamp_heading(category: str):
    category = (category or "OTHER").strip().upper()
    return f"\n### [{human_ts()}] [{category}]\n\n"


def preflight_payload():
    ws = STATE["workspace"]
    checks = []

    def add(name, ok, detail=""):
        checks.append({"name": name, "ok": bool(ok), "detail": detail or (ok if isinstance(ok, str) else "")})

    add("Python", sys.executable, sys.executable)
    add("nmap", shutil.which("nmap"), shutil.which("nmap") or "not on PATH")
    if os.name != "nt":
        add("script", shutil.which("script"), shutil.which("script") or "not on PATH (bsdutils)")
    else:
        add("console capture", True, "Windows piped cmd (ipconfig/ping/tracert/nmap output included)")

    shot = find_screenshot_command()
    if os.name == "nt":
        add("screenshot", True, "PowerShell screen capture")
    else:
        add("screenshot", bool(shot), shot or "none (mate-screenshot/scrot/gnome-screenshot/import)")

    for folder in ("logs", "screenshots", "notes"):
        if ws:
            add(folder + "/", (ws / folder).is_dir())
        else:
            add(folder + "/", False, "configure first")

    os_id, like, pretty = detect_os()
    add("OS", True, pretty or sys.platform)

    optional = [
        "gobuster", "ffuf", "feroxbuster", "nikto", "whatweb", "nuclei",
        "httpx", "enum4linux-ng", "enum4linux", "smbclient", "nxc",
        "ldapsearch", "curl", "dig", "whois",
    ]
    present = [name for name in optional if shutil.which(name)]
    return {
        "checks": checks,
        "optional_tools": present,
        "os": pretty,
        "configured": is_configured(STATE["config"]),
        "wordlists": existing_wordlists(),
    }


def stats_payload():
    ws = STATE["workspace"]
    if not ws:
        return {}
    logs = ws / "logs"
    shots = ws / "screenshots"
    notes = read_notes()
    evidence = (ws / "notes" / "evidence.md").read_text(encoding="utf-8", errors="replace") if (ws / "notes" / "evidence.md").exists() else ""
    manifest = engine.load_manifest(ws) or {}
    return {
        "session_logs": len(list(logs.glob("session*.log"))),
        "tool_runs": len(manifest.get("tool_runs") or []),
        "timeline_notes": len(re.findall(r"^### \[", notes, re.M)),
        "evidence": len(re.findall(r"^## E-\d+", evidence, re.M)),
        "screenshots": len(list(shots.glob("*.png"))),
        "milestones": manifest.get("milestones") or {},
        "workspace": str(ws),
        "session_log": str(STATE["session_log"]) if STATE["session_log"] else None,
        "session_active": STATE["session_active"],
    }


def list_workspace_files():
    ws = STATE["workspace"]
    if not ws:
        return []
    rows = []
    for path in sorted(p for p in ws.rglob("*") if p.is_file()):
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        rows.append({"path": engine.relative_path(ws, path), "size": size})
    return rows


def log_files():
    ws = STATE["workspace"]
    if not ws:
        return []
    logs = ws / "logs"
    names = []
    for path in sorted(logs.glob("*"), key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True):
        if path.is_file():
            names.append(path.name)
    return names


def read_log(name: str, offset: int = 0):
    ws = STATE["workspace"]
    if not ws:
        return {"text": "", "offset": 0, "name": name}
    path = (ws / "logs" / name).resolve()
    path.relative_to((ws / "logs").resolve())
    if not path.is_file():
        return {"text": "", "offset": 0, "name": name}
    data = path.read_bytes()
    text = decode_log_bytes(data)
    if len(text) > 400_000:
        text = text[-400_000:]
    return {"text": text, "offset": len(data), "name": name, "size": len(data), "replace": True}


def find_screenshot_command():
    for name in ("mate-screenshot", "gnome-screenshot", "scrot", "grim", "import"):
        if shutil.which(name):
            return name
    return None


def capture_screenshot(milestone, description):
    ws = STATE["workspace"]
    if not ws:
        raise RuntimeError("Workspace is not configured yet.")
    screenshots = ws / "screenshots"
    screenshots.mkdir(parents=True, exist_ok=True)
    description = engine.safe_filename(description) or "screenshot"
    dest = screenshots / f"{engine.timestamp_seconds()}_{engine.safe_filename(milestone)}_{description}.png"

    if os.name == "nt":
        ps = (
            "Add-Type -AssemblyName System.Windows.Forms; "
            "Add-Type -AssemblyName System.Drawing; "
            "$b = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds; "
            "$bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height; "
            "$g = [System.Drawing.Graphics]::FromImage($bmp); "
            "$g.CopyFromScreen($b.Location, [System.Drawing.Point]::Empty, $b.Size); "
            f"$bmp.Save('{str(dest).replace(chr(39), '')}'); "
            "$g.Dispose(); $bmp.Dispose();"
        )
        result = subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=False)
        if result.returncode != 0 or not dest.exists() or dest.stat().st_size == 0:
            raise RuntimeError("Windows screenshot failed.")
    else:
        cmd_name = find_screenshot_command()
        if not cmd_name:
            raise RuntimeError("No screenshot utility. On Parrot: sudo apt install scrot  (or mate-screenshot).")
        if cmd_name == "gnome-screenshot":
            command = [cmd_name, "-f", str(dest)]
        elif cmd_name == "mate-screenshot":
            command = [cmd_name, "-f", str(dest)]
        elif cmd_name == "scrot":
            command = [cmd_name, str(dest)]
        elif cmd_name == "grim":
            command = [cmd_name, str(dest)]
        else:
            command = ["import", "-window", "root", str(dest)]
        result = subprocess.run(command, check=False)
        if result.returncode != 0 or not dest.exists() or dest.stat().st_size == 0:
            raise RuntimeError(f"{cmd_name} failed (exit {result.returncode}).")

    engine.update_milestone(ws, milestone)
    engine.manifest_add(ws, "screenshots", {
        "time": human_ts(),
        "milestone": milestone,
        "description": description,
        "file": engine.file_metadata(ws, dest),
    })
    engine.append_timeline_note(
        ws,
        "EVIDENCE",
        f"Captured screenshot: {description}",
        evidence=[engine.relative_path(ws, dest)],
        metadata={"milestone": milestone},
    )
    return engine.relative_path(ws, dest)


def substitute(value: str, fields: dict, config: dict):
    target = str(config.get("target_ip") or "")
    port = "" if config.get("target_port") in (None, "", 0) else str(config.get("target_port"))
    mapping = {
        "target": target,
        "url": fields.get("url") or f"http://{target}",
        "wordlist": fields.get("wordlist") or "",
        "query": fields.get("query") or "",
        "port": port,
        "command": fields.get("command") or "",
    }
    mapping.update({k: str(v) for k, v in fields.items() if v is not None})
    out = value
    for key, val in mapping.items():
        out = out.replace("{" + key + "}", val)
    return out


def resolve_bin(tool):
    names = []
    if tool.get("bin"):
        names.append(tool["bin"])
    names.extend(tool.get("alt_bins") or [])
    for name in names:
        path = shutil.which(name)
        if path:
            return name, path
    return tool.get("bin"), None


def find_tool(tool_id: str):
    for group in TOOL_GROUPS:
        for tool in group["tools"]:
            if tool["id"] == tool_id:
                return group, tool
    return None, None


def build_command(tool, fields, extra, config):
    fields = fields or {}
    extra_parts = []
    if extra:
        if engine.shell_meta_present(extra):
            raise RuntimeError("Pipes, redirects, and ';' are not allowed. The helper already captures output.")
        extra_parts = shlex.split(extra)

    kind = tool["kind"]
    target = str(config.get("target_ip") or "")
    if kind == "ping":
        if os.name == "nt":
            return ["ping", "-n", "4", target] + extra_parts
        return ["ping", "-c", "4", target] + extra_parts
    if kind == "traceroute":
        if os.name == "nt":
            return ["tracert", target] + extra_parts
        prog = shutil.which("traceroute") or shutil.which("tracepath") or "traceroute"
        return [prog, target] + extra_parts
    if kind == "custom":
        command_text = (fields.get("command") or "").strip()
        if not command_text:
            raise RuntimeError("Command is empty.")
        if engine.shell_meta_present(command_text):
            raise RuntimeError("Pipes, redirects, and ';' are not allowed here.")
        return shlex.split(command_text) + extra_parts

    if kind in ("nmap", "nmap-port"):
        ws = STATE["workspace"]
        stamp = engine.timestamp_seconds()
        logs = ws / "logs"
        port = config.get("target_port") if kind == "nmap-port" else None
        if kind == "nmap-port":
            if not port:
                raise RuntimeError("No assigned port in config.")
            prefix = logs / f"nmap_port_{port}_{stamp}"
        else:
            prefix = logs / f"nmap_scan_{stamp}"
        command = ["nmap"] + list(tool.get("nmap_args") or [])
        if port:
            command.extend(["-p", str(port)])
        command.extend(["-oA", str(prefix), str(config["target_ip"])])
        return command + extra_parts

    if kind == "gobuster":
        wordlist = fields.get("wordlist") or (existing_wordlists()[0] if existing_wordlists() else "")
        if not wordlist:
            raise RuntimeError("Wordlist path is required.")
        url = substitute(fields.get("url") or "http://{target}", fields, config)
        command = ["gobuster", tool.get("mode") or "dir", "-u", url, "-w", wordlist]
        return command + extra_parts

    if kind == "template":
        argv = [substitute(part, fields, config) for part in tool.get("argv") or []]
        if any(part.endswith("{wordlist}") or part == "" for part in argv):
            raise RuntimeError("Fill in the required fields.")
        for required in ("wordlist",):
            if "{wordlist}" in (tool.get("argv") or []) and not fields.get("wordlist"):
                lists = existing_wordlists()
                if not lists:
                    raise RuntimeError("Wordlist path is required.")
                argv = [lists[0] if item in ("", "{wordlist}") else item for item in argv]
        if "wordlist" in [f.get("name") for f in tool.get("fields") or []]:
            if not fields.get("wordlist"):
                lists = existing_wordlists()
                if lists:
                    argv = [lists[0] if item in ("",) else item for item in argv]
                    # replace empty wordlist slot if we used default via substitution miss
                    if tool.get("argv") and "{wordlist}" in tool["argv"]:
                        argv = [substitute(part, {**fields, "wordlist": lists[0]}, config) for part in tool["argv"]]
                else:
                    raise RuntimeError("Wordlist path is required.")
        return argv + extra_parts

    raise RuntimeError(f"Unknown tool kind: {kind}")


def fill_defaults(tool, fields, config):
    fields = dict(fields or {})
    for spec in tool.get("fields") or []:
        name = spec["name"]
        if not fields.get(name) and spec.get("default"):
            fields[name] = substitute(spec["default"], fields, config)
    if "wordlist" in [s["name"] for s in tool.get("fields") or []] and not fields.get("wordlist"):
        lists = existing_wordlists()
        if lists:
            fields["wordlist"] = lists[0]
    return fields


def record_gui_tool(tool, command, purpose, description):
    ws = STATE["workspace"]
    bin_name = command[0] if command else "command"
    tool_name = Path(bin_name).name
    identified = engine.identify_tool(command)
    logs = ws / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    output_file = logs / f"{engine.safe_filename(tool_name)}_{engine.timestamp_seconds()}.txt"
    return engine.record_tool_run(
        ws,
        command,
        description,
        purpose,
        tool=identified,
        output_file=output_file,
    ), output_file


def run_tool_streaming(command, output_file, send_line):
    captured = []
    captured_chars = 0
    interrupted = False
    truncated = False
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with output_file.open("w", encoding="utf-8", errors="replace") as handle:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            bufsize=1,
        )
        try:
            assert process.stdout is not None
            for line in process.stdout:
                handle.write(line)
                handle.flush()
                send_line(line)
                if captured_chars < engine.MAX_ANALYSIS_CHARS:
                    remaining = engine.MAX_ANALYSIS_CHARS - captured_chars
                    captured.append(line[:remaining])
                    captured_chars += min(len(line), remaining)
                    if len(line) > remaining:
                        truncated = True
                else:
                    truncated = True
            code = process.wait()
        except KeyboardInterrupt:
            interrupted = True
            process.terminate()
            try:
                code = process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                code = process.wait()
    return {
        "returncode": code,
        "output": "".join(captured),
        "interrupted": interrupted,
        "truncated": truncated,
    }


def finish_tool_run(tool, command, purpose, description, result, output_file):
    ws = STATE["workspace"]
    identified = engine.identify_tool(command)
    tool_label = identified if identified != "generic" else Path(command[0]).name
    category = engine.classify_tool_category(identified, command)
    summary, findings, metadata = engine.analyze_tool_output(identified, result["output"], result["returncode"])
    if result["truncated"]:
        findings.append("Parser used the first part of a large capture; the raw file is complete.")
    outcome = engine.classify_outcome(result["returncode"], result["interrupted"])
    rel = engine.relative_path(ws, output_file)
    engine.save_command_record(ws, command, description, purpose)
    engine.append_timeline_note(
        ws,
        "DEAD END" if result["interrupted"] else category,
        summary,
        tool=tool_label,
        command=shlex.join(command),
        purpose=purpose,
        exit_code=result["returncode"],
        outcome=outcome,
        findings=findings,
        evidence=[rel],
        metadata={**metadata, "event": "attempt_result"},
    )
    artifact = engine.file_metadata(ws, output_file)
    run_record = {
        "time": human_ts(),
        "tool": identified,
        "tool_label": tool_label,
        "description": description,
        "purpose": purpose,
        "command": shlex.join(command),
        "exit_code": result["returncode"],
        "summary": summary,
        "findings": findings[: engine.MAX_NOTE_FINDINGS],
        "output": artifact,
    }
    engine.manifest_add(ws, "tool_runs", run_record)
    engine.manifest_add(ws, "command_outputs", run_record)
    return run_record


def build_report():
    ws = STATE["workspace"]
    config = STATE["config"] or {}
    if not ws:
        raise RuntimeError("Workspace is not configured yet.")
    def strip_leading_h1(text: str) -> str:
        lines = text.splitlines()
        if lines and lines[0].startswith("# "):
            lines = lines[1:]
            while lines and not lines[0].strip():
                lines = lines[1:]
        return "\n".join(lines).strip()

    notes = strip_leading_h1(read_notes())
    evidence = ""
    ev_path = ws / "notes" / "evidence.md"
    if ev_path.exists():
        evidence = strip_leading_h1(
            ev_path.read_text(encoding="utf-8", errors="replace")
        )
    manifest = engine.load_manifest(ws) or {}
    runs = manifest.get("tool_runs") or []
    machine = config.get("machine_name") or "Unknown"
    student = config.get("student_id") or ""
    target = config.get("target_ip") or ""
    port = config.get("target_port") or "None"
    project = config.get("research_project") or "HTB Enterprise AI Generated Pentest Report Study"

    method_lines = [
        "Authorized HTB Enterprise lab only. Work was recorded in real time:",
        "",
        "- Terminal session logs under `logs/session*.log` (full command output, including failed attempts)",
        "- Helper-captured tool runs (raw files under `logs/`)",
        "- Timestamped notes in `notes/notes.md`",
        "- Evidence pointers in `notes/evidence.md`",
        "",
    ]
    if runs:
        method_lines.append("Tools invoked through the helper:")
        for run in runs:
            cmd = run.get("command") or run.get("tool_label")
            method_lines.append(f"- `{cmd}` (exit {run.get('exit_code')})")
    else:
        method_lines.append("_No helper-captured tool runs yet. Commands run in the logged terminal still belong in session logs._")

    finding_lines = []
    for run in runs:
        for item in run.get("findings") or []:
            finding_lines.append(f"- {item} _(source: {run.get('tool_label')})_")
    if evidence:
        finding_lines.extend(["", "Evidence log:", "", evidence])
    if not finding_lines:
        finding_lines.append("_No structured findings yet. Record evidence and keep failed attempts._")

    lines = [
        f"# HTB Challenge: {machine}",
        "",
        f"- Student: `{student}`",
        f"- Target: `{target}`",
        f"- Assigned port: `{port}`",
        f"- Study: {project}",
        f"- Draft generated: {human_ts()}",
        "",
        "Draft assembled from the workspace. Edit before any formal submission.",
        "Do not reconstruct the engagement from memory.",
        "",
        "## Scope",
        "",
        f"This report covers the authorized HTB machine **{machine}** at `{target}`",
        f"(assigned port: `{port}`). Testing was limited to that host and the engagement rules.",
        "",
        "## Methodology",
        "",
        *method_lines,
        "",
        "## Findings",
        "",
        *finding_lines,
        "",
        "## Attack narrative",
        "",
        notes or "_No notes yet. Write the story in Notes as you work; it is copied here._",
        "",
        "## Remediation",
        "",
        "_Summarize recommended fixes for each finding. Do not invent issues that were not observed._",
        "",
        "## Conclusion",
        "",
        "_State the outcome (foothold, flags, or time expired) and what remains unverified._",
        "",
    ]
    text = "\n".join(lines) + "\n"
    dest = ws / "notes" / "report_draft.md"
    dest.write_text(text, encoding="utf-8")
    return text


def tools_public():
    groups = []
    for group in TOOL_GROUPS:
        tools = []
        for tool in group["tools"]:
            bin_name, resolved = resolve_bin(tool)
            item = {
                "id": tool["id"],
                "name": tool["name"],
                "bin": bin_name,
                "summary": tool.get("summary"),
                "purpose": tool.get("purpose"),
                "fields": tool.get("fields") or [],
                "installed": bool(resolved) or tool["kind"] == "custom",
                "kind": tool["kind"],
            }
            tools.append(item)
        groups.append({
            "id": group["id"],
            "name": group["name"],
            "blurb": group["blurb"],
            "tools": tools,
        })
    return groups


class Handler(BaseHTTPRequestHandler):
    server_version = f"HTBHelper/{APP_VERSION}"

    def log_message(self, fmt, *args):
        msg = fmt % args
        if "/api/state" in msg or "/api/logs?" in msg:
            return
        sys.stderr.write("%s - %s\n" % (self.address_string(), msg))

    def _send(self, status, content_type, body: bytes):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload, status=200):
        status, ctype, body = json_bytes(payload, status)
        self._send(status, ctype, body)

    def _read_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        if path in ("/", "/index.html"):
            self._send(200, "text/html; charset=utf-8", (WEB / "index.html").read_bytes())
            return
        if path == "/app.css":
            self._send(200, "text/css; charset=utf-8", (WEB / "app.css").read_bytes())
            return
        if path == "/app.js":
            self._send(200, "application/javascript; charset=utf-8", (WEB / "app.js").read_bytes())
            return

        try:
            if path == "/api/state":
                config = STATE["config"] or {}
                self._json({
                    "version": APP_VERSION,
                    "configured": is_configured(config),
                    "config": {
                        "student_id": config.get("student_id", ""),
                        "machine_name": config.get("machine_name", ""),
                        "target_ip": config.get("target_ip", ""),
                        "target_port": config.get("target_port"),
                        "research_project": config.get("research_project", ""),
                    } if config else {},
                    "workspace": str(STATE["workspace"]) if STATE["workspace"] else None,
                    "session_active": STATE["session_active"],
                    "session_log": str(STATE["session_log"]) if STATE["session_log"] else None,
                    "port": STATE["port"],
                    "stats": stats_payload() if STATE["workspace"] else {},
                })
                return
            if path == "/api/notes":
                self._json({"text": read_notes()})
                return
            if path == "/api/evidence":
                ws = STATE["workspace"]
                text = ""
                if ws and (ws / "notes" / "evidence.md").exists():
                    text = (ws / "notes" / "evidence.md").read_text(encoding="utf-8", errors="replace")
                self._json({"text": text})
                return
            if path == "/api/files":
                self._json({"files": list_workspace_files()})
                return
            if path == "/api/logs":
                name = (query.get("name") or ["session.log"])[0]
                offset = int((query.get("offset") or ["0"])[0] or 0)
                self._json({"files": log_files(), **read_log(name, offset)})
                return
            if path == "/api/stats":
                self._json(stats_payload())
                return
            if path == "/api/preflight":
                self._json(preflight_payload())
                return
            if path == "/api/tools":
                self._json({
                    "groups": tools_public(),
                    "wordlists": existing_wordlists(),
                    "target": (STATE["config"] or {}).get("target_ip"),
                    "port": (STATE["config"] or {}).get("target_port"),
                })
                return
            if path == "/api/info":
                self._json({"groups": TOOL_INFO, "target": (STATE["config"] or {}).get("target_ip")})
                return
            if path == "/api/report":
                ws = STATE["workspace"]
                text = ""
                if ws and (ws / "notes" / "report_draft.md").exists():
                    text = (ws / "notes" / "report_draft.md").read_text(encoding="utf-8", errors="replace")
                self._json({"text": text})
                return
            if path == "/api/wordlists":
                self._json({"wordlists": existing_wordlists()})
                return
        except Exception as exc:
            self._json({"error": str(exc)}, 400)
            return

        self._send(404, "text/plain; charset=utf-8", b"not found")

    def do_PUT(self):
        parsed = urlparse(self.path)
        try:
            data = self._read_json()
            if parsed.path == "/api/notes":
                write_notes(data.get("text") or "")
                self._json({"ok": True})
                return
        except Exception as exc:
            self._json({"error": str(exc)}, 400)
            return
        self._json({"error": "not found"}, 404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            data = self._read_json() if path != "/api/tools/run" else self._read_json()
        except Exception as exc:
            self._json({"error": f"invalid JSON: {exc}"}, 400)
            return

        try:
            if path == "/api/config":
                config = {
                    "student_id": str(data.get("student_id") or "").strip(),
                    "machine_name": str(data.get("machine_name") or "").strip(),
                    "target_ip": str(data.get("target_ip") or "").strip(),
                    "target_port": data.get("target_port"),
                    "workspace_root": (STATE["config"] or {}).get("workspace_root", "./machines"),
                    "research_project": str(
                        data.get("research_project")
                        or "HTB Enterprise AI Generated Pentest Report Study"
                    ).strip(),
                    "gui_port": DEFAULT_PORT,
                }
                if config["target_port"] in ("", None):
                    config["target_port"] = None
                else:
                    config["target_port"] = int(config["target_port"])
                if not engine.validate_config(config) or not is_configured(config):
                    self._json({"error": "Invalid configuration. Check student id, machine name, and target IP."}, 400)
                    return
                save_config(STATE["config_path"], config)
                apply_config(config, STATE["config_path"])
                self._json({"ok": True, "workspace": str(STATE["workspace"])})
                return

            if path == "/api/notes/append":
                block = append_student_note(data.get("category") or "OTHER", data.get("body") or "")
                self._json({"ok": True, "block": block, "text": read_notes()})
                return

            if path == "/api/notes/stamp":
                heading = stamp_heading(data.get("category") or "OTHER")
                self._json({"ok": True, "heading": heading})
                return

            if path == "/api/evidence":
                ws = STATE["workspace"]
                if not ws:
                    raise RuntimeError("Workspace is not configured yet.")
                evidence_file = ws / "notes" / "evidence.md"
                evidence_id = engine.get_next_evidence_id(evidence_file)
                phase = str(data.get("phase") or "").strip()
                description = str(data.get("description") or "").strip()
                source = str(data.get("source") or "").strip()
                if not phase or not description or not source:
                    raise RuntimeError("Phase, description, and source are required.")
                source_path = (ws / source).resolve()
                source_path.relative_to(ws.resolve())
                exists = source_path.exists()
                status = "Verified" if exists else "WARNING: file does not currently exist"
                size = source_path.stat().st_size if exists and source_path.is_file() else None
                digest = engine.sha256_file(source_path) if exists and source_path.is_file() else None
                with evidence_file.open("a", encoding="utf-8") as handle:
                    handle.write(f"\n## E-{evidence_id:03d}\n")
                    handle.write(f"- Time: {human_ts()}\n")
                    handle.write(f"- Phase: {phase}\n")
                    handle.write(f"- Description: {description}\n")
                    handle.write(f"- Source: {source}\n")
                    handle.write(f"- Source status: {status}\n")
                    if size is not None:
                        handle.write(f"- Source size: {size:,} bytes\n")
                    if digest:
                        handle.write(f"- SHA-256: {digest}\n")
                engine.manifest_add(ws, "evidence", {
                    "id": f"E-{evidence_id:03d}",
                    "time": human_ts(),
                    "phase": phase,
                    "description": description,
                    "source": source,
                    "status": status,
                    "sha256": digest,
                })
                engine.append_timeline_note(
                    ws,
                    "EVIDENCE",
                    f"Recorded evidence E-{evidence_id:03d}: {description}",
                    origin="student",
                    evidence=[source],
                )
                text = evidence_file.read_text(encoding="utf-8")
                self._json({"ok": True, "id": f"E-{evidence_id:03d}", "text": text})
                return

            if path == "/api/screenshot":
                rel = capture_screenshot(
                    data.get("milestone") or "other",
                    data.get("description") or "screenshot",
                )
                self._json({"ok": True, "file": rel})
                return

            if path == "/api/validate":
                ws = STATE["workspace"]
                if not ws:
                    raise RuntimeError("Workspace is not configured yet.")
                buf = []

                class Capture:
                    def write(self, s):
                        buf.append(s)

                    def flush(self):
                        pass

                old = sys.stdout
                sys.stdout = Capture()
                try:
                    engine.validate_submission(ws)
                finally:
                    sys.stdout = old
                self._json({"ok": True, "text": "".join(buf)})
                return

            if path == "/api/backup":
                ws = STATE["workspace"]
                if not ws:
                    raise RuntimeError("Workspace is not configured yet.")
                archive_base = ws.parent / f"{ws.name}_{engine.timestamp_seconds()}"
                archive = shutil.make_archive(str(archive_base), "zip", root_dir=ws.parent, base_dir=ws.name)
                self._json({"ok": True, "file": archive})
                return

            if path == "/api/report":
                text = build_report()
                self._json({"ok": True, "text": text})
                return

            if path == "/api/bootstrap":
                self._json(try_bootstrap())
                return

            if path == "/api/tools/run":
                self._run_tool_sse(data)
                return
        except Exception as exc:
            self._json({"error": str(exc)}, 400)
            return

        self._json({"error": "not found"}, 404)

    def _run_tool_sse(self, data):
        if not STATE["workspace"] or not is_configured(STATE["config"]):
            self._json({"error": "Configure the lab identity first."}, 400)
            return
        _, tool = find_tool(data.get("id") or "")
        if not tool:
            self._json({"error": "Unknown tool."}, 400)
            return
        purpose = str(data.get("purpose") or "").strip()
        if not purpose:
            self._json({"error": "A short reason/goal is required."}, 400)
            return
        fields = fill_defaults(tool, data.get("fields") or {}, STATE["config"])
        command = build_command(tool, fields, data.get("extra") or "", STATE["config"])
        description = tool.get("name") or command[0]

        if not STATE["tool_lock"].acquire(blocking=False):
            self._json({"error": "A tool is already running."}, 409)
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        def emit(obj):
            self.wfile.write(f"data: {json.dumps(obj)}\n\n".encode("utf-8"))
            self.wfile.flush()

        try:
            emit({"type": "command", "command": shlex.join(command)})
            ws = STATE["workspace"]
            identified = engine.identify_tool(command)
            tool_label = identified if identified != "generic" else Path(command[0]).name
            logs = ws / "logs"
            output_file = logs / f"{engine.safe_filename(tool_label)}_{engine.timestamp_seconds()}.txt"
            engine.append_timeline_note(
                ws,
                engine.classify_tool_category(identified, command),
                f"Starting {description}.",
                origin="automatic",
                tool=tool_label,
                command=shlex.join(command),
                purpose=purpose,
                outcome="Command is about to run.",
                metadata={"event": "attempt_started"},
            )
            result = run_tool_streaming(command, output_file, lambda line: emit({"type": "line", "text": line}))
            record = finish_tool_run(tool, command, purpose, description, result, output_file)
            emit({
                "type": "done",
                "exit_code": result["returncode"],
                "output_file": engine.relative_path(ws, output_file),
                "summary": record["summary"],
            })
        except FileNotFoundError:
            emit({"type": "error", "error": f"Command not found: {command[0]}"})
        except Exception as exc:
            emit({"type": "error", "error": str(exc)})
        finally:
            STATE["tool_lock"].release()


def open_browser(url: str):
    try:
        webbrowser.open(url)
    except Exception:
        pass


def start_logged_shell(log_file: Path):
    STATE["session_log"] = log_file
    STATE["session_active"] = True
    engine.append_timeline_note(
        STATE["workspace"],
        "SESSION",
        "Starting a terminal-logged shell for this engagement.",
        tool="script" if os.name != "nt" else "conpty",
        purpose="Capture the full terminal interaction, including native scan output.",
        evidence=[engine.relative_path(STATE["workspace"], log_file)],
    )
    print(f"\n[+] Session log: {log_file}")
    print("[+] Work in THIS terminal. Notes / tools GUI is the browser.\n")
    run_logged_shell(log_file)
    STATE["session_active"] = False
    if engine.verify_session_log(log_file):
        engine.manifest_add(STATE["workspace"], "session_logs", {
            "time": human_ts(),
            "file": engine.file_metadata(STATE["workspace"], log_file),
        })
        print("[+] Session log contains data.")
    else:
        print("[-] WARNING: session log looks empty.")


def serve(port: int):
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    STATE["port"] = port
    return httpd


def pick_port(preferred: int):
    for port in range(preferred, preferred + 20):
        try:
            probe = ThreadingHTTPServer(("127.0.0.1", port), Handler)
            probe.server_close()
            return port
        except OSError:
            continue
    raise RuntimeError("No free port in 8765–8784.")


def print_banner(url: str):
    print("=" * 60)
    print(f" HTB Helper {APP_VERSION}  —  local field notebook")
    print("=" * 60)
    print(f" GUI:      {url}")
    print(" Bind:     127.0.0.1 only (this machine)")
    if STATE["workspace"]:
        print(f" Workspace:{STATE['workspace']}")
    print()
    print(" Keep this terminal. Everything you type after logging starts")
    print(" is captured. Use the browser for markdown notes and tools.")
    print()
    print(" GUI keys:  Ctrl+S save   Ctrl+N stamp   Ctrl+1–8 tabs")
    print("=" * 60)


def parse_args():
    parser = argparse.ArgumentParser(description="HTB Helper local GUI")
    parser.add_argument("--config", default=str(ROOT / "config.json"))
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--gui-only", action="store_true", help="Serve the GUI without wrapping a logged shell.")
    parser.add_argument("--cli", action="store_true", help="Original numbered menu (htb_helper.py).")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--no-bootstrap", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--version", action="version", version=f"htb-helper {APP_VERSION}")
    return parser.parse_args()


def main():
    os.chdir(ROOT)
    args = parse_args()
    config_path = Path(args.config).expanduser()
    if not config_path.is_absolute():
        config_path = (ROOT / config_path).resolve()

    if not args.no_bootstrap:
        result = try_bootstrap()
        if result.get("installed"):
            print("[+] " + result["message"])
        elif not result.get("ok"):
            print("[!] Bootstrap: " + result.get("message", "failed"))

    config = load_or_none(config_path)
    if config is None and (ROOT / "config.example.json").exists() and not config_path.exists():
        shutil.copy(ROOT / "config.example.json", config_path)
        config = load_or_none(config_path)
    apply_config(config, config_path)

    if args.cli:
        sys.argv = [sys.argv[0], "--config", str(config_path)]
        engine.main()
        return

    if args.check:
        if STATE["workspace"]:
            engine.preflight_check(STATE["workspace"])
        else:
            print(json.dumps(preflight_payload(), indent=2))
        return

    port = pick_port(args.port)
    serve(port)
    url = f"http://127.0.0.1:{port}/"
    print_banner(url)
    if not args.no_browser:
        threading.Timer(0.6, open_browser, args=(url,)).start()

    if args.gui_only or not is_configured(STATE["config"]):
        if not is_configured(STATE["config"]):
            print("[*] Fill in the lab identity in the browser, then restart without --gui-only")
            print("    if you want this terminal wrapped in a session log.")
        print(f"[*] GUI only. Open {url}")
        print("[*] Ctrl+C to stop.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n[+] Stopped.")
        return

    log_file = engine.get_next_session_log(STATE["workspace"])
    try:
        start_logged_shell(log_file)
    except KeyboardInterrupt:
        print("\n[+] Logging stopped.")
    print(f"[*] GUI still at {url}  —  Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[+] Stopped.")


if __name__ == "__main__":
    main()
