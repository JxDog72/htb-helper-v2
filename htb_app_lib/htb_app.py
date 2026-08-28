#!/usr/bin/env python3
"""
HTB Helper 2.0 — local field notebook.

A stdlib-only localhost GUI (127.0.0.1) so notes can be real Markdown,
plus a logged shell in the terminal this process was started from.

Not a network service. Binds loopback only. No pip packages.
"""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
import argparse
import base64
import ipaddress
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
import webbrowser

import htb_helper as engine
from session_capture import (
    append_to_session_log,
    decode_log_bytes,
    inject_to_session,
    run_logged_shell,
    session_paused,
    set_session_paused,
)
from tools_catalog import COMMON_WORDLISTS, TOOL_GROUPS, TOOL_INFO

LIB = Path(__file__).resolve().parent
ROOT = LIB.parent
WEB = LIB / "web"
APP_VERSION = "2.0.0"
DEFAULT_PORT = 8765

STATE = {
    "config": None,
    "config_path": LIB / "config.json",
    "workspace": None,
    "session_log": None,
    "session_active": False,
    "port": DEFAULT_PORT,
    "tool_lock": threading.Lock(),
    "tool_proc": None,
    "tool_stop": threading.Event(),
    "notes_lock": threading.Lock(),
    "configured_event": threading.Event(),
    "session_ready": threading.Event(),
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
        STATE["configured_event"].set()
    else:
        STATE["workspace"] = None


def workspace_root_path():
    cfg = STATE["config"] or {}
    root = Path(cfg.get("workspace_root", "./machines")).expanduser()
    if not root.is_absolute():
        root = (ROOT / root).resolve()
    return root


def list_labs():
    root = workspace_root_path()
    labs = []
    if not root.is_dir():
        return labs
    current = STATE["workspace"].name if STATE["workspace"] else None
    for folder in sorted(p for p in root.iterdir() if p.is_dir()):
        meta = load_or_none(engine.metadata_path(folder)) or load_or_none(folder / "metadata.json") or {}
        labs.append({
            "id": folder.name,
            "student_id": meta.get("student_id") or "",
            "machine_name": meta.get("machine_name") or folder.name,
            "target_ip": meta.get("target_ip") or "",
            "target_port": meta.get("assigned_port"),
            "research_project": meta.get("research_project") or "",
            "current": folder.name == current,
        })
    return labs


def select_lab(folder_name: str):
    root = workspace_root_path()
    folder = (root / folder_name).resolve()
    try:
        folder.relative_to(root)
    except ValueError:
        raise RuntimeError("Lab folder must stay inside the machines directory.")
    if not folder.is_dir():
        raise RuntimeError(f"No lab folder named {folder_name}.")
    meta = load_or_none(engine.metadata_path(folder)) or load_or_none(folder / "metadata.json") or {}
    if not meta.get("student_id") or not meta.get("machine_name") or not meta.get("target_ip"):
        raise RuntimeError("That lab folder is missing machine_json/metadata.json (student, machine, IP).")
    prev = STATE["config"] or {}
    config = {
        "student_id": meta["student_id"],
        "machine_name": meta["machine_name"],
        "target_ip": meta["target_ip"],
        "target_port": meta.get("assigned_port"),
        "workspace_root": prev.get("workspace_root", "./machines"),
        "research_project": meta.get(
            "research_project",
            prev.get("research_project", "HTB Enterprise AI Generated Pentest Report Study"),
        ),
        "gui_port": prev.get("gui_port", DEFAULT_PORT),
    }
    save_config(STATE["config_path"], config)
    apply_config(config, STATE["config_path"])
    return config


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
    return engine.notes_file(ws)


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
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def append_student_note(category: str, body: str):
    ws = STATE["workspace"]
    if not ws:
        raise RuntimeError("Workspace is not configured yet.")
    category = (category or "NONE").strip().upper()
    body = (body or "").rstrip()
    if not body:
        raise RuntimeError("Note body is empty.")
    path = notes_path()
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    stamp = engine.format_workflow_stamp(existing, category)
    block = f"\n{stamp} {body}\n"
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
    ws = STATE["workspace"]
    path = notes_path()
    existing = path.read_text(encoding="utf-8") if path and path.exists() else ""
    stamp = engine.format_workflow_stamp(existing, category)
    return f"\n{stamp} "


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
    logs = engine.logs_dir(ws)
    shots = engine.screenshots_dir(ws)
    notes = read_notes()
    ev_path = engine.evidence_file(ws)
    evidence = ev_path.read_text(encoding="utf-8", errors="replace") if ev_path.exists() else ""
    manifest = engine.load_manifest(ws) or {}
    return {
        "session_logs": len(list(logs.glob("session*.log"))),
        "tool_runs": len(manifest.get("tool_runs") or []),
        "timeline_notes": len(re.findall(r"^\[\d{2}:\d{2}\]", notes, re.M)),
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


def unique_capture_path(prefix: str, suffix: str = ".txt"):
    """Next unused name: nmap_1.txt, nmap_2.txt, … counted from files already in logs/."""
    ws = STATE["workspace"]
    if not ws:
        raise RuntimeError("Workspace is not configured yet.")
    logs = engine.logs_dir(ws)
    logs.mkdir(parents=True, exist_ok=True)
    stem = engine.safe_filename(prefix) or "tool"
    pattern = re.compile(r"^" + re.escape(stem) + r"_(\d+)" + re.escape(suffix) + r"$")
    highest = 0
    for path in logs.iterdir():
        match = pattern.match(path.name)
        if match:
            highest = max(highest, int(match.group(1)))
    number = highest + 1
    dest = logs / f"{stem}_{number}{suffix}"
    while dest.exists():
        number += 1
        dest = logs / f"{stem}_{number}{suffix}"
    return dest


def retarget_nmap_on(command, nmap_file: Path):
    command = list(command)
    nmap_path = str(nmap_file)
    if "-oN" in command:
        index = command.index("-oN")
        if index + 1 < len(command):
            command[index + 1] = nmap_path
        else:
            command.append(nmap_path)
        return command
    if command:
        return command[:-1] + ["-oN", nmap_path, command[-1]]
    return ["nmap", "-oN", nmap_path]


def tee_command(cmd: str, rel: str):
    text = str(cmd or "").rstrip()
    if not text:
        return text
    if "| tee " in text or text.endswith("| tee"):
        return text
    return f'{text} | tee "{rel}"'


def log_files():
    ws = STATE["workspace"]
    if not ws:
        return []
    logs = engine.logs_dir(ws)
    names = []
    for path in sorted(logs.glob("*"), key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True):
        if path.is_file():
            names.append(path.name)
    return names


def read_log(name: str, offset: int = 0, tail: bool = False):
    ws = STATE["workspace"]
    if not ws:
        return {"text": "", "offset": 0, "name": name}
    path = (engine.logs_dir(ws) / name).resolve()
    path.relative_to(engine.logs_dir(ws).resolve())
    if not path.is_file():
        return {"text": "", "offset": 0, "name": name, "size": 0, "replace": True}
    size = path.stat().st_size
    if tail and offset > 0 and offset <= size:
        with path.open("rb") as handle:
            handle.seek(offset)
            chunk = handle.read()
        return {
            "text": decode_log_bytes(chunk),
            "offset": size,
            "name": name,
            "size": size,
            "replace": False,
        }
    data = path.read_bytes()
    text = decode_log_bytes(data)
    if len(text) > 400_000:
        text = text[-400_000:]
    return {"text": text, "offset": size, "name": name, "size": size, "replace": True}


def find_screenshot_command():
    for name in ("mate-screenshot", "gnome-screenshot", "scrot", "grim", "import"):
        if shutil.which(name):
            return name
    return None


def capture_screenshot(milestone, description):
    ws = STATE["workspace"]
    if not ws:
        raise RuntimeError("Workspace is not configured yet.")
    screenshots = engine.screenshots_dir(ws)
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
        "NONE",
        f"Screenshot: {description}",
        compact=True,
        metadata={"milestone": milestone},
    )
    return engine.relative_path(ws, dest)


def tool_target(fields, config):
    return str(fields.get("target") or config.get("target_ip") or "").strip()


def tool_port(fields, config, *, fallback=False):
    raw = fields.get("port")
    if raw in (None, "") and fallback:
        raw = config.get("target_port")
    if raw in (None, "", 0, "0"):
        return None
    try:
        port = int(raw)
    except (TypeError, ValueError):
        raise RuntimeError("Port must be an integer 1–65535.")
    if not 1 <= port <= 65535:
        raise RuntimeError("Port must be between 1 and 65535.")
    return port


def substitute(value: str, fields: dict, config: dict):
    target = tool_target(fields, config)
    port = tool_port(fields, config)
    mapping = {
        "target": target,
        "url": fields.get("url") or (f"http://{target}" if target else ""),
        "wordlist": fields.get("wordlist") or "",
        "query": fields.get("query") or "",
        "port": "" if port is None else str(port),
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
    target = tool_target(fields, config)
    port = tool_port(fields, config, fallback=(kind == "nmap-port"))
    if not target and kind != "custom":
        raise RuntimeError("Target IP is required.")
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
            raise RuntimeError("Type the command in the Command box.")
        if engine.shell_meta_present(command_text):
            raise RuntimeError("Pipes, redirects, and ';' are not allowed here.")
        return shlex.split(command_text) + extra_parts

    if kind in ("nmap", "nmap-port"):
        nmap_args = list(tool.get("nmap_args") or [])
        full_tcp = "-p-" in nmap_args
        if kind == "nmap-port" and port is None:
            raise RuntimeError("Set a port for this scan (lab assigned port, or another port you found).")
        if kind == "nmap-port" or (port and not full_tcp):
            nmap_file = unique_capture_path(f"nmap_port_{port}", ".nmap")
        else:
            nmap_file = unique_capture_path("nmap_scan", ".nmap")
        command = ["nmap"] + nmap_args
        # nmap -p- must stay all TCP ports. Assigned lab port is only used
        # for "Nmap assigned port", or if the student typed a Port on a
        # non-full scan.
        if kind == "nmap-port":
            command = [arg for arg in command if arg != "-p-"]
            command.extend(["-p", str(port)])
        elif port and not full_tcp and "-p" not in command:
            command.extend(["-p", str(port)])
        # .txt is the streamed capture; .nmap is nmap's own text format. No xml/gnmap.
        command.extend(["-oN", str(nmap_file), target])
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


def format_command(command):
    if os.name == "nt":
        return subprocess.list2cmdline(command)
    return shlex.join(command)


def parse_command_override(text):
    command_text = str(text or "").strip()
    if not command_text:
        raise RuntimeError("Command is empty.")
    if engine.shell_meta_present(command_text):
        raise RuntimeError("Pipes, redirects, and ';' are not allowed. The helper already captures output.")
    parts = shlex.split(command_text, posix=(os.name != "nt"))
    if not parts:
        raise RuntimeError("Command is empty.")
    return parts


def collect_tool_fields(data):
    _, tool = find_tool(data.get("id") or "")
    if not tool:
        raise RuntimeError("Unknown tool.")
    if not STATE["workspace"] or not is_configured(STATE["config"]):
        raise RuntimeError("Configure the lab identity first.")
    fields = fill_defaults(tool, data.get("fields") or {}, STATE["config"])
    return tool, fields


def resolve_run_command(tool, fields, data):
    if data.get("command_edited") or tool.get("kind") == "custom":
        override = str(data.get("command") or "").strip()
        if override:
            return parse_command_override(override)
        if tool.get("kind") == "custom":
            raise RuntimeError("Type the command in the Command box.")
    return build_command(tool, fields, data.get("extra") or "", STATE["config"])


def stop_running_tool():
    proc = STATE.get("tool_proc")
    if proc is None or proc.poll() is not None:
        return False
    STATE["tool_stop"].set()
    try:
        if os.name != "nt":
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        else:
            proc.terminate()
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
    return True


def fill_defaults(tool, fields, config):
    fields = dict(fields or {})
    if not str(fields.get("target") or "").strip():
        fields["target"] = str(config.get("target_ip") or "")
    if tool.get("kind") == "nmap-port" and not str(fields.get("port") or "").strip():
        if config.get("target_port") not in (None, "", 0):
            fields["port"] = str(config.get("target_port"))
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
    logs = engine.logs_dir(ws)
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
    code = 1
    output_file.parent.mkdir(parents=True, exist_ok=True)
    popen_kw = dict(
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
        bufsize=1,
    )
    if os.name == "nt":
        popen_kw["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        popen_kw["start_new_session"] = True
    with output_file.open("w", encoding="utf-8", errors="replace") as handle:
        process = subprocess.Popen(command, **popen_kw)
        STATE["tool_proc"] = process
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
            stop_running_tool()
            try:
                code = process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                code = process.wait()
        finally:
            STATE["tool_proc"] = None
    if STATE["tool_stop"].is_set():
        interrupted = True
    return {
        "returncode": code,
        "output": "".join(captured),
        "interrupted": interrupted,
        "truncated": truncated,
    }


def finish_tool_run(tool, command, purpose, description, result, output_file, include_notes=False):
    ws = STATE["workspace"]
    identified = engine.identify_tool(command)
    tool_label = identified if identified != "generic" else Path(command[0]).name
    category = engine.classify_tool_category(identified, command)
    summary, findings, metadata = engine.analyze_tool_output(identified, result["output"], result["returncode"])
    if result["truncated"]:
        findings.append("Parser used the first part of a large capture; the raw file is complete.")
    outcome = engine.classify_outcome(result["returncode"], result["interrupted"])
    rel = engine.relative_path(ws, output_file)
    engine.save_command_record(
        ws,
        command,
        description,
        purpose,
        findings=findings,
        output_file=rel,
    )
    if include_notes:
        with STATE["notes_lock"]:
            engine.append_timeline_note(
                ws,
                "TOOL",
                summary,
                tool=tool_label,
                command=format_command(command),
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


def _format_finding_line(eid, phase, description, when=""):
    label = str(eid)
    if phase:
        label += f" ({phase})"
    if when:
        label += f" [{when}]"
    label += f": {description}"
    return f"- {label}"


def evidence_suggestion_lines(workspace):
    """Short bullets from evidence.md — no headings, for the student to rewrite."""
    path = engine.evidence_file(workspace)
    if not path.exists():
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    suggestions = []
    current_id = None
    phase = ""
    description = ""
    when = ""
    for line in text.splitlines():
        heading = re.match(r"^## (E-\d+)\s*$", line)
        if heading:
            if current_id and description:
                suggestions.append(_format_finding_line(current_id, phase, description, when))
            current_id = heading.group(1)
            phase = ""
            description = ""
            when = ""
            continue
        if line.startswith("- Phase:"):
            phase = line.split(":", 1)[1].strip()
        elif line.startswith("- Description:"):
            description = line.split(":", 1)[1].strip()
        elif line.startswith("- Time:"):
            when = line.split(":", 1)[1].strip()
    if current_id and description:
        suggestions.append(_format_finding_line(current_id, phase, description, when))
    return suggestions


def report_path():
    ws = STATE["workspace"]
    if not ws:
        return None
    return engine.report_file(ws)


def write_report(text: str):
    path = report_path()
    if not path:
        raise RuntimeError("Workspace is not configured yet.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def save_pasted_image(data_b64: str, mime: str = "", dest="report"):
    ws = STATE["workspace"]
    if not ws:
        raise RuntimeError("Workspace is not configured yet.")
    raw = re.sub(r"^data:[^;]+;base64,", "", data_b64)
    blob = base64.b64decode(raw)
    ext = "png"
    mime = (mime or "").lower()
    if "jpeg" in mime or "jpg" in mime:
        ext = "jpg"
    elif "gif" in mime:
        ext = "gif"
    elif "webp" in mime:
        ext = "webp"
    if dest == "notes":
        folder = engine.notes_dir(ws) / "media"
    else:
        folder = engine.report_media_dir(ws)
    folder.mkdir(parents=True, exist_ok=True)
    name = f"paste_{engine.timestamp_seconds()}.{ext}"
    path = folder / name
    path.write_bytes(blob)
    return engine.relative_path(ws, path)


def findings_insert_block():
    ws = STATE["workspace"]
    if not ws:
        raise RuntimeError("Workspace is not configured yet.")
    suggestions = evidence_suggestion_lines(ws)
    if not suggestions:
        return ""
    return "\n".join(suggestions) + "\n"


def merge_findings_into_report(text, new_lines):
    """Append new E-ID bullets at the *end* of ## Findings (not above older ones)."""
    text = text or ""
    existing = {m.group(0).upper() for m in re.finditer(r"\bE-\d+\b", text, flags=re.I)}
    fresh = []
    for line in new_lines:
        line = str(line).rstrip()
        if not line:
            continue
        hit = re.search(r"\bE-\d+\b", line, flags=re.I)
        if hit and hit.group(0).upper() in existing:
            continue
        fresh.append(line)
        if hit:
            existing.add(hit.group(0).upper())
    if not fresh:
        return text, False
    block = "\n".join(fresh) + "\n"
    marker = "## Findings"
    index = text.find(marker)
    if index < 0:
        joined = text.rstrip() + "\n\n## Findings\n\n" + block
        return joined, True
    after = text.find("\n", index)
    start = after + 1 if after >= 0 else len(text)
    nxt = re.search(r"^## ", text[start:], flags=re.M)
    insert_at = start + nxt.start() if nxt else len(text)
    head = text[:insert_at].rstrip() + "\n\n"
    tail = text[insert_at:]
    if tail and not tail.startswith("\n") and not tail.startswith("##"):
        tail = "\n" + tail
    elif tail.startswith("##"):
        tail = "\n" + tail
    return head + block + tail, True


def append_findings_to_report_file(lines):
    path = report_path()
    if not path:
        raise RuntimeError("Workspace is not configured yet.")
    path.parent.mkdir(parents=True, exist_ok=True)
    current = path.read_text(encoding="utf-8") if path.exists() else engine.default_report_text(STATE["config"] or {})
    updated, changed = merge_findings_into_report(current, lines)
    if changed:
        path.write_text(updated, encoding="utf-8")
    return updated, changed


def workspace_file(rel: str):
    ws = STATE["workspace"]
    if not ws:
        raise RuntimeError("Workspace is not configured yet.")
    path = (ws / rel).resolve()
    path.relative_to(ws.resolve())
    if not path.is_file():
        raise RuntimeError("File not found.")
    return path


def build_report():
    ws = STATE["workspace"]
    config = STATE["config"] or {}
    if not ws:
        raise RuntimeError("Workspace is not configured yet.")
    text = engine.default_report_text(config, evidence_suggestion_lines(ws) or None)
    dest = engine.report_file(ws)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding="utf-8")
    return text


def log_gui_tool_to_session(command, output_file, result):
    stamp = human_ts()
    cmd = format_command(command)
    snippet = (result.get("output") or "")[-8000:]
    code = result.get("returncode")
    block = (
        f"\n===== GUI tool {stamp} =====\n"
        f"$ {cmd}\n"
        f"{snippet}"
        f"\n===== GUI tool exit {code}  ({engine.relative_path(STATE['workspace'], output_file) if STATE['workspace'] else output_file}) =====\n"
    )
    if append_to_session_log(block):
        return True
    log = STATE.get("session_log")
    if not log:
        return False
    try:
        Path(log).parent.mkdir(parents=True, exist_ok=True)
        with Path(log).open("a", encoding="utf-8", errors="replace") as handle:
            handle.write(block)
        return True
    except OSError:
        return False


def next_spawned_session_log(workspace):
    logs = engine.logs_dir(workspace)
    logs.mkdir(parents=True, exist_ok=True)
    number = 2
    while (logs / f"terminal{number}_session.log").exists():
        number += 1
    return (logs / f"terminal{number}_session.log").resolve()


def spawn_logged_terminal():
    ws = STATE["workspace"]
    if not ws:
        raise RuntimeError("Pick or create a lab first.")
    log_file = next_spawned_session_log(ws)
    inner = [
        sys.executable,
        str(LIB / "htb_app.py"),
        "--logged-shell",
        str(log_file),
        "--config",
        str(STATE["config_path"]),
        "--no-bootstrap",
        "--no-browser",
    ]
    cwd = str(ws)
    if os.name == "nt":
        flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0x00000010)
        subprocess.Popen(inner, cwd=cwd, creationflags=flags)
        return log_file.name
    quoted = " ".join(shlex.quote(part) for part in inner)
    launchers = []
    if shutil.which("xfce4-terminal"):
        launchers.append(["xfce4-terminal", f"--working-directory={cwd}", "-e", quoted])
    if shutil.which("mate-terminal"):
        launchers.append(["mate-terminal", f"--working-directory={cwd}", "-e", quoted])
    if shutil.which("gnome-terminal"):
        launchers.append(["gnome-terminal", f"--working-directory={cwd}", "--"] + inner)
    if shutil.which("konsole"):
        launchers.append(["konsole", "--workdir", cwd, "-e"] + inner)
    if shutil.which("x-terminal-emulator"):
        launchers.append(["x-terminal-emulator", "-e"] + inner)
    if shutil.which("xterm"):
        launchers.append(["xterm", "-e"] + inner)
    last_err = "No terminal emulator found (xfce4-terminal, mate-terminal, gnome-terminal, xterm)."
    for cmd in launchers:
        try:
            subprocess.Popen(
                cmd,
                cwd=cwd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
            )
            return log_file.name
        except OSError as exc:
            last_err = str(exc)
    raise RuntimeError(last_err)


def prepare_terminal_send(data):
    """Unique .txt (and .nmap) plus optional notes, then a line to type into the shell."""
    ws = STATE["workspace"]
    if not ws or not is_configured(STATE["config"]):
        raise RuntimeError("Pick or create a lab first.")
    command_text = str(data.get("command") or "").strip()
    tool = None
    fields = {}
    if data.get("id"):
        try:
            tool, fields = collect_tool_fields(data)
        except Exception:
            tool, fields = None, {}
        if not command_text:
            built = resolve_run_command(tool, fields, data)
            command_text = format_command(built)
    if not command_text:
        raise RuntimeError("Command is empty.")
    label = "command"
    if tool:
        label = tool.get("bin") or tool.get("id") or label
    else:
        first = command_text.split()[0] if command_text.split() else "command"
        label = Path(first).name
    if "nmap" in label.lower() or command_text.lower().startswith("nmap "):
        nmap_file = unique_capture_path("nmap_scan", ".nmap")
        try:
            parts = shlex.split(command_text, posix=(os.name != "nt"))
            command_text = format_command(retarget_nmap_on(parts, nmap_file))
        except ValueError:
            pass
    out = unique_capture_path(label, ".txt")
    rel = engine.relative_path(ws, out)
    send = tee_command(command_text, rel)
    include_notes = data.get("include_notes") in (True, "yes", "true", 1, "1")
    notes_text = None
    if include_notes:
        purpose = str(data.get("purpose") or "").strip() or "Sent to the logged terminal."
        description = (tool or {}).get("name") or label
        with STATE["notes_lock"]:
            engine.append_timeline_note(
                ws,
                "TOOL",
                f"Sent to terminal ({description}). Output: {rel}",
                tool=label,
                command=send,
                purpose=purpose,
                evidence=[rel],
            )
        notes_text = read_notes()
    return {
        "ok": True,
        "send_command": send,
        "command": command_text,
        "output_file": rel,
        "copy_command": send,
        "notes": notes_text,
    }


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
        # Keep HTTP access lines out of the logged work terminal.
        return

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
        if path in ("/examples/view", "/example.html"):
            self._send(200, "text/html; charset=utf-8", (WEB / "example.html").read_bytes())
            return
        if path in ("/examples/notes.md", "/examples/report.md"):
            name = "notes.md" if path.endswith("notes.md") else "report.md"
            dest = WEB / "examples" / name
            if not dest.is_file():
                self._json({"error": "Example file missing."}, 404)
                return
            self._send(200, "text/markdown; charset=utf-8", dest.read_bytes())
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
                    "session_paused": session_paused(),
                    "session_log": str(STATE["session_log"]) if STATE["session_log"] else None,
                    "port": STATE["port"],
                    "stats": stats_payload() if STATE["workspace"] else {},
                    "labs": list_labs(),
                    "current_lab": STATE["workspace"].name if STATE["workspace"] else None,
                })
                return
            if path == "/api/labs":
                self._json({
                    "labs": list_labs(),
                    "current_lab": STATE["workspace"].name if STATE["workspace"] else None,
                })
                return
            if path == "/api/notes":
                self._json({"text": read_notes()})
                return
            if path == "/api/evidence":
                ws = STATE["workspace"]
                text = ""
                ev_path = engine.evidence_file(ws) if ws else None
                if ev_path and ev_path.exists():
                    text = ev_path.read_text(encoding="utf-8", errors="replace")
                self._json({"text": text})
                return
            if path == "/api/files":
                self._json({"files": list_workspace_files()})
                return
            if path == "/api/logs":
                name = (query.get("name") or ["session.log"])[0]
                offset = int((query.get("offset") or ["0"])[0] or 0)
                tail = (query.get("tail") or ["0"])[0] in ("1", "true", "yes")
                self._json({"files": log_files(), **read_log(name, offset, tail=tail)})
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
                path_r = report_path()
                text = ""
                if path_r and path_r.exists():
                    text = path_r.read_text(encoding="utf-8", errors="replace")
                self._json({"text": text})
                return
            if path == "/api/media":
                rel = (query.get("path") or [""])[0]
                dest = workspace_file(rel)
                suffix = dest.suffix.lower()
                types = {
                    ".png": "image/png",
                    ".jpg": "image/jpeg",
                    ".jpeg": "image/jpeg",
                    ".gif": "image/gif",
                    ".webp": "image/webp",
                }
                body = dest.read_bytes()
                self._send(200, types.get(suffix, "application/octet-stream"), body)
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
            if parsed.path == "/api/report":
                write_report(data.get("text") or "")
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
                STATE["session_ready"].set()
                self._json({"ok": True, "workspace": str(STATE["workspace"])})
                return

            if path == "/api/labs/select":
                folder = str(data.get("id") or "").strip()
                if not folder:
                    raise RuntimeError("Pick an existing lab.")
                select_lab(folder)
                STATE["session_ready"].set()
                self._json({
                    "ok": True,
                    "workspace": str(STATE["workspace"]),
                    "config": STATE["config"],
                })
                return

            if path == "/api/labs/ready":
                if not is_configured(STATE["config"]):
                    raise RuntimeError("Pick or create a lab first.")
                STATE["session_ready"].set()
                self._json({"ok": True})
                return

            if path == "/api/notes/append":
                block = append_student_note(data.get("category") or "NONE", data.get("body") or "")
                self._json({"ok": True, "block": block, "text": read_notes()})
                return

            if path == "/api/notes/stamp":
                heading = stamp_heading(data.get("category") or "NONE")
                self._json({"ok": True, "heading": heading})
                return

            if path == "/api/evidence":
                ws = STATE["workspace"]
                if not ws:
                    raise RuntimeError("Workspace is not configured yet.")
                ev_path = engine.evidence_file(ws)
                evidence_id = engine.get_next_evidence_id(ev_path)
                phase = str(data.get("phase") or "").strip()
                description = str(data.get("description") or "").strip()
                source = str(data.get("source") or "").strip()
                source_na = bool(data.get("source_na"))
                if not phase or not description:
                    raise RuntimeError("Phase and description are required.")
                if source_na or source.upper() in ("N/A", "NA"):
                    source = "N/A"
                else:
                    if not source:
                        raise RuntimeError("Source file is required, or check Source N/A.")
                    source_path = (ws / source).resolve()
                    source_path.relative_to(ws.resolve())
                with ev_path.open("a", encoding="utf-8") as handle:
                    handle.write(f"\n## E-{evidence_id:03d}\n")
                    handle.write(f"- Time: {human_ts()}\n")
                    handle.write(f"- Phase: {phase}\n")
                    handle.write(f"- Description: {description}\n")
                    handle.write(f"- Source: {source}\n")
                engine.manifest_add(ws, "evidence", {
                    "id": f"E-{evidence_id:03d}",
                    "time": human_ts(),
                    "phase": phase,
                    "description": description,
                    "source": source,
                })
                engine.append_timeline_note(
                    ws,
                    "NONE",
                    f"E-{evidence_id:03d}: {description}",
                    origin="student",
                    compact=True,
                )
                text = ev_path.read_text(encoding="utf-8")
                finding = _format_finding_line(
                    f"E-{evidence_id:03d}", phase, description, human_ts(),
                )
                report_text, _ = append_findings_to_report_file([finding])
                self._json({
                    "ok": True,
                    "id": f"E-{evidence_id:03d}",
                    "text": text,
                    "finding": finding,
                    "report": report_text,
                })
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
                encrypt = bool(data.get("encrypt"))
                password = str(data.get("password") or "")
                archive, copied, kind = engine.create_export_archive(
                    ws, encrypt=encrypt, password=password,
                )
                host = str(data.get("hostname") or "").strip()
                user = str(data.get("username") or "htb-username").strip()
                if host:
                    scp = f"scp {user}@{host}:{archive} ."
                else:
                    scp = (
                        f"scp {user}@htb-YOURINSTANCE.htb-cloud.com:{archive} ."
                    )
                self._json({
                    "ok": True,
                    "file": str(Path(archive).resolve()),
                    "kind": kind,
                    "copied": copied,
                    "scp": scp,
                    "seven_zip": bool(engine.seven_zip_bin()),
                    "name": Path(archive).name,
                })
                return

            if path == "/api/report":
                text = build_report()
                self._json({"ok": True, "text": text})
                return

            if path == "/api/report/findings":
                block = findings_insert_block()
                if not block:
                    raise RuntimeError("No evidence entries to insert yet.")
                path_r = report_path()
                current = path_r.read_text(encoding="utf-8") if path_r and path_r.exists() else ""
                lines = [ln for ln in block.splitlines() if ln.strip()]
                updated, changed = merge_findings_into_report(current, lines)
                if changed and path_r:
                    write_report(updated)
                self._json({"ok": True, "block": block, "report": updated, "changed": changed})
                return

            if path == "/api/terminal/spawn":
                name = spawn_logged_terminal()
                self._json({"ok": True, "file": name})
                return

            if path == "/api/tools/inject":
                payload = prepare_terminal_send(data)
                if not STATE["session_active"]:
                    raise RuntimeError("No live session. Start with ./htb (not --gui-only), then Send to terminal.")
                if not inject_to_session(payload["send_command"]):
                    raise RuntimeError("Could not type into the logged terminal.")
                self._json(payload)
                return

            if path == "/api/session":
                action = str(data.get("action") or "").strip().lower()
                if action not in ("pause", "resume"):
                    raise RuntimeError("action must be pause or resume.")
                if not STATE["session_active"]:
                    raise RuntimeError("No live session. Start with ./htb (not --gui-only).")
                set_session_paused(action == "pause")
                self._json({
                    "ok": True,
                    "paused": session_paused(),
                    "session_active": STATE["session_active"],
                })
                return

            if path == "/api/image":
                rel = save_pasted_image(
                    data.get("data") or "",
                    data.get("mime") or "",
                    dest=str(data.get("dest") or "report"),
                )
                self._json({"ok": True, "path": rel})
                return

            if path == "/api/bootstrap":
                self._json(try_bootstrap())
                return

            if path == "/api/tools/preview":
                tool, fields = collect_tool_fields(data)
                command = build_command(tool, fields, data.get("extra") or "", STATE["config"])
                label = tool.get("bin") or tool.get("id") or command[0]
                out = unique_capture_path(label, ".txt")
                rel = engine.relative_path(STATE["workspace"], out)
                cmd = format_command(command)
                self._json({
                    "command": cmd,
                    "output_file": rel,
                    "copy_command": tee_command(cmd, rel),
                })
                return

            if path == "/api/tools/stop":
                self._json({"ok": True, "stopped": stop_running_tool()})
                return

            if path == "/api/tools/run":
                self._run_tool_sse(data)
                return
        except Exception as exc:
            self._json({"error": str(exc)}, 400)
            return

        self._json({"error": "not found"}, 404)

    def _run_tool_sse(self, data):
        tool, fields = collect_tool_fields(data)
        purpose = str(data.get("purpose") or "").strip()
        if not purpose:
            self._json({"error": "A short reason/goal is required."}, 400)
            return
        command = resolve_run_command(tool, fields, data)
        if command and Path(command[0]).name.lower().startswith("nmap"):
            command = retarget_nmap_on(command, unique_capture_path("nmap_scan", ".nmap"))
        description = tool.get("name") or command[0]

        if not STATE["tool_lock"].acquire(blocking=False):
            self._json({"error": "A tool is already running."}, 409)
            return
        STATE["tool_stop"].clear()

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        def emit(obj):
            self.wfile.write(f"data: {json.dumps(obj)}\n\n".encode("utf-8"))
            self.wfile.flush()

        try:
            cmd = format_command(command)
            ws = STATE["workspace"]
            identified = engine.identify_tool(command)
            tool_label = identified if identified != "generic" else Path(command[0]).name
            output_file = unique_capture_path(tool_label, ".txt")
            rel = engine.relative_path(ws, output_file)
            emit({
                "type": "command",
                "command": cmd,
                "output_file": rel,
                "copy_command": f'{cmd} | tee "{rel}"',
            })
            result = run_tool_streaming(command, output_file, lambda line: emit({"type": "line", "text": line}))
            log_gui_tool_to_session(command, output_file, result)
            include_notes = data.get("include_notes") in (True, "yes", "true", 1, "1")
            record = finish_tool_run(
                tool, command, purpose, description, result, output_file,
                include_notes=include_notes,
            )
            emit({
                "type": "done",
                "exit_code": result["returncode"],
                "output_file": rel,
                "notes": read_notes() if include_notes else None,
            })
        except FileNotFoundError:
            emit({"type": "error", "error": f"Command not found: {command[0]}"})
        except Exception as exc:
            emit({"type": "error", "error": str(exc)})
        finally:
            STATE["tool_lock"].release()


def open_browser(url: str):
    """Open the GUI without dumping GTK/GPU errors into the logged terminal."""
    try:
        if os.name == "nt":
            os.startfile(url)
            return
        opener = shutil.which("xdg-open") or shutil.which("gio")
        if opener:
            subprocess.Popen(
                [opener, url],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
            )
            return
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
        compact=True,
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
    parser.add_argument("--config", default=str(LIB / "config.json"))
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--gui-only", action="store_true", help="Serve the GUI without wrapping a logged shell.")
    parser.add_argument("--cli", action="store_true", help="Numbered menu (htb_helper.py). Option 14: view/change machine or start a new lab.")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--no-bootstrap", action="store_true", help="Skip apt install of python3/nmap/bsdutils/xdg-utils on start.")
    parser.add_argument("--logged-shell", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--version", action="version", version=f"htb-helper {APP_VERSION}")
    return parser.parse_args()


def main():
    os.chdir(ROOT)
    args = parse_args()
    config_path = Path(args.config).expanduser()
    if not config_path.is_absolute():
        config_path = (ROOT / config_path).resolve()

    if not args.no_bootstrap and not args.logged_shell:
        result = try_bootstrap()
        if result.get("installed"):
            print("[+] " + result["message"])
        elif not result.get("ok"):
            print("[!] Bootstrap: " + result.get("message", "failed"))

    config = load_or_none(config_path)
    if config is None and (LIB / "config.example.json").exists() and not config_path.exists():
        shutil.copy(LIB / "config.example.json", config_path)
        config = load_or_none(config_path)
    apply_config(config, config_path)

    if args.logged_shell:
        log_path = Path(args.logged_shell).expanduser()
        if not log_path.is_absolute():
            log_path = (ROOT / log_path).resolve()
        if STATE["workspace"]:
            os.chdir(STATE["workspace"])
        print(f"[+] Extra terminal log: {log_path}")
        print("[+] Working directory is the lab folder. Type exit when done.")
        run_logged_shell(log_path)
        return

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

    if args.gui_only:
        print(f"[*] GUI only. Open {url}")
        print("[*] This terminal stays with the GUI. Ctrl+C to stop.")
        print("[*] For a logged work shell, run ./htb  (without --gui-only).")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n[+] Stopped.")
        return

    print("[*] In the browser: open an existing lab or create a new one.")
    print("[*] This terminal becomes the logged shell after you choose.")
    print("[*] Do not Ctrl+C unless you want to quit the helper.")
    try:
        while not STATE["session_ready"].wait(timeout=0.5):
            pass
    except KeyboardInterrupt:
        print("\n[+] Stopped.")
        return
    print("[+] Workspace ready. Starting logged shell.\n")

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
