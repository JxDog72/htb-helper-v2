#!/usr/bin/env python3
"""
HTB Enterprise Research Study Helper v3.4.0

Purpose:
    Collect consistent, timestamped research data during an authorized
    HTB Enterprise engagement while preserving the student's own reasoning.

Design goals:
    - Keep a full terminal session log with util-linux `script`.
    - Save raw output from scanning/enumeration tools to separate files.
    - Generate factual, tool-aware notes in real time.
    - Ask the student for the purpose/reason before each tool run.
    - Preserve failed attempts and non-zero exit codes.
    - Capture milestone screenshots and evidence references.
    - Offer semi-automatic milestone screenshots after relevant events.
    - Maintain a machine-readable manifest with file hashes.
    - Never infer exploitation success, credentials, flags, or student intent.
    - Do not automate exploitation or privilege escalation.

Supported automatic note parsers include:
    Nmap, ping, Gobuster, ffuf, Feroxbuster, dirsearch, Nikto, WhatWeb,
    httpx, nuclei, dig, nslookup, enum4linux/enum4linux-ng,
    smbclient, rpcclient, ldapsearch, NetExec/CrackMapExec, curl,
    wget, and generic commands.

This tool is intended only for systems the student is authorized to test.
"""

from pathlib import Path
from datetime import datetime
import argparse
import hashlib
import ipaddress
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from urllib.parse import urlparse


APP_NAME = "HTB Enterprise Research Study Helper"
APP_VERSION = "3.4.0"
MAX_ANALYSIS_CHARS = 2_000_000
MAX_NOTE_FINDINGS = 25
ANSI_RE = re.compile(r"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~]|].*?(?:\x07|\x1b\\))")
SCREENSHOT_MILESTONES = {
    "initial_recon": "Initial reconnaissance",
    "initial_foothold": "Initial foothold",
    "vulnerability_evidence": "Vulnerability evidence",
    "privilege_escalation": "Privilege escalation",
    "user_flag": "User flag",
    "root_admin_flag": "Root/admin flag",
    "other": "Other",
}


# ============================================================
# GENERAL UTILITIES
# ============================================================

def timestamp():
    return datetime.now().strftime("%H:%M")


def timestamp_seconds():
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def human_timestamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def safe_filename(value):
    value = str(value).strip().lower()
    value = re.sub(r"[^a-zA-Z0-9._-]+", "_", value)
    value = re.sub(r"_+", "_", value)
    return value.strip("._-")


def command_exists(command):
    return shutil.which(command) is not None


def pause():
    input("\nPress Enter to continue...")


def relative_path(workspace, path):
    path = Path(path)
    try:
        return path.resolve().relative_to(workspace.resolve()).as_posix()
    except (ValueError, OSError):
        return str(path)


def sha256_file(path):
    digest = hashlib.sha256()
    try:
        with Path(path).open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def file_metadata(workspace, path):
    path = Path(path)
    if not path.exists() or not path.is_file():
        return None
    try:
        size = path.stat().st_size
    except OSError:
        size = None
    return {
        "file": relative_path(workspace, path),
        "size": size,
        "sha256": sha256_file(path),
    }


def sanitize_note_text(value, limit=500):
    """Reduce accidental credential/token disclosure in generated notes.

    Raw tool output is NOT modified. Redaction applies only to summaries.
    """
    text = str(value).replace("\r", " ").replace("\n", " ").strip()
    text = re.sub(r"\s+", " ", text)

    secret_patterns = [
        r"(?i)\b(password|passwd|pwd)\s*[:=]\s*\S+",
        r"(?i)\b(token|access[_-]?token|api[_-]?key|secret)\s*[:=]\s*\S+",
        r"(?i)\bauthorization\s*:\s*\S+(?:\s+\S+)?",
        r"(?i)\bcookie\s*:\s*\S+",
        r"(?i)\bset-cookie\s*:\s*\S+",
    ]
    for pattern in secret_patterns:
        text = re.sub(pattern, lambda m: m.group(0).split(":", 1)[0].split("=", 1)[0] + ": [REDACTED]", text)

    if len(text) > limit:
        return text[: max(0, limit - 3)] + "..."
    return text


def unique_preserve(values):
    seen = set()
    result = []
    for value in values:
        key = str(value)
        if key not in seen:
            seen.add(key)
            result.append(value)
    return result


def strip_ansi(text):
    return ANSI_RE.sub("", str(text or ""))


def read_multiline(prompt, *, end_marker=".done", allow_empty=False):
    """Read paste-friendly multiline text until an explicit marker is entered.

    Linux terminals normally paste with Ctrl+Shift+V or right-click. Using an
    explicit marker prevents a multiline paste from spilling into the next
    research-note prompt.
    """
    print(f"\n{prompt}")
    print(f"Paste/type as many lines as needed. Enter {end_marker!r} on a line by itself when finished.")
    lines = []

    while True:
        try:
            line = input("> ")
        except EOFError:
            break

        if line.strip() == end_marker:
            break

        lines.append(line.rstrip())

    value = "\n".join(lines).strip()
    if value or allow_empty:
        return value

    print("[-] This field cannot be empty.")
    return None


def sanitize_note_multiline(value, limit=4000):
    """Redact note text while preserving line breaks for student-authored notes."""
    raw = str(value).replace("\r", "")
    cleaned_lines = []
    for line in raw.splitlines():
        cleaned_lines.append(sanitize_note_text(line, limit=1000))
    text = "\n".join(cleaned_lines).strip()
    if len(text) > limit:
        return text[: max(0, limit - 3)] + "..."
    return text


def write_note_field(handle, label, value):
    """Write a Markdown field without losing pasted line breaks."""
    if value is None:
        return
    lines = str(value).splitlines() or [""]
    handle.write(f"- {label}: {lines[0]}\n")
    for line in lines[1:]:
        handle.write(f"  {line}\n")


def prompt_purpose(default=None):
    """Capture the student's reason before running a tool."""
    if default:
        purpose = input(f"Reason/goal [{default}]: ").strip()
        return purpose or default

    while True:
        purpose = input("Reason/goal for this command: ").strip()
        if purpose:
            return purpose
        print("[-] A short reason/goal is required for the research notes.")


def shell_meta_present(command_text):
    """Detect shell operators unsupported by the direct command runner."""
    return bool(re.search(r"(?:\|\||&&|[|;<>])", command_text))


# ============================================================
# CONFIGURATION
# ============================================================

def load_config(config_path):
    path = Path(config_path)
    if not path.exists():
        print(f"[-] Configuration file not found: {path}")
        sys.exit(1)

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"[-] Invalid JSON configuration: {exc}")
        sys.exit(1)
    except OSError as exc:
        print(f"[-] Could not read configuration: {exc}")
        sys.exit(1)


def save_config(config_path, config):
    path = Path(config_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=4) + "\n", encoding="utf-8")


def validate_config(config):
    for key in ("student_id", "machine_name", "target_ip"):
        if key not in config or not str(config[key]).strip():
            print(f"[-] Missing or empty configuration field: {key}")
            return False

    try:
        ipaddress.ip_address(str(config["target_ip"]).strip())
    except ValueError:
        print(f"[-] Invalid target IP: {config['target_ip']}")
        return False

    target_port = config.get("target_port")
    if target_port not in (None, "", 0):
        try:
            port = int(target_port)
        except (TypeError, ValueError):
            print("[-] target_port must be an integer.")
            return False
        if not 1 <= port <= 65535:
            print("[-] target_port must be between 1 and 65535.")
            return False

    return True


def workspace_from_config(config):
    root = Path(config.get("workspace_root", "./machines")).expanduser()
    student_id = safe_filename(config["student_id"])
    machine_name = safe_filename(config["machine_name"])
    derived = root / f"{student_id}_{machine_name}"
    raw = str(config.get("lab_folder") or "").strip()
    if not raw:
        return derived
    name = Path(raw).name
    if not name or name in (".", ".."):
        return derived
    return root / name


def workspace_slug(workspace):
    return Path(workspace).name


def json_dir(workspace):
    return Path(workspace) / "machine_json"


def logs_dir(workspace):
    return Path(workspace) / "logs"


def screenshots_dir(workspace):
    return Path(workspace) / "screenshots"


def notes_dir(workspace):
    return Path(workspace) / "notes"


def notes_file(workspace):
    return notes_dir(workspace) / "notes.md"


def evidence_file(workspace):
    return notes_dir(workspace) / "evidence.md"


def report_dir(workspace):
    return Path(workspace) / "report"


def report_file(workspace):
    return report_dir(workspace) / "report.md"


def default_report_text(config, suggestions=None):
    """Starter report.md so a new lab already has the write-up structure."""
    machine = (config or {}).get("machine_name") or "Unknown"
    target = (config or {}).get("target_ip") or ""
    port = (config or {}).get("target_port") or "None"
    lines = [
        f"# HTB Challenge: {machine}",
        "",
        "## Executive Summary",
        "",
        "",
        "## Scope",
        "",
        f"This report covers the authorized HTB machine **{machine}** at `{target}`",
        f"(assigned port: `{port}`). Testing was limited to that host and the engagement rules.",
        "",
        "## Methodology",
        "",
        "",
        "## Findings",
        "",
    ]
    if suggestions:
        lines.append("<small>")
        lines.append("")
        lines.append("Suggested from the evidence log — rewrite in your words, then delete this list.")
        lines.append("")
        lines.extend(suggestions)
        lines.append("")
        lines.append("</small>")
        lines.append("")
    else:
        lines.append("")
    lines.extend([
        "## Attack narrative",
        "",
        "",
        "## Remediation",
        "",
        "",
        "## Conclusion",
        "",
        "",
    ])
    return "\n".join(lines) + "\n"


def report_media_dir(workspace):
    return report_dir(workspace) / "media"


def files_given_dir(workspace):
    return Path(workspace) / "files_given"


def metadata_path(workspace):
    return json_dir(workspace) / "metadata.json"


EXPORT_FOLDERS = ("logs", "screenshots", "notes", "report", "files_given")


def last_note_date(text):
    dates = re.findall(r"(?m)^(\d{4}-\d{2}-\d{2})$", text or "")
    return dates[-1] if dates else None


def note_date_prefix(existing_text):
    today = datetime.now().strftime("%Y-%m-%d")
    if last_note_date(existing_text) == today:
        return ""
    return f"{today}\n"


def note_clock():
    return datetime.now().strftime("%H:%M")


def format_workflow_stamp(existing_text, category=None):
    prefix = note_date_prefix(existing_text)
    clock = note_clock()
    cat = str(category or "").strip().upper()
    if cat in ("", "NONE", "SESSION"):
        return f"{prefix}[{clock}]"
    return f"{prefix}[{clock}] [{cat}]"


# ============================================================
# WORKSPACE AND MANIFEST
# ============================================================

def manifest_path(workspace):
    return json_dir(workspace) / "research_manifest.json"


def load_manifest(workspace):
    path = manifest_path(workspace)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def save_manifest(workspace, manifest):
    path = manifest_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(manifest, indent=4),
        encoding="utf-8",
    )


def initialize_manifest(config, workspace):
    path = manifest_path(workspace)
    if path.exists():
        manifest = load_manifest(workspace)
        if manifest is not None:
            manifest.setdefault("tool_runs", [])
            manifest.setdefault("notes", [])
            manifest.setdefault("evidence", [])
            manifest.setdefault("screenshots", [])
            manifest.setdefault("session_logs", [])
            manifest.setdefault("nmap_scans", [])
            manifest.setdefault("command_outputs", [])
            manifest.setdefault("milestones", {
                "initial_recon": False,
                "initial_foothold": False,
                "vulnerability_evidence": False,
                "privilege_escalation": False,
                "user_flag": False,
                "root_admin_flag": False,
            })
            manifest["helper"] = {"name": APP_NAME, "version": APP_VERSION}
            manifest["student_id"] = config["student_id"]
            manifest["machine_name"] = config["machine_name"]
            manifest["target_ip"] = config["target_ip"]
            manifest["assigned_port"] = config.get("target_port")
            save_manifest(workspace, manifest)
        return

    manifest = {
        "schema_version": 2,
        "helper": {"name": APP_NAME, "version": APP_VERSION},
        "study": config.get(
            "research_project",
            "HTB Enterprise AI Generated Pentest Report Study",
        ),
        "student_id": config["student_id"],
        "machine_name": config["machine_name"],
        "target_ip": config["target_ip"],
        "assigned_port": config.get("target_port"),
        "started": human_timestamp(),
        "session_logs": [],
        "nmap_scans": [],
        "command_outputs": [],
        "tool_runs": [],
        "screenshots": [],
        "notes": [],
        "evidence": [],
        "milestones": {
            "initial_recon": False,
            "initial_foothold": False,
            "vulnerability_evidence": False,
            "privilege_escalation": False,
            "user_flag": False,
            "root_admin_flag": False,
        },
    }
    save_manifest(workspace, manifest)


def manifest_add(workspace, category, value):
    manifest = load_manifest(workspace)
    if manifest is None:
        return
    manifest.setdefault(category, [])
    if not isinstance(manifest[category], list):
        return
    manifest[category].append(value)
    save_manifest(workspace, manifest)


def update_milestone(workspace, milestone):
    manifest = load_manifest(workspace)
    if manifest is None:
        return
    milestones = manifest.setdefault("milestones", {})
    if milestone in milestones:
        milestones[milestone] = True
    save_manifest(workspace, manifest)


def setup_workspace(config, workspace=None):
    workspace = Path(workspace) if workspace is not None else workspace_from_config(config)
    for folder in (
        logs_dir(workspace),
        screenshots_dir(workspace),
        notes_dir(workspace),
        report_dir(workspace),
        files_given_dir(workspace),
        json_dir(workspace),
    ):
        folder.mkdir(parents=True, exist_ok=True)

    notes_path = notes_file(workspace)
    machine = config["machine_name"]
    lab_block = (
        f"### Lab instructions\n\n"
        "Paste the HTB lab instructions here (scope, rules, and any details the box gives you).\n\n"
        "### Workflow\n"
    )
    old_lab = f"## Lab instructions — {machine}\n\nPaste the HTB lab instructions here (scope, rules, and any details the box gives you).\n"
    old_timeline = (
        "## Research Timeline\n\n"
        "Automatic entries summarize observed tool output. The raw files in "
        "`logs/` remain the authoritative evidence. Student-entered purposes "
        "and manual notes preserve the student's own reasoning.\n"
    )
    if not notes_path.exists():
        notes_path.write_text(
            f"# {machine}\n\n"
            f"Student ID: {config['student_id']}\n"
            f"Machine: {machine}\n"
            f"Target: {config['target_ip']}\n"
            f"Assigned Port: {config.get('target_port') or 'None'}\n"
            f"Started: {human_timestamp()}\n\n"
            + lab_block,
            encoding="utf-8",
        )
    else:
        current = notes_path.read_text(encoding="utf-8")
        updated = current
        if updated.startswith("# HTB Enterprise Research Notes"):
            updated = f"# {machine}" + updated[len("# HTB Enterprise Research Notes"):]
        if old_timeline in updated:
            updated = updated.replace(old_timeline, lab_block, 1)
        if old_lab in updated:
            updated = updated.replace(old_lab, lab_block, 1)
        if "### Workflow" not in updated and "### Lab instructions" in updated:
            updated = updated.replace(
                "Paste the HTB lab instructions here (scope, rules, and any details the box gives you).\n",
                "Paste the HTB lab instructions here (scope, rules, and any details the box gives you).\n\n### Workflow\n",
                1,
            )
        def _compact_session(match):
            stamp = match.group(1) or ""
            parts = stamp.split()
            clock = parts[-1][:5] if parts else note_clock()
            return f"[{clock}] Starting a terminal-logged shell for this engagement.\n"

        compact_session = re.compile(
            r"### \[([^\]]+)\] \[SESSION\]\n"
            r"- Summary: Starting a terminal-logged shell for this engagement\.\n"
            r"(?:- Origin: [^\n]+\n)?"
            r"(?:- Tool: [^\n]+\n)?"
            r"(?:- Why / goal: [^\n]+\n(?:  [^\n]+\n)*)?"
            r"(?:- Raw evidence:\n(?:  - [^\n]+\n)*)?",
        )
        updated = compact_session.sub(_compact_session, updated)
        if updated != current:
            notes_path.write_text(updated, encoding="utf-8")

    ev_path = evidence_file(workspace)
    if not ev_path.exists():
        ev_path.write_text(
            "# HTB Evidence Log\n\n"
            "Each evidence item points to an original artifact in the workspace.\n",
            encoding="utf-8",
        )
    report_path = report_file(workspace)
    if not report_path.exists():
        report_path.write_text(default_report_text(config), encoding="utf-8")

    metadata_file = metadata_path(workspace)
    if not metadata_file.exists():
        metadata_file.write_text(
            json.dumps({
                "helper_version": APP_VERSION,
                "student_id": config["student_id"],
                "machine_name": config["machine_name"],
                "target_ip": config["target_ip"],
                "assigned_port": config.get("target_port"),
                "workspace_created": human_timestamp(),
                "research_project": config.get(
                    "research_project",
                    "HTB Enterprise AI Generated Pentest Report Study",
                ),
            }, indent=4),
            encoding="utf-8",
        )

    initialize_manifest(config, workspace)
    return workspace


# ============================================================
# SOPHISTICATED NOTE GENERATION
# ============================================================

def append_timeline_note(
    workspace,
    category,
    summary,
    *,
    origin="automatic",
    tool=None,
    command=None,
    purpose=None,
    outcome=None,
    findings=None,
    evidence=None,
    exit_code=None,
    metadata=None,
    compact=False,
    include_command=True,
    include_findings=True,
):
    """Append a factual timestamped note and mirror it into the manifest."""
    note_time = human_timestamp()
    category = sanitize_note_text(category, 50).upper()
    if origin == "student":
        summary = sanitize_note_multiline(summary, 4000)
        purpose = sanitize_note_multiline(purpose, 4000) if purpose else None
        outcome = sanitize_note_multiline(outcome, 4000) if outcome else None
    else:
        summary = sanitize_note_text(summary, 700)
        purpose = sanitize_note_text(purpose, 700) if purpose else None
        outcome = sanitize_note_text(outcome, 700) if outcome else None
    tool = None if compact else (sanitize_note_text(tool, 100) if tool else None)
    if compact or not include_command:
        command = None
    else:
        command = sanitize_note_text(command, 1500) if command else None
    if compact:
        purpose = None
        outcome = None
        origin_write = False
        evidence = None
        findings = None
        exit_code = None
        include_findings = False
    else:
        origin_write = True

    clean_findings = []
    if include_findings:
        for finding in findings or []:
            cleaned = sanitize_note_text(finding, 700)
            if cleaned:
                clean_findings.append(cleaned)
        clean_findings = unique_preserve(clean_findings)[:MAX_NOTE_FINDINGS]
    else:
        findings = None

    clean_evidence = []
    for item in evidence or []:
        cleaned = sanitize_note_text(item, 500)
        if cleaned:
            clean_evidence.append(cleaned)
    clean_evidence = unique_preserve(clean_evidence)

    path = notes_file(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    stamp = format_workflow_stamp(existing, None if compact else category)
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n")
        if compact or not tool:
            handle.write(f"{stamp} {summary}\n")
        else:
            handle.write(f"{stamp} {tool}\n")
            if command:
                handle.write(f"- Command: `{command}`\n")
            if purpose:
                handle.write(f"- Why: {purpose}\n")
            if include_findings:
                if summary:
                    handle.write(f"- Summary: {summary}\n")
                if clean_findings:
                    handle.write("- Findings:\n")
                    for finding in clean_findings:
                        handle.write(f"  - {finding}\n")
            if clean_evidence:
                handle.write(f"- Output: {', '.join(clean_evidence)}\n")
            if exit_code is not None:
                handle.write(f"- Exit: {exit_code}\n")

    manifest_add(workspace, "notes", {
        "time": note_time,
        "category": category,
        "origin": origin,
        "summary": summary,
        "tool": tool,
        "purpose": purpose,
        "command": command,
        "exit_code": exit_code,
        "outcome": outcome,
        "findings": clean_findings,
        "evidence": clean_evidence,
        "metadata": metadata or {},
    })


def add_note(workspace):
    """Add a student-authored note for reasoning, changes of approach, or findings."""
    categories = {
        "1": "RECON",
        "2": "ENUMERATION",
        "3": "FINDING",
        "4": "DEAD END",
        "5": "FOOTHOLD",
        "6": "PRIVESC",
        "7": "FLAG",
        "8": "OTHER",
    }

    print("\n" + "=" * 60)
    print("ADD STUDENT RESEARCH NOTE")
    print("=" * 60)
    print("\nNote type:")
    for key, value in categories.items():
        print(f"{key}. {value}")

    category = categories.get(input("\nSelect type: ").strip())
    if not category:
        print("[-] Invalid note type.")
        return

    # Offer the screenshot immediately after the student identifies the
    # milestone, before multiline note entry can push the relevant terminal
    # evidence farther off-screen. The category choice is the student's
    # explicit classification; the helper does not infer the milestone.
    if category == "RECON":
        offer_milestone_screenshot(
            workspace,
            "initial_recon",
            "Initial reconnaissance",
            "student_recon_note",
        )
    elif category == "FINDING":
        offer_milestone_screenshot(
            workspace,
            "vulnerability_evidence",
            "Vulnerability evidence",
            "student_finding",
        )
    elif category == "FOOTHOLD":
        offer_milestone_screenshot(
            workspace,
            "initial_foothold",
            "Initial foothold",
            "initial_foothold",
        )
    elif category == "PRIVESC":
        offer_milestone_screenshot(
            workspace,
            "privilege_escalation",
            "Privilege escalation",
            "privilege_escalation",
        )
    elif category == "FLAG":
        offer_flag_screenshot(workspace)

    print("\nPaste note text with Ctrl+Shift+V or right-click in most Linux terminals.")
    print("Each field accepts multiple lines; type .done on its own line to finish that field.")

    tried = read_multiline("What did you try / observe?")
    if tried is None:
        return

    why = read_multiline("Why did you try it / why is it important?")
    if why is None:
        return

    result = read_multiline("What happened / what will you do next?")
    if result is None:
        return

    append_timeline_note(
        workspace,
        category,
        tried,
        origin="student",
        purpose=why,
        outcome=result,
    )
    print("[+] Student research note saved.")


# ============================================================
# TOOL IDENTIFICATION AND OUTPUT PARSERS
# ============================================================

TOOL_ALIASES = {
    "nmap": "nmap",
    "gobuster": "gobuster",
    "ffuf": "ffuf",
    "feroxbuster": "feroxbuster",
    "dirsearch": "dirsearch",
    "dirsearch.py": "dirsearch",
    "nikto": "nikto",
    "whatweb": "whatweb",
    "httpx": "httpx",
    "nuclei": "nuclei",
    "dig": "dig",
    "nslookup": "nslookup",
    "enum4linux": "enum4linux",
    "enum4linux-ng": "enum4linux",
    "enum4linux-ng.py": "enum4linux",
    "smbclient": "smbclient",
    "rpcclient": "rpcclient",
    "ldapsearch": "ldapsearch",
    "netexec": "netexec",
    "nxc": "netexec",
    "crackmapexec": "netexec",
    "cme": "netexec",
    "curl": "curl",
    "wget": "wget",
    "sqlmap": "sqlmap",
    "sqlmap.py": "sqlmap",
    "dalfox": "dalfox",
    "ping": "ping",
    "tracert": "traceroute",
    "traceroute": "traceroute",
    "tracepath": "traceroute",
}

TOOL_CATEGORIES = {
    "nmap": "RECON",
    "gobuster": "ENUMERATION",
    "ffuf": "ENUMERATION",
    "feroxbuster": "ENUMERATION",
    "dirsearch": "ENUMERATION",
    "nikto": "ENUMERATION",
    "whatweb": "ENUMERATION",
    "httpx": "ENUMERATION",
    "nuclei": "ENUMERATION",
    "dig": "RECON",
    "nslookup": "RECON",
    "enum4linux": "ENUMERATION",
    "smbclient": "ENUMERATION",
    "rpcclient": "ENUMERATION",
    "ldapsearch": "ENUMERATION",
    "netexec": "ENUMERATION",
    "curl": "ENUMERATION",
    "wget": "ENUMERATION",
    "sqlmap": "ENUMERATION",
    "dalfox": "ENUMERATION",
    "ping": "RECON",
    "traceroute": "RECON",
    "generic": "OTHER",
}


def classify_tool_category(tool, command=None):
    """Classify a tool run by research phase rather than by tool name alone."""
    command = command or []
    lowered = [str(part).lower() for part in command]

    if tool == "nmap":
        # Service/version, NSE, or targeted-port scans are enumeration.
        # A basic discovery/port scan remains reconnaissance.
        if any(arg in ("-sv", "-sc") for arg in lowered):
            return "ENUMERATION"
        if any(arg.startswith("--script") for arg in lowered):
            return "ENUMERATION"
        if "-p" in lowered:
            return "ENUMERATION"
        return "RECON"

    return TOOL_CATEGORIES.get(tool, "OTHER")


def _tool_basename(name):
    name = Path(str(name or "")).name.lower()
    if name.endswith((".exe", ".bat", ".cmd", ".bin")):
        name = Path(name).stem.lower()
    return name


def identify_tool(command):
    if not command:
        return "generic"
    if isinstance(command, str):
        try:
            command = shlex.split(command, posix=(os.name != "nt"))
        except ValueError:
            command = str(command).split()
        if not command:
            return "generic"
    name = _tool_basename(command[0])
    if name in ("python", "python3", "python2") and len(command) > 1:
        name = _tool_basename(command[1])
    return TOOL_ALIASES.get(name, "generic")


def parse_nmap_output(output):
    findings = {
        "host_status": None,
        "open_ports": [],
        "closed_ports": None,
        "filtered_ports": None,
        "other_states": [],
    }

    for line in output.splitlines():
        stripped = line.strip()
        if "Host is up" in stripped:
            findings["host_status"] = stripped

        match = re.match(
            r"^(\d+)/(tcp|udp)\s+(open|open\|filtered|filtered|closed)\s+(.+)$",
            stripped,
            re.IGNORECASE,
        )
        if match:
            item = {
                "port": int(match.group(1)),
                "protocol": match.group(2).lower(),
                "state": match.group(3).lower(),
                "service": match.group(4).strip(),
            }
            if item["state"] == "open":
                findings["open_ports"].append(item)
            else:
                findings["other_states"].append(item)

        filtered_match = re.search(r"(\d+)\s+filtered\s+(?:tcp|udp)\s+ports?", stripped, re.I)
        if not filtered_match:
            filtered_match = re.search(r"(\d+)\s+filtered\b", stripped, re.I)
        if filtered_match:
            findings["filtered_ports"] = int(filtered_match.group(1))

        closed_match = re.search(r"(\d+)\s+closed\s+(?:tcp|udp)\s+ports?", stripped, re.I)
        if not closed_match:
            closed_match = re.search(r"(\d+)\s+closed\b", stripped, re.I)
        if closed_match:
            findings["closed_ports"] = int(closed_match.group(1))

    return findings


def nmap_findings_for_notes(parsed):
    notes = []
    if parsed.get("host_status"):
        notes.append(parsed["host_status"])
    if parsed.get("closed_ports") is not None:
        notes.append(f"Closed ports reported: {parsed['closed_ports']}")
    if parsed.get("filtered_ports") is not None:
        notes.append(f"Filtered ports reported: {parsed['filtered_ports']}")
    for item in parsed.get("open_ports", []):
        notes.append(
            f"Open service: {item['port']}/{item['protocol']} "
            f"{sanitize_note_text(item['service'], 350)}"
        )
    for item in parsed.get("other_states", [])[:10]:
        notes.append(
            f"Port state: {item['port']}/{item['protocol']} "
            f"{item['state']} {sanitize_note_text(item['service'], 250)}"
        )
    return notes


def parse_ping_output(output):
    """Brief ICMP stats from Windows ping.exe or Unix ping. Never dumps every reply."""
    findings = []
    text = strip_ansi(output or "")
    win = re.search(
        r"Ping statistics for ([^\r\n:]+):\s*"
        r"Packets: Sent = (\d+), Received = (\d+), Lost = (\d+) \((\d+)% loss\)",
        text,
        re.I,
    )
    if win:
        host, sent, recv, lost, loss = win.groups()
        findings.append(
            f"{host.strip()} ICMP: {recv}/{sent} received, {lost} lost ({loss}% loss)"
        )
        rtt = re.search(
            r"Minimum = (\d+)ms, Maximum = (\d+)ms, Average = (\d+)ms",
            text,
            re.I,
        )
        if rtt:
            findings.append(
                f"Round trip: min {rtt.group(1)}ms, max {rtt.group(2)}ms, avg {rtt.group(3)}ms"
            )
        if int(recv) == 0:
            findings.append("No ICMP replies (host down, filtered, or ICMP blocked).")
        return unique_preserve(findings)[:MAX_NOTE_FINDINGS]

    unix = re.search(
        r"(\d+) packets transmitted, (\d+) (?:packets )?received,.*?(\d+(?:\.\d+)?)% packet loss",
        text,
        re.I,
    )
    if unix:
        sent, recv, loss = unix.groups()
        dest_match = re.search(r"^PING\s+(\S+)", text, re.M)
        label = dest_match.group(1) if dest_match else "target"
        findings.append(f"{label} ICMP: {recv}/{sent} received, {loss}% loss")
        rtt = re.search(
            r"min/avg/max[^=]*=\s*([\d.]+)/([\d.]+)/([\d.]+)",
            text,
            re.I,
        )
        if rtt:
            findings.append(
                f"Round trip: min {rtt.group(1)}ms, avg {rtt.group(2)}ms, max {rtt.group(3)}ms"
            )
        if float(loss) >= 100 or int(recv) == 0:
            findings.append("No ICMP replies (host down, filtered, or ICMP blocked).")
        return unique_preserve(findings)[:MAX_NOTE_FINDINGS]

    if re.search(r"(?i)could not find host|unknown host|Name or service not known", text):
        findings.append("Ping could not resolve the host name.")
    elif re.search(r"(?i)Destination host unreachable", text):
        findings.append("Destination host unreachable.")
    elif re.search(r"(?i)Request timed out|100%\s*(packet )?loss", text):
        findings.append("No ICMP replies.")
    return unique_preserve(findings)[:MAX_NOTE_FINDINGS]


def capture_output_complete(tool, output):
    """True when a capture file looks finished enough to parse."""
    text = strip_ansi(output or "")
    if not text.strip():
        return False
    if tool == "ping":
        return bool(re.search(
            r"(?i)Ping statistics for|packets transmitted|could not find host|unknown host",
            text,
        ))
    if tool == "nmap":
        return bool(re.search(r"(?i)#?\s*Nmap done at", text))
    if tool == "traceroute":
        return bool(re.search(r"(?i)Trace complete|traceroute to ", text))
    return False


def patch_tool_note_findings(notes_text, output_rel, summary, findings):
    """Fill parser findings into the last send-to-terminal stamp for this capture file."""
    text = notes_text or ""
    marker = str(output_rel or "").strip()
    if not marker:
        return text, False
    idx = text.rfind(marker)
    if idx < 0:
        slash = marker.replace("\\", "/")
        idx = text.rfind(slash)
        if idx < 0:
            return text, False
    stamp_starts = [m.start() for m in re.finditer(r"(?m)^\[\d{2}:\d{2}\]", text)]
    block_start = 0
    for start in stamp_starts:
        if start <= idx:
            block_start = start
        else:
            break
    next_starts = [s for s in stamp_starts if s > block_start]
    block_end = next_starts[0] if next_starts else len(text)
    block = text[block_start:block_end]
    clean_summary = sanitize_note_text(summary, 700) if summary else ""
    clean_findings = []
    for finding in findings or []:
        cleaned = sanitize_note_text(finding, 700)
        if cleaned:
            clean_findings.append(cleaned)
    clean_findings = unique_preserve(clean_findings)[:MAX_NOTE_FINDINGS]
    findings_md = ""
    if clean_findings:
        findings_md = "- Findings:\n" + "".join(f"  - {item}\n" for item in clean_findings)

    new_block = block
    if clean_summary:
        if re.search(r"(?m)^- Summary: ", new_block):
            new_block = re.sub(
                r"(?m)^- Summary: .*$",
                f"- Summary: {clean_summary}",
                new_block,
                count=1,
            )
        else:
            new_block = re.sub(
                r"(?m)^(- Why: .*\n)",
                r"\1" + f"- Summary: {clean_summary}\n",
                new_block,
                count=1,
            ) if re.search(r"(?m)^- Why: ", new_block) else (
                new_block.rstrip() + f"\n- Summary: {clean_summary}\n"
            )

    if re.search(r"(?m)^- Findings:", new_block):
        new_block = re.sub(
            r"(?ms)^- Findings:\n(?:  - .*\n)*",
            findings_md,
            new_block,
            count=1,
        )
    elif findings_md:
        if re.search(r"(?m)^- Output: ", new_block):
            new_block = re.sub(
                r"(?m)^- Output: ",
                findings_md + "- Output: ",
                new_block,
                count=1,
            )
        else:
            new_block = new_block.rstrip() + "\n" + findings_md

    if new_block == block:
        return text, False
    return text[:block_start] + new_block + text[block_end:], True


def parse_gobuster_output(output):
    results = []
    for line in output.splitlines():
        stripped = line.strip()
        match = re.match(
            r"^(\S+)\s+\(Status:\s*(\d{3})\)(?:\s+\[Size:\s*([^\]]+)\])?(?:\s+\[-->\s*([^\]]+)\])?",
            stripped,
            re.I,
        )
        if match:
            path, status, size, redirect = match.groups()
            item = f"HTTP {status}: {path}"
            if size:
                item += f" (size {size.strip()})"
            if redirect:
                item += f" -> {redirect.strip()}"
            results.append(item)
            continue

        match = re.match(r"^Found:\s+(\S+)(?:\s+\(Status:\s*(\d{3})\))?", stripped, re.I)
        if match:
            url, status = match.groups()
            results.append(f"Discovered: {url}" + (f" (HTTP {status})" if status else ""))

    return unique_preserve(results)


def parse_ffuf_output(output):
    results = []
    pattern = re.compile(
        r"^(.*?)\s+\[Status:\s*(\d{3}),\s*Size:\s*(\d+),\s*Words:\s*(\d+),\s*Lines:\s*(\d+)",
        re.I,
    )
    for line in output.splitlines():
        match = pattern.match(line.strip())
        if match:
            value, status, size, words, lines = match.groups()
            results.append(
                f"HTTP {status}: {value.strip()} (size {size}, words {words}, lines {lines})"
            )
    return unique_preserve(results)


def parse_feroxbuster_output(output):
    results = []
    pattern = re.compile(
        r"^(\d{3})\s+\S+\s+\S+\s+\S+\s+\S+\s+(https?://\S+)",
        re.I,
    )
    for line in output.splitlines():
        match = pattern.match(line.strip())
        if match:
            status, url = match.groups()
            results.append(f"HTTP {status}: {url}")
    return unique_preserve(results)


def parse_dirsearch_output(output):
    results = []
    patterns = [
        re.compile(r"^\[\d{2}:\d{2}:\d{2}\]\s+(\d{3})\s+\S+\s+(https?://\S+)", re.I),
        re.compile(r"^(\d{3})\s+\S+\s+(https?://\S+)", re.I),
    ]
    for line in output.splitlines():
        stripped = line.strip()
        for pattern in patterns:
            match = pattern.match(stripped)
            if match:
                status, url = match.groups()
                results.append(f"HTTP {status}: {url}")
                break
    return unique_preserve(results)


def parse_nikto_output(output):
    results = []
    for line in output.splitlines():
        stripped = line.strip()
        if stripped.startswith("+"):
            text = sanitize_note_text(stripped.lstrip("+ "), 500)
            if text and not re.match(r"^-+$", text):
                results.append(text)
    return unique_preserve(results)


def parse_whatweb_output(output):
    results = []
    for line in output.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith(("WhatWeb report", "ERROR")):
            results.append(sanitize_note_text(stripped, 700))
    return unique_preserve(results[:10])


def parse_httpx_output(output):
    results = []
    for line in output.splitlines():
        stripped = line.strip()
        if re.search(r"https?://", stripped, re.I):
            results.append(sanitize_note_text(stripped, 650))
    return unique_preserve(results)


def parse_nuclei_output(output):
    results = []
    for line in output.splitlines():
        stripped = line.strip()
        if re.match(r"^\[[^\]]+\]\s+\[[^\]]+\]\s+\[(info|low|medium|high|critical|unknown)\]", stripped, re.I):
            results.append(sanitize_note_text(stripped, 700))
    return unique_preserve(results)


def parse_dns_output(output):
    addresses = []
    cnames = []
    for line in output.splitlines():
        stripped = line.strip()
        for address in re.findall(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", stripped):
            try:
                ipaddress.ip_address(address)
                addresses.append(address)
            except ValueError:
                pass
        cname = re.search(r"\bCNAME\s+([^\s]+)", stripped, re.I)
        if cname:
            cnames.append(cname.group(1).rstrip("."))
    notes = [f"Resolved address: {item}" for item in unique_preserve(addresses)[:20]]
    notes += [f"CNAME: {item}" for item in unique_preserve(cnames)[:20]]
    return notes


def parse_smb_output(output):
    results = []
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if re.search(r"(?i)\b(sharename|workgroup|domain|server|disk|ipc\$|smb\d|signing)\b", stripped):
            results.append(sanitize_note_text(stripped, 600))
        elif re.match(r"^\[\+\]", stripped):
            results.append(sanitize_note_text(stripped, 600))
    return unique_preserve(results)


def parse_ldap_output(output):
    dns = []
    object_classes = set()
    for line in output.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("dn:"):
            dns.append(sanitize_note_text(stripped, 600))
        elif stripped.lower().startswith("objectclass:"):
            object_classes.add(sanitize_note_text(stripped.split(":", 1)[1], 200))
    results = [f"LDAP entries returned: {len(dns)}"] if dns else []
    results.extend(dns[:10])
    if object_classes:
        results.append("Object classes observed: " + ", ".join(sorted(object_classes)[:15]))
    return results


def parse_http_headers_output(output):
    results = []
    for line in output.splitlines():
        stripped = line.strip()
        if re.match(r"^HTTP/\S+\s+\d{3}", stripped, re.I):
            results.append(stripped)
        elif re.match(r"^(server|location|content-type|www-authenticate):", stripped, re.I):
            results.append(sanitize_note_text(stripped, 500))
    return unique_preserve(results)


def parse_sqlmap_output(output):
    results = []
    for line in output.splitlines():
        stripped = line.strip()
        if re.search(r"(?i)(injectable|injection point|back-end DBMS|available databases|fetched data|Parameter:)", stripped):
            results.append(sanitize_note_text(stripped.lstrip("[*] ").lstrip("[+] "), 600))
        elif re.match(r"^\[?['\"]?\w", stripped) and "database" in output.lower() and len(stripped) < 80:
            if re.match(r"^[*+\-]\s+\S+", stripped) or stripped.startswith("[*]"):
                results.append(sanitize_note_text(stripped, 400))
    return unique_preserve(results)[:MAX_NOTE_FINDINGS]


def parse_dalfox_output(output):
    results = []
    for line in output.splitlines():
        stripped = line.strip()
        if re.search(r"(?i)(\[V\]|POC|reflected|verified|vulnerable|payload)", stripped):
            results.append(sanitize_note_text(stripped, 600))
    return unique_preserve(results)[:MAX_NOTE_FINDINGS]


def analyze_tool_output(tool, output, returncode):
    """Generate a conservative summary. Never claim exploitation success."""
    output = strip_ansi(output or "")
    nonempty_lines = [line for line in output.splitlines() if line.strip()]
    error_lines = [
        line for line in nonempty_lines
        if re.search(r"(?i)\b(error|failed|failure|permission denied|timed out|refused)\b", line)
    ]

    if tool == "nmap":
        parsed = parse_nmap_output(output)
        findings = nmap_findings_for_notes(parsed)
        if parsed["open_ports"]:
            summary = f"Nmap reported {len(parsed['open_ports'])} open service(s)."
        elif parsed["host_status"]:
            summary = "Nmap completed and reported the host status, but no open services were parsed."
        else:
            summary = "Nmap completed; no structured host/service findings were parsed from the captured output."
        return summary, findings, {"parsed": parsed}

    if tool == "ping":
        findings = parse_ping_output(output)
        if findings:
            summary = findings[0]
        elif returncode == 0:
            summary = "ping completed; no structured ICMP stats were parsed from the captured output."
        else:
            summary = f"ping exited with code {returncode}; the failed/partial output was preserved."
        return summary, findings, {"parser": "ping"}

    parser_map = {
        "gobuster": parse_gobuster_output,
        "ffuf": parse_ffuf_output,
        "feroxbuster": parse_feroxbuster_output,
        "dirsearch": parse_dirsearch_output,
        "nikto": parse_nikto_output,
        "whatweb": parse_whatweb_output,
        "httpx": parse_httpx_output,
        "nuclei": parse_nuclei_output,
        "dig": parse_dns_output,
        "nslookup": parse_dns_output,
        "enum4linux": parse_smb_output,
        "smbclient": parse_smb_output,
        "rpcclient": parse_smb_output,
        "netexec": parse_smb_output,
        "ldapsearch": parse_ldap_output,
        "curl": parse_http_headers_output,
        "wget": parse_http_headers_output,
        "sqlmap": parse_sqlmap_output,
        "dalfox": parse_dalfox_output,
    }

    parser = parser_map.get(tool)
    findings = parser(output) if parser else []

    if findings:
        summary = f"{tool} produced {len(findings)} structured finding(s) from the captured output."
    elif returncode == 0:
        summary = f"{tool} completed; no structured findings were parsed. Review the raw output for context."
    else:
        summary = f"{tool} exited with code {returncode}; the failed/partial output was preserved."

    metadata = {
        "captured_nonempty_lines": len(nonempty_lines),
        "possible_error_lines": len(error_lines),
        "parser": tool if parser else "generic",
    }
    if error_lines and not findings:
        findings.append(f"Possible error/failure messages observed: {len(error_lines)}")

    return summary, findings, metadata


def classify_outcome(returncode, interrupted=False):
    if interrupted:
        return "The command was interrupted. Partial output, if any, was preserved."
    if returncode == 0:
        return "The command completed with exit code 0."
    return f"The command completed with non-zero exit code {returncode}. The output was retained as research data."


# ============================================================
# COMMAND RECORDING AND STREAMING CAPTURE
# ============================================================

def save_command_record(workspace, command, description, purpose=None, findings=None, output_file=None):
    logs = logs_dir(workspace)
    logs.mkdir(parents=True, exist_ok=True)
    command_log = logs / "commands.log"
    command_text = shlex.join(command) if isinstance(command, list) else str(command)
    with command_log.open("a", encoding="utf-8") as handle:
        handle.write(f"\n[{human_timestamp()}]\n")
        handle.write(f"Description: {description}\n")
        if purpose:
            handle.write(f"Purpose: {purpose}\n")
        handle.write(f"Command: {command_text}\n")
        if output_file:
            handle.write(f"Raw output: {output_file}\n")
        if findings:
            handle.write("Observed findings:\n")
            for finding in findings:
                cleaned = str(finding).strip()
                if cleaned:
                    handle.write(f"  - {cleaned}\n")


def run_streaming_command(command, raw_output_file):
    """Run a direct command, tee merged stdout/stderr to terminal and a raw file."""
    captured = []
    captured_chars = 0
    truncated_for_analysis = False
    interrupted = False

    with raw_output_file.open("w", encoding="utf-8", errors="replace") as handle:
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
                print(line, end="")
                handle.write(line)
                handle.flush()
                if captured_chars < MAX_ANALYSIS_CHARS:
                    remaining = MAX_ANALYSIS_CHARS - captured_chars
                    captured.append(line[:remaining])
                    captured_chars += min(len(line), remaining)
                    if len(line) > remaining:
                        truncated_for_analysis = True
                else:
                    truncated_for_analysis = True
            returncode = process.wait()

        except KeyboardInterrupt:
            interrupted = True
            print("\n[!] Command interrupted; preserving partial output.")
            process.terminate()
            try:
                returncode = process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                returncode = process.wait()

    return {
        "returncode": returncode,
        "output_for_analysis": "".join(captured),
        "analysis_truncated": truncated_for_analysis,
        "interrupted": interrupted,
    }


def record_tool_run(
    workspace,
    command,
    description,
    purpose,
    *,
    tool=None,
    output_file=None,
):
    """Run an enumeration/recon command, save raw output, and generate notes."""
    if not command:
        print("[-] Command cannot be empty.")
        return None

    tool = tool or identify_tool(command)
    tool_label = tool if tool != "generic" else Path(command[0]).name
    category = classify_tool_category(tool, command)
    logs = logs_dir(workspace)
    logs.mkdir(parents=True, exist_ok=True)

    if output_file is None:
        output_file = logs / f"{safe_filename(tool_label) or 'command'}_{timestamp_seconds()}.txt"

    save_command_record(workspace, command, description, purpose)

    # Write the student's intended action before execution so the timeline
    # still contains the attempt if the command hangs, fails, or is interrupted.
    append_timeline_note(
        workspace,
        category,
        f"Starting {description}.",
        origin="automatic",
        tool=tool_label,
        command=shlex.join(command),
        purpose=purpose,
        outcome="Command is about to run; a separate result entry will be written when it finishes.",
        metadata={"event": "attempt_started"},
    )

    print("\n" + "=" * 60)
    print(f"RUN {tool_label.upper()} AND CAPTURE RAW OUTPUT")
    print("=" * 60)
    print(f"\nPurpose: {purpose}")
    print(f"Command: {shlex.join(command)}")
    print(f"Raw output: {output_file}")
    print("\n[*] Running...\n")

    try:
        result = run_streaming_command(command, output_file)
    except FileNotFoundError:
        append_timeline_note(
            workspace,
            "DEAD END",
            f"Could not start {tool_label}; the command was not found.",
            tool=tool_label,
            command=shlex.join(command),
            purpose=purpose,
            outcome="The executable was not found in PATH.",
            evidence=[relative_path(workspace, output_file)] if output_file.exists() else [],
        )
        print(f"[-] Command not found: {command[0]}")
        return None
    except PermissionError:
        append_timeline_note(
            workspace,
            "DEAD END",
            f"Could not start {tool_label} because permission was denied.",
            tool=tool_label,
            command=shlex.join(command),
            purpose=purpose,
            outcome="Permission denied before the command could run normally.",
        )
        print("[-] Permission denied.")
        return None
    except OSError as exc:
        append_timeline_note(
            workspace,
            "DEAD END",
            f"Could not execute {tool_label}.",
            tool=tool_label,
            command=shlex.join(command),
            purpose=purpose,
            outcome=f"Operating-system error: {exc}",
        )
        print(f"[-] Could not execute command: {exc}")
        return None

    returncode = result["returncode"]
    output = result["output_for_analysis"]
    summary, findings, parser_metadata = analyze_tool_output(tool, output, returncode)
    if result["analysis_truncated"]:
        findings.append(
            "Automatic parsing used only the first part of the output because the capture was large; the raw file is complete."
        )

    evidence_path = relative_path(workspace, output_file)
    outcome = classify_outcome(returncode, result["interrupted"])
    if result["interrupted"]:
        category_for_note = "DEAD END"
    else:
        category_for_note = category

    append_timeline_note(
        workspace,
        category_for_note,
        summary,
        tool=tool_label,
        command=shlex.join(command),
        purpose=purpose,
        exit_code=returncode,
        outcome=outcome,
        findings=findings,
        evidence=[evidence_path],
        metadata={**parser_metadata, "event": "attempt_result"},
    )

    artifact = file_metadata(workspace, output_file)
    run_record = {
        "time": human_timestamp(),
        "tool": tool,
        "tool_label": tool_label,
        "description": description,
        "purpose": purpose,
        "command": shlex.join(command),
        "exit_code": returncode,
        "interrupted": result["interrupted"],
        "analysis_truncated": result["analysis_truncated"],
        "summary": summary,
        "findings": findings[:MAX_NOTE_FINDINGS],
        "output": artifact,
    }
    manifest_add(workspace, "tool_runs", run_record)
    manifest_add(workspace, "command_outputs", run_record)

    print(f"\n[+] {tool_label} finished with exit code {returncode}.")
    print(f"[+] Raw output saved to: {output_file}")
    print("[+] A factual research-timeline note was added to notes.md.")
    return run_record


# ============================================================
# SESSION LOGGING
# ============================================================

def get_next_session_log(workspace):
    logs = logs_dir(workspace)
    logs.mkdir(parents=True, exist_ok=True)
    first = logs / "session.log"
    if not first.exists():
        return first
    number = 2
    while True:
        candidate = logs / f"session{number}.log"
        if not candidate.exists():
            return candidate
        number += 1


def verify_session_log(log_file):
    if not log_file.exists():
        return False
    try:
        content = log_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return bool(content.strip())


def start_session_logging(config, workspace, config_path):
    """Run a child copy of this helper inside a `script` session.

    This allows menu-driven Nmap/Gobuster/other commands to remain inside the
    full terminal transcript instead of launching a separate shell that hides
    the helper menu.
    """
    if not command_exists("script"):
        print("[-] 'script' command was not found.")
        return

    log_file = get_next_session_log(workspace)
    helper_path = Path(__file__).resolve()
    config_abs = Path(config_path).expanduser().resolve()

    child_command = [
        sys.executable,
        str(helper_path),
        "--config",
        str(config_abs),
        "--inside-session",
        "--session-log",
        str(log_file.resolve()),
    ]

    append_timeline_note(
        workspace,
        "SESSION",
        "Starting a terminal-logged helper session.",
        tool="script",
        command=shlex.join(["script", "-f", "-c", shlex.join(child_command), str(log_file)]),
        purpose="Capture the full terminal interaction for the authorized HTB engagement.",
        evidence=[relative_path(workspace, log_file)],
    )

    print("\n" + "=" * 60)
    print("START LOGGED HTB HELPER SESSION")
    print("=" * 60)
    print(f"\nSession log: {log_file}")
    print("[*] The helper will reopen inside the logged terminal session.")
    print("[*] Exit the child helper when the engagement/session is finished.\n")

    script_command = [
        "script",
        "-q",
        "-f",
        "-c",
        shlex.join(child_command),
        str(log_file),
    ]

    try:
        result = subprocess.run(script_command, check=False)
    except KeyboardInterrupt:
        print("\n[!] Session wrapper interrupted.")
        result = None

    if verify_session_log(log_file):
        metadata = file_metadata(workspace, log_file)
        manifest_add(workspace, "session_logs", {
            "time": human_timestamp(),
            "file": metadata,
            "wrapper_exit_code": result.returncode if result is not None else None,
        })
        append_timeline_note(
            workspace,
            "SESSION",
            "Terminal logging session ended and the session log contains captured data.",
            tool="script",
            outcome="The session log was verified as non-empty after the logged helper exited.",
            evidence=[relative_path(workspace, log_file)],
        )
        print("\n[+] Session log contains captured data.")
    else:
        append_timeline_note(
            workspace,
            "DEAD END",
            "The terminal logging session ended, but the session log appears empty.",
            tool="script",
            outcome="Session logging could not be verified from the resulting file.",
            evidence=[relative_path(workspace, log_file)],
        )
        print("\n[-] WARNING: Session log appears empty.")


def announce_inside_session(workspace, session_log):
    print("\n[+] SESSION LOGGING ACTIVE")
    if session_log:
        print(f"[+] Session file: {session_log}")

    if command_exists("whoami"):
        try:
            result = subprocess.run(
                ["whoami"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                errors="replace",
                check=False,
            )
            output = (result.stdout or "").strip()
            print(f"[+] whoami verification: {output}")
            append_timeline_note(
                workspace,
                "SESSION",
                "Ran whoami as a session-logging verification command.",
                tool="whoami",
                command="whoami",
                exit_code=result.returncode,
                outcome="The verification command was displayed in the logged terminal session.",
            )
        except OSError:
            pass


# ============================================================
# NMAP
# ============================================================

def run_nmap(workspace, target, port=None, scan_args=None, description=None):
    if not command_exists("nmap"):
        print("[-] Nmap was not found.")
        append_timeline_note(
            workspace,
            "DEAD END",
            "Nmap could not be started because it was not found in PATH.",
            tool="nmap",
        )
        return

    if port is not None:
        try:
            port = int(port)
        except (TypeError, ValueError):
            print("[-] Invalid port.")
            return
        if not 1 <= port <= 65535:
            print("[-] Invalid port.")
            return

    default_purpose = (
        f"Identify the service and version information exposed on assigned port {port}."
        if port
        else "Identify reachable services and version information on the assigned target."
    )
    purpose = prompt_purpose(default_purpose)

    logs = logs_dir(workspace)
    logs.mkdir(parents=True, exist_ok=True)
    run_timestamp = timestamp_seconds()
    if port:
        output_prefix = logs / f"nmap_port_{port}_{run_timestamp}"
        label = description or f"Nmap assigned-port reconnaissance ({port})"
    else:
        output_prefix = logs / f"nmap_scan_{run_timestamp}"
        label = description or "Nmap reconnaissance"

    command = ["nmap"]
    args = list(scan_args or [])
    if "-Pn" not in args:
        args = ["-Pn"] + args
    command.extend(args)
    if port:
        command.extend(["-p", str(port)])
    command.extend(["-oN", f"{output_prefix}.nmap", target])

    text_output = logs / f"{output_prefix.name}.txt"
    record = record_tool_run(
        workspace,
        command,
        label,
        purpose,
        tool="nmap",
        output_file=text_output,
    )
    if record is None:
        return

    generated_files = []
    for suffix in (".nmap", ".txt"):
        path = Path(f"{output_prefix}{suffix}")
        meta = file_metadata(workspace, path)
        if meta:
            generated_files.append(meta)

    manifest_add(workspace, "nmap_scans", {
        "time": human_timestamp(),
        "target": target,
        "port": port,
        "command": shlex.join(command),
        "exit_code": record["exit_code"],
        "summary": record["summary"],
        "findings": record["findings"],
        "files": generated_files,
    })

    print(f"[+] Nmap text evidence: {output_prefix}.nmap")

    # A completed service/version scan with parsed open services is a
    # reasonable point to *offer* an Initial Recon screenshot. This is
    # intentionally only a prompt: the student decides whether the current
    # screen is meaningful evidence.
    open_service_findings = [
        item for item in record.get("findings", [])
        if str(item).startswith("Open service:")
    ]
    if record.get("exit_code") == 0 and open_service_findings:
        offer_milestone_screenshot(
            workspace,
            "initial_recon",
            "Initial reconnaissance",
            "nmap_open_services",
        )


# ============================================================
# GOBUSTER AND OTHER ENUMERATION COMMANDS
# ============================================================

def run_gobuster(workspace, config):
    if not command_exists("gobuster"):
        print("[-] Gobuster was not found in PATH.")
        append_timeline_note(
            workspace,
            "DEAD END",
            "Gobuster could not be started because it was not found in PATH.",
            tool="gobuster",
        )
        return

    print("\n" + "=" * 60)
    print("GOBUSTER ENUMERATION")
    print("=" * 60)
    print("1. Directory/content enumeration (dir)")
    print("2. Virtual-host enumeration (vhost)")
    print("3. DNS subdomain enumeration (dns)")
    choice = input("\nSelect Gobuster mode: ").strip()

    mode_map = {"1": "dir", "2": "vhost", "3": "dns"}
    mode = mode_map.get(choice)
    if not mode:
        print("[-] Invalid Gobuster mode.")
        return

    command = ["gobuster", mode]
    if mode in ("dir", "vhost"):
        default_url = f"http://{config['target_ip']}"
        target_url = input(f"Target URL [{default_url}]: ").strip() or default_url
        parsed = urlparse(target_url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            print("[-] Target must be a valid http:// or https:// URL.")
            return
        command.extend(["-u", target_url])
    else:
        domain = input("Authorized target domain: ").strip()
        if not domain:
            print("[-] Domain cannot be empty.")
            return
        command.extend(["-d", domain])

    wordlist = input("Wordlist path: ").strip()
    if not wordlist:
        print("[-] Wordlist path is required.")
        return
    command.extend(["-w", str(Path(wordlist).expanduser())])

    extra = input("Optional additional Gobuster arguments (or Enter): ").strip()
    if extra:
        if shell_meta_present(extra):
            print("[-] Shell operators are not accepted here. The helper already captures output.")
            return
        try:
            command.extend(shlex.split(extra))
        except ValueError as exc:
            print(f"[-] Could not parse additional arguments: {exc}")
            return

    purpose = prompt_purpose(
        "Enumerate authorized web/DNS content and record discovered resources for follow-up."
    )
    description = f"Gobuster {mode} enumeration"
    return record_tool_run(
        workspace,
        command,
        description,
        purpose,
        tool="gobuster",
    )


def run_enumeration_command(workspace):
    print("\n" + "=" * 60)
    print("RUN ENUMERATION / RECON COMMAND")
    print("=" * 60)
    print(
        "\nThe helper recognizes Nmap, Gobuster, ffuf, Feroxbuster, dirsearch,\n"
        "Nikto, WhatWeb, httpx, nuclei, DNS tools, SMB/LDAP enumeration tools,\n"
        "curl/wget, and generic commands. Raw stdout/stderr is always saved."
    )
    print("\nDo not add '| tee ...' here; this helper already performs the capture.")

    command_text = input("\nCommand: ").strip()
    if not command_text:
        print("[-] Command cannot be empty.")
        return
    if shell_meta_present(command_text):
        print("[-] Shell operators such as |, >, ;, && are not supported in this runner.")
        print("[-] Enter the tool command itself; output capture is automatic.")
        return

    try:
        command = shlex.split(command_text)
    except ValueError as exc:
        print(f"[-] Could not parse command: {exc}")
        return
    if not command:
        print("[-] Command cannot be empty.")
        return

    tool = identify_tool(command)
    purpose = prompt_purpose()
    description = input("Short description (or Enter for automatic): ").strip()
    if not description:
        description = f"{tool if tool != 'generic' else Path(command[0]).name} command"

    return record_tool_run(
        workspace,
        command,
        description,
        purpose,
        tool=tool,
    )


# ============================================================
# EVIDENCE
# ============================================================

def get_next_evidence_id(evidence_file):
    if not evidence_file.exists():
        return 1
    try:
        content = evidence_file.read_text(encoding="utf-8")
    except OSError:
        return 1
    matches = re.findall(r"^## E-(\d+)", content, flags=re.MULTILINE)
    return max((int(value) for value in matches), default=0) + 1


def record_evidence(workspace):
    ev_path = evidence_file(workspace)
    evidence_id = get_next_evidence_id(ev_path)

    print("\n" + "=" * 60)
    print(f"RECORD E-{evidence_id:03d}")
    print("=" * 60)

    phase = input("\nPhase/category: ").strip()
    description = input("Description: ").strip()
    source = input("Source file relative to workspace: ").strip()
    if not phase or not description or not source:
        print("[-] All fields are required.")
        return

    workspace_resolved = workspace.resolve()
    source_path = (workspace / source).resolve()
    try:
        source_path.relative_to(workspace_resolved)
    except ValueError:
        print("[-] Source must remain inside the workspace.")
        return

    evidence_time = human_timestamp()

    with ev_path.open("a", encoding="utf-8") as handle:
        handle.write(f"\n## E-{evidence_id:03d}\n")
        handle.write(f"- Time: {evidence_time}\n")
        handle.write(f"- Phase: {phase}\n")
        handle.write(f"- Description: {description}\n")
        handle.write(f"- Source: {source}\n")

    manifest_add(workspace, "evidence", {
        "id": f"E-{evidence_id:03d}",
        "time": evidence_time,
        "phase": phase,
        "description": description,
        "source": source,
    })

    append_timeline_note(
        workspace,
        "NONE",
        f"E-{evidence_id:03d}: {description}",
        origin="student",
        compact=True,
    )
    print(f"[+] Evidence E-{evidence_id:03d} recorded.")


# ============================================================
# SCREENSHOTS
# ============================================================

LINUX_SCREENSHOT_TOOLS = (
    "scrot",
    "grim",
    "gnome-screenshot",
    "xfce4-screenshooter",
    "import",
    "mate-screenshot",
)


def find_screenshot_command():
    for command in LINUX_SCREENSHOT_TOOLS:
        if command_exists(command):
            return command
    return None


def screenshot_argv(tool, dest):
    """Argv for a Linux screenshot tool. mate-screenshot cannot take -f."""
    dest = str(dest)
    if tool == "gnome-screenshot":
        return [tool, "-f", dest]
    if tool == "scrot":
        return [tool, dest]
    if tool == "grim":
        return [tool, dest]
    if tool == "xfce4-screenshooter":
        return [tool, "-f", "-s", dest]
    if tool == "import":
        return [tool, "-window", "root", dest]
    if tool == "mate-screenshot":
        return [tool]
    raise RuntimeError(f"Unsupported screenshot tool: {tool}")


def _pictures_dirs():
    dirs = []
    xdg = os.environ.get("XDG_PICTURES_DIR")
    if xdg:
        dirs.append(Path(xdg).expanduser())
    dirs.append(Path.home() / "Pictures")
    dirs.append(Path.home() / "Desktop")
    seen = set()
    out = []
    for folder in dirs:
        key = str(folder)
        if key in seen:
            continue
        seen.add(key)
        out.append(folder)
    return out


def _new_image_since(folders, started, before):
    candidates = []
    for folder in folders:
        if not folder.is_dir():
            continue
        try:
            entries = list(folder.iterdir())
        except OSError:
            continue
        for path in entries:
            if not path.is_file() or path.suffix.lower() not in (".png", ".jpg", ".jpeg"):
                continue
            try:
                resolved = path.resolve()
                mtime = path.stat().st_mtime
            except OSError:
                continue
            if resolved in before:
                continue
            if mtime + 1.0 >= started:
                candidates.append(path)
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def take_linux_screenshot(dest):
    """Capture the display into dest. mate-screenshot saves to Pictures; we move it."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tool = find_screenshot_command()
    if not tool:
        raise RuntimeError(
            "No screenshot utility. On Parrot: sudo apt install scrot  (or mate-utils)."
        )
    argv = screenshot_argv(tool, dest)
    if tool == "mate-screenshot":
        folders = _pictures_dirs()
        before = set()
        for folder in folders:
            if not folder.is_dir():
                continue
            try:
                for path in folder.iterdir():
                    if path.is_file() and path.suffix.lower() in (".png", ".jpg", ".jpeg"):
                        before.add(path.resolve())
            except OSError:
                continue
        started = time.time()
        result = subprocess.run(argv, check=False)
        if result.returncode != 0:
            raise RuntimeError(f"{tool} failed (exit {result.returncode}).")
        found = None
        for _ in range(25):
            found = _new_image_since(folders, started, before)
            if found:
                break
            time.sleep(0.12)
        if not found:
            raise RuntimeError(
                "mate-screenshot ran but no new image showed up in Pictures. "
                "Install scrot for a direct save: sudo apt install scrot"
            )
        shutil.move(str(found), str(dest))
    else:
        result = subprocess.run(argv, check=False)
        if result.returncode != 0 or not dest.exists() or dest.stat().st_size == 0:
            if dest.exists() and dest.stat().st_size == 0:
                try:
                    dest.unlink()
                except OSError:
                    pass
            raise RuntimeError(f"{tool} failed (exit {result.returncode}).")
    if not dest.exists() or dest.stat().st_size == 0:
        raise RuntimeError(f"{tool} produced an empty screenshot.")
    return dest, tool


def infer_milestones_from_screenshots(workspace):
    """Treat files like User-flag.png as the user-flag milestone even if not captured via the menu."""
    folder = screenshots_dir(workspace)
    names = []
    if folder.is_dir():
        for path in folder.iterdir():
            if path.is_file():
                names.append(path.name.lower())
    blob = " ".join(names)
    checks = {
        "user_flag": ("user-flag", "user_flag", "userflag"),
        "root_admin_flag": ("root-flag", "root_flag", "rootflag", "admin-flag", "admin_flag"),
        "initial_recon": ("initial-recon", "initial_recon", "recon"),
        "initial_foothold": ("foothold", "initial-foothold", "initial_foothold"),
        "privilege_escalation": ("privesc", "priv-esc", "privilege"),
        "vulnerability_evidence": ("vuln-evidence", "vulnerability"),
    }
    found = {}
    for key, needles in checks.items():
        found[key] = any(needle in blob for needle in needles)
    return found


def milestone_label(milestone):
    labels = {
        "initial_recon": "Initial recon screenshot",
        "initial_foothold": "Initial foothold screenshot",
        "vulnerability_evidence": "Vulnerability-evidence screenshot",
        "privilege_escalation": "Privilege-escalation screenshot",
        "user_flag": "User-flag screenshot (only if you took one — do not type this in notes)",
        "root_admin_flag": "Root/admin-flag screenshot (only if you took one)",
        "other": "Other screenshot",
    }
    return labels.get(milestone, milestone.replace("_", " "))


def screenshot_category():
    order = [
        "initial_recon",
        "initial_foothold",
        "vulnerability_evidence",
        "privilege_escalation",
        "user_flag",
        "root_admin_flag",
        "other",
    ]
    categories = {
        str(i): (key, SCREENSHOT_MILESTONES[key])
        for i, key in enumerate(order, start=1)
    }
    print("\nScreenshot milestone:")
    for key, value in categories.items():
        print(f"{key}. {value[1]}")
    return categories.get(input("\nSelect milestone: ").strip())


def milestone_is_complete(workspace, milestone):
    manifest = load_manifest(workspace) or {}
    return bool(manifest.get("milestones", {}).get(milestone, False))


def ask_yes_no(prompt, default=False):
    suffix = " [Y/n]: " if default else " [y/N]: "
    answer = input(prompt + suffix).strip().lower()
    if not answer:
        return default
    return answer in ("y", "yes")


def capture_screenshot(workspace, milestone, milestone_name, description_raw):
    """Capture and register a screenshot for a known milestone."""
    screenshots = screenshots_dir(workspace)
    screenshots.mkdir(parents=True, exist_ok=True)

    command_name = find_screenshot_command()
    if not command_name:
        print("[-] No supported screenshot utility found.")
        print("    Install scrot, mate-utils, gnome-screenshot, or ImageMagick.")
        return None

    description = safe_filename(description_raw)
    if not description:
        description = safe_filename(milestone_name) or "screenshot"

    path = screenshots / f"{timestamp_seconds()}_{milestone}_{description}.png"
    command = screenshot_argv(command_name, path)
    save_command_record(workspace, command, "Screenshot capture", milestone_name)
    try:
        take_linux_screenshot(path)
    except RuntimeError as exc:
        print(f"[-] {exc}")
        return None

    metadata = file_metadata(workspace, path)
    manifest_add(workspace, "screenshots", {
        "time": human_timestamp(),
        "milestone": milestone,
        "milestone_name": milestone_name,
        "description": description_raw,
        "file": metadata,
    })
    update_milestone(workspace, milestone)
    append_timeline_note(
        workspace,
        "EVIDENCE",
        f"Captured {milestone_name.lower()} screenshot: {description_raw}",
        tool=command_name,
        evidence=[relative_path(workspace, path)],
        outcome="The screenshot file was created and verified as non-empty.",
        metadata={"event": "milestone_screenshot", "milestone": milestone},
    )
    print(f"[+] Screenshot captured: {path}")
    return path


def offer_milestone_screenshot(
    workspace,
    milestone,
    milestone_name,
    description_hint,
    *,
    skip_if_complete=True,
):
    """Offer a screenshot at a meaningful point without inferring the event."""
    if skip_if_complete and milestone != "other" and milestone_is_complete(workspace, milestone):
        print(f"[+] {milestone_name} screenshot milestone is already recorded; no prompt needed.")
        return None

    if not find_screenshot_command():
        print(f"[WARN] {milestone_name} may be worth a screenshot, but no supported screenshot utility is installed.")
        return None

    print(f"\n[+] Suggested screenshot milestone: {milestone_name}")
    if not ask_yes_no(f"Capture the current screen as {milestone_name} evidence?", default=False):
        print("[+] Screenshot skipped; no milestone was marked complete.")
        return None

    description_raw = input(f"Short description [{description_hint}]: ").strip() or description_hint
    return capture_screenshot(
        workspace,
        milestone,
        milestone_name,
        description_raw,
    )


def offer_flag_screenshot(workspace):
    """Ask the student which flag milestone applies; never infer it automatically."""
    print("\nFlag screenshot type:")
    print("1. User flag")
    print("2. Root/admin flag")
    print("3. Other screenshot")
    print("4. Skip screenshot")
    choice = input("\nSelect type: ").strip()

    if choice == "1":
        return offer_milestone_screenshot(
            workspace,
            "user_flag",
            "User flag",
            "user_flag",
        )
    if choice == "2":
        return offer_milestone_screenshot(
            workspace,
            "root_admin_flag",
            "Root/admin flag",
            "root_admin_flag",
        )
    if choice == "3":
        return offer_milestone_screenshot(
            workspace,
            "other",
            "Other",
            "flag_related_evidence",
            skip_if_complete=False,
        )

    print("[+] Flag screenshot skipped.")
    return None


def record_screenshot(workspace):
    """Manual screenshot capture from the menu."""
    print("\n" + "=" * 60)
    print("CAPTURE MILESTONE SCREENSHOT")
    print("=" * 60)

    selected = screenshot_category()
    if not selected:
        print("[-] Invalid screenshot milestone.")
        return
    milestone, milestone_name = selected

    description_raw = input("\nShort description: ").strip()
    if not description_raw:
        print("[-] Description cannot be empty.")
        return

    return capture_screenshot(
        workspace,
        milestone,
        milestone_name,
        description_raw,
    )


def show_recent_notes(workspace, count=8):
    """Display the most recent timeline entries for quick verification."""
    path = notes_file(workspace)
    if not path.exists():
        print("[-] notes file does not exist.")
        return

    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print(f"[-] Could not read notes: {exc}")
        return

    starts = [m.start() for m in re.finditer(r"(?m)^\[\d{2}:\d{2}\]", content)]
    print("\n" + "=" * 60)
    print("RECENT RESEARCH NOTES")
    print("=" * 60)
    if not starts:
        print("\nNo timeline entries found yet.")
        return

    start = starts[max(0, len(starts) - count)]
    print("\n" + content[start:].rstrip())


# ============================================================
# PREFLIGHT
# ============================================================

def preflight_check(workspace):
    print("\n" + "=" * 60)
    print("HTB RESEARCH ENVIRONMENT CHECK")
    print("=" * 60)

    all_good = True
    for name, result in (
        ("Python", sys.executable),
        ("script", shutil.which("script")),
        ("nmap", shutil.which("nmap")),
    ):
        status = "PASS" if result else "FAIL"
        print(f"[{status}] {name:<18}")
        if not result:
            all_good = False

    optional = (
        "gobuster", "ffuf", "feroxbuster", "dirsearch", "nikto",
        "whatweb", "httpx", "nuclei", "enum4linux-ng", "smbclient",
        "ldapsearch", "nxc", "curl", "dig",
    )
    found = [tool for tool in optional if command_exists(tool)]
    print(f"[INFO] Recognized optional tools installed: {', '.join(found) if found else 'none detected'}")

    screenshot = find_screenshot_command()
    print(f"[{'PASS' if screenshot else 'WARN'}] Screenshot utility   {screenshot or 'not found'}")

    for folder_name in ("logs", "screenshots", "notes"):
        folder = workspace / folder_name
        status = "PASS" if folder.is_dir() else "FAIL"
        print(f"[{status}] {folder_name + '/':<18}")
        if not folder.is_dir():
            all_good = False

    try:
        test_file = workspace / ".write_test"
        test_file.write_text("test", encoding="utf-8")
        test_file.unlink()
        print("[PASS] Writable workspace")
    except OSError:
        print("[FAIL] Writable workspace")
        all_good = False

    print("\n[+] Environment appears ready." if all_good else "\n[-] One or more required checks failed.")
    return all_good


# ============================================================
# FILE INVENTORY, STATISTICS, VALIDATION, ZIP
# ============================================================

def list_files(workspace):
    print("\n" + "=" * 60)
    print("COLLECTED FILES")
    print("=" * 60)
    files = sorted(path for path in workspace.rglob("*") if path.is_file())
    if not files:
        print("\nNo files found.")
        return

    total_size = 0
    for path in files:
        try:
            size = path.stat().st_size
            total_size += size
            print(f"{relative_path(workspace, path)} ({size:,} bytes)")
        except OSError:
            print(f"{relative_path(workspace, path)} (unable to read size)")
    print("\n" + "-" * 60)
    print(f"Files: {len(files)}")
    print(f"Total size: {total_size:,} bytes")


def research_statistics(workspace):
    manifest = load_manifest(workspace) or {}
    logs = logs_dir(workspace)
    screenshots = screenshots_dir(workspace)
    notes_path = notes_file(workspace)
    ev_path = evidence_file(workspace)

    note_count = 0
    if notes_path.exists():
        try:
            note_count = len(re.findall(r"^\[\d{2}:\d{2}\]", notes_path.read_text(encoding="utf-8"), re.M))
        except OSError:
            pass

    evidence_count = 0
    if ev_path.exists():
        try:
            evidence_count = len(re.findall(r"^## E-\d+", ev_path.read_text(encoding="utf-8"), re.M))
        except OSError:
            pass

    tool_runs = manifest.get("tool_runs", [])
    by_tool = {}
    for run in tool_runs:
        tool = run.get("tool_label") or run.get("tool") or "unknown"
        by_tool[tool] = by_tool.get(tool, 0) + 1

    print("\n" + "=" * 60)
    print("RESEARCH STATISTICS")
    print("=" * 60)
    print(f"\nSession logs:       {len(list(logs.glob('session*.log')))}")
    print(f"Tool runs:          {len(tool_runs)}")
    print(f"Timeline notes:     {note_count}")
    print(f"Evidence entries:   {evidence_count}")
    print(f"Screenshots:        {len(list(screenshots.glob('*.png')))}")
    if by_tool:
        print("\nTool runs by type:")
        for tool, count in sorted(by_tool.items()):
            print(f"  {tool:<18} {count}")

    milestones = manifest.get("milestones", {})
    inferred = infer_milestones_from_screenshots(workspace)
    for key, hit in inferred.items():
        if hit:
            milestones[key] = True
    if milestones:
        print("\nScreenshot milestones (optional):")
        for milestone, complete in milestones.items():
            print(f"  [{'PASS' if complete else 'WARN'}] {milestone_label(milestone)}")


def validate_submission(workspace):
    print("\n" + "=" * 60)
    print("RESEARCH DATA VALIDATION")
    print("=" * 60)
    failures = []
    warnings = []

    for label, path in (
        ("logs", logs_dir(workspace)),
        ("screenshots", screenshots_dir(workspace)),
        ("notes", notes_dir(workspace)),
        ("report", report_dir(workspace)),
        ("files_given", files_given_dir(workspace)),
    ):
        if path.is_dir():
            print(f"[PASS] {path.name}/ exists")
        else:
            print(f"[FAIL] {path.name}/ missing")
            failures.append(f"Missing directory: {path.name}")

    required_files = (
        notes_file(workspace),
        evidence_file(workspace),
        metadata_path(workspace),
        manifest_path(workspace),
    )
    for path in required_files:
        if path.exists():
            print(f"[PASS] {relative_path(workspace, path)} exists")
        else:
            print(f"[FAIL] {relative_path(workspace, path)} missing")
            failures.append(f"Missing file: {relative_path(workspace, path)}")

    session_logs = list(logs_dir(workspace).glob("session*.log"))
    if not session_logs:
        print("[WARN] No session logs found")
        warnings.append("No session logs found. The study requires continuous terminal logging.")
    else:
        good_logs = [log for log in session_logs if verify_session_log(log)]
        print(f"[PASS] {len(good_logs)}/{len(session_logs)} session log(s) contain data")
        if len(good_logs) != len(session_logs):
            warnings.append("One or more session logs are empty or unreadable.")

    manifest = load_manifest(workspace)
    if not manifest:
        print("[FAIL] Research manifest unreadable")
        failures.append("Research manifest could not be read.")
    else:
        print("[PASS] Research manifest readable")
        tool_runs = manifest.get("tool_runs", [])
        if tool_runs:
            print(f"[PASS] {len(tool_runs)} captured tool run(s)")
        else:
            print("[WARN] No captured tool runs in manifest")
            warnings.append("No tool runs were captured through the helper.")

        missing_raw = []
        for run in tool_runs:
            output = run.get("output") or {}
            rel = output.get("file") if isinstance(output, dict) else None
            if rel and not (workspace / rel).exists():
                missing_raw.append(rel)
        if missing_raw:
            print(f"[WARN] {len(missing_raw)} manifest raw-output file(s) are missing")
            warnings.append("Some manifest entries reference missing raw-output files.")
        elif tool_runs:
            print("[PASS] Captured tool runs reference existing raw-output files")

        notes = manifest.get("notes", [])
        student_notes = [item for item in notes if item.get("origin") == "student"]
        purpose_notes = [item for item in notes if item.get("purpose")]
        if notes:
            print(f"[PASS] {len(notes)} timeline note(s) recorded")
        else:
            print("[WARN] No timeline notes recorded")
            warnings.append("No research timeline notes were recorded.")
        if student_notes or purpose_notes:
            print("[PASS] Student reasoning/purpose is present in the notes")
        else:
            print("[WARN] No student-entered reasoning/purpose detected")
            warnings.append("The instructions require documenting what was tried and why in real time.")

        milestones = manifest.get("milestones", {})
        inferred = infer_milestones_from_screenshots(workspace)
        for key, hit in inferred.items():
            if hit:
                milestones[key] = True
                update_milestone(workspace, key)
        print("\nScreenshot milestones (optional — WARN only means none recorded yet):")
        print("  Filenames like User-flag.png in screenshots/ count as the user-flag milestone.")
        for milestone, complete in milestones.items():
            print(f"  [{'PASS' if complete else 'WARN'}] {milestone_label(milestone)}")

    screenshot_files = list(screenshots_dir(workspace).glob("*"))
    screenshot_files = [p for p in screenshot_files if p.is_file() and p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".gif"}]
    if screenshot_files:
        print(f"[PASS] {len(screenshot_files)} screenshot(s) found")
    else:
        print("[WARN] No screenshots found")
        warnings.append("No milestone screenshots found.")

    if failures:
        print("\n[-] Validation FAILED.")
        for failure in failures:
            print(f"    - {failure}")
    elif warnings:
        print("\n[!] Validation completed with warnings.")
        for warning in warnings:
            print(f"    - {warning}")
    return not failures


def vpn_addresses():
    """Likely HTB VPN / tun addresses on this box (Pwnbox attacking IP)."""
    addrs = []
    try:
        if os.name == "nt":
            result = subprocess.run(
                ["ipconfig"],
                capture_output=True, text=True, errors="replace", check=False,
            )
            for line in result.stdout.splitlines():
                line = line.strip()
                if "IPv4" in line and ":" in line:
                    ip = line.split(":")[-1].strip()
                    if ip.startswith("10."):
                        addrs.append(ip)
        else:
            result = subprocess.run(
                ["ip", "-4", "-o", "addr", "show"],
                capture_output=True, text=True, errors="replace", check=False,
            )
            for line in result.stdout.splitlines():
                if any(tag in line for tag in (" tun", " tap", "tun0", "tap0")):
                    parts = line.split()
                    for item in parts:
                        if "/" in item and item[0].isdigit():
                            addrs.append(item.split("/")[0])
    except OSError:
        pass
    return addrs


def seven_zip_bin():
    return shutil.which("7z") or shutil.which("7za") or shutil.which("7z.exe")


def stage_export_tree(workspace):
    """Stage report folders as student_machine_logs, _notes, etc. No machine_json."""
    workspace = Path(workspace).resolve()
    slug = workspace.name
    root = Path(tempfile.mkdtemp(prefix="htb-export-"))
    staged = root / slug
    staged.mkdir()
    mapping = {
        "logs": f"{slug}_logs",
        "screenshots": f"{slug}_screenshots",
        "notes": f"{slug}_notes",
        "report": f"{slug}_report",
        "files_given": f"{slug}_files_given",
    }
    copied = []
    for src_name, dest_name in mapping.items():
        src = workspace / src_name
        dest = staged / dest_name
        dest.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            for item in src.iterdir():
                target = dest / item.name
                if item.is_dir():
                    shutil.copytree(item, target, dirs_exist_ok=True)
                else:
                    shutil.copy2(item, target)
        copied.append(dest_name)
    notes_dest = staged / f"{slug}_notes"
    notes_dest.mkdir(parents=True, exist_ok=True)
    for src in (notes_file(workspace), evidence_file(workspace)):
        if src.is_file():
            shutil.copy2(src, notes_dest / src.name)
    for stray in ("notes.md", "evidence.md"):
        src = workspace / stray
        if src.is_file() and not (notes_dest / stray).exists():
            shutil.copy2(src, notes_dest / stray)
    return root, staged, copied


def create_export_archive(workspace, *, encrypt=False, password=""):
    """Zip (or 7z) using absolute paths so 7z does not write into the temp cwd."""
    workspace = Path(workspace).resolve()
    slug = workspace.name
    stamp = timestamp_seconds()
    root, staged, copied = stage_export_tree(workspace)
    dest_dir = workspace.parent.resolve()
    dest_dir.mkdir(parents=True, exist_ok=True)
    try:
        if encrypt:
            binary = seven_zip_bin()
            if not binary:
                raise RuntimeError(
                    "7z is not installed. On Parrot/Kali: sudo apt install p7zip-full"
                )
            if not password:
                raise RuntimeError("A password is required for 7z encryption.")
            archive = dest_dir / f"{slug}_{stamp}.7z"
            cmd = [
                binary, "a", "-t7z", "-mhe=on", f"-p{password}",
                str(archive), slug,
            ]
            result = subprocess.run(
                cmd, cwd=str(root), check=False,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            )
            if result.returncode != 0 or not archive.is_file():
                raise RuntimeError(result.stdout.strip() or "7z failed.")
            return str(archive), copied, "7z"
        archive_base = dest_dir / f"{slug}_{stamp}"
        archive = shutil.make_archive(
            str(archive_base), "zip", root_dir=str(root), base_dir=slug,
        )
        return str(Path(archive).resolve()), copied, "zip"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _rewrite_zip_member_name(name, old_slug, new_slug):
    parts = name.split("/")
    rewritten = []
    for part in parts:
        if part == old_slug or part.startswith(old_slug + "_"):
            rewritten.append(new_slug + part[len(old_slug):])
        else:
            rewritten.append(part)
    return "/".join(rewritten)


def rewrite_zip_export_slug(zip_path, old_slug, new_slug):
    """Rename student_old_* prefixes inside an export zip to student_new_*."""
    zip_path = Path(zip_path)
    if zip_path.suffix.lower() != ".zip" or not zip_path.is_file():
        return False
    if not old_slug or old_slug == new_slug:
        return False
    tmp = zip_path.with_name(zip_path.name + ".renaming")
    changed = False
    try:
        with zipfile.ZipFile(zip_path, "r") as src, zipfile.ZipFile(
            tmp, "w", compression=zipfile.ZIP_DEFLATED
        ) as dst:
            for info in src.infolist():
                new_name = _rewrite_zip_member_name(info.filename, old_slug, new_slug)
                if new_name != info.filename:
                    changed = True
                data = src.read(info.filename)
                new_info = zipfile.ZipInfo(filename=new_name, date_time=info.date_time)
                new_info.compress_type = zipfile.ZIP_DEFLATED
                new_info.external_attr = info.external_attr
                dst.writestr(new_info, data)
        if changed:
            tmp.replace(zip_path)
            return True
        tmp.unlink(missing_ok=True)
        return False
    except (OSError, zipfile.BadZipFile):
        tmp.unlink(missing_ok=True)
        return False


def rename_export_archives(old_workspace, new_workspace):
    """Rename sibling zip/7z files and rewrite zip inner folders to the new slug."""
    old_slug = Path(old_workspace).name
    new_slug = Path(new_workspace).name
    if not old_slug or old_slug == new_slug:
        return []
    dest_dir = Path(new_workspace).resolve().parent
    if not dest_dir.is_dir():
        dest_dir = Path(old_workspace).resolve().parent
    moved = []
    if not dest_dir.is_dir():
        return moved
    for path in list(dest_dir.iterdir()):
        if not path.is_file():
            continue
        suffix = path.suffix.lower()
        if suffix not in (".zip", ".7z"):
            continue
        stem_match = path.name == f"{old_slug}{path.suffix}" or path.name.startswith(old_slug + "_")
        if not stem_match:
            continue
        new_path = dest_dir / (new_slug + path.name[len(old_slug):])
        if new_path.exists():
            continue
        try:
            path.rename(new_path)
        except OSError:
            continue
        if suffix == ".zip":
            rewrite_zip_export_slug(new_path, old_slug, new_slug)
        moved.append(str(new_path))
    return moved


def create_zip(workspace):
    print("\n" + "=" * 60)
    print("CREATING ZIP BACKUP")
    print("=" * 60)
    try:
        archive, copied, kind = create_export_archive(workspace)
        print(f"\n[+] Archive created ({kind}):\n    {archive}")
        print(f"[+] Included: {', '.join(copied) or '(empty)'}")
        print("[+] machine_json/ was left out (app-only).")
    except Exception as exc:
        print(f"[-] Could not create archive: {exc}")


# ============================================================
# MACHINE / LAB SWITCHING (CLI)
# ============================================================

def prompt_line(label, default=""):
    shown = "" if default in (None, "") else str(default)
    extra = f" [{shown}]" if shown else ""
    value = input(f"{label}{extra}: ").strip()
    return shown if not value else value


def prompt_port(default=None):
    shown = "" if default in (None, "", 0) else str(default)
    extra = f" [{shown}]" if shown else " [none]"
    raw = input(f"Assigned port{extra}: ").strip()
    if not raw:
        if shown:
            try:
                return int(shown)
            except ValueError:
                return None
        return None
    if raw.lower() in ("none", "no", "-"):
        return None
    try:
        port = int(raw)
    except ValueError:
        print("[-] Port must be an integer or blank.")
        return default if default not in (None, "", 0) else None
    if not 1 <= port <= 65535:
        print("[-] Port must be between 1 and 65535.")
        return default if default not in (None, "", 0) else None
    return port


def workspace_root_from_config(config):
    root = Path(config.get("workspace_root", "./machines")).expanduser()
    return root


def load_lab_metadata(folder):
    folder = Path(folder)
    for candidate in (metadata_path(folder), folder / "metadata.json"):
        if not candidate.exists():
            continue
        try:
            data = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict):
            return data
    return {}


def write_lab_metadata(workspace, config):
    path = metadata_path(workspace)
    existing = load_lab_metadata(workspace)
    existing.update({
        "helper_version": APP_VERSION,
        "student_id": config["student_id"],
        "machine_name": config["machine_name"],
        "target_ip": config["target_ip"],
        "assigned_port": config.get("target_port"),
        "research_project": config.get(
            "research_project",
            existing.get(
                "research_project",
                "HTB Enterprise AI Generated Pentest Report Study",
            ),
        ),
    })
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(existing, indent=4) + "\n", encoding="utf-8")


def refresh_notes_machine_header(workspace, old_name, config):
    path = notes_file(workspace)
    if not path.exists():
        return
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return
    new_name = config["machine_name"]
    lines = text.splitlines()
    if lines and (lines[0].strip() == f"# {old_name}" or lines[0].strip() == "# HTB Enterprise Research Notes"):
        lines[0] = f"# {new_name}"
    for index, line in enumerate(lines[:16]):
        if line.startswith("Machine:"):
            lines[index] = f"Machine: {new_name}"
        elif line.startswith("Target:"):
            lines[index] = f"Target: {config['target_ip']}"
        elif line.startswith("Assigned Port:"):
            lines[index] = f"Assigned Port: {config.get('target_port') or 'None'}"
        elif line.startswith("Student ID:"):
            lines[index] = f"Student ID: {config['student_id']}"
    new_text = "\n".join(lines)
    if text.endswith("\n"):
        new_text += "\n"
    if new_text != text:
        path.write_text(new_text, encoding="utf-8")


def refresh_report_machine_header(workspace, old_name, config):
    path = report_file(workspace)
    if not path.exists() or not old_name:
        return
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return
    new_name = config["machine_name"]
    if old_name == new_name:
        return
    updated = text
    old_heading = f"# HTB Challenge: {old_name}"
    if updated.startswith(old_heading):
        updated = f"# HTB Challenge: {new_name}" + updated[len(old_heading):]
    updated = updated.replace(
        f"authorized HTB machine **{old_name}**",
        f"authorized HTB machine **{new_name}**",
        1,
    )
    target = config.get("target_ip") or ""
    port = config.get("target_port") or "None"
    updated = re.sub(
        r"at `[^`]+`\n\(assigned port: `[^`]+`\)\.",
        f"at `{target}`\n(assigned port: `{port}`).",
        updated,
        count=1,
    )
    if updated != text:
        path.write_text(updated, encoding="utf-8")


def list_lab_folders(config):
    root = workspace_root_from_config(config)
    labs = []
    if not root.is_dir():
        return labs
    for folder in sorted(p for p in root.iterdir() if p.is_dir()):
        meta = load_lab_metadata(folder)
        labs.append({
            "id": folder.name,
            "path": folder,
            "student_id": meta.get("student_id") or "",
            "machine_name": meta.get("machine_name") or folder.name,
            "target_ip": meta.get("target_ip") or "",
            "target_port": meta.get("assigned_port"),
            "research_project": meta.get("research_project") or "",
        })
    return labs


def print_lab_list(config, workspace):
    labs = list_lab_folders(config)
    current = Path(workspace).name if workspace else ""
    print("\nExisting labs:")
    if not labs:
        print("  (none yet)")
        return labs
    for index, lab in enumerate(labs, start=1):
        mark = "  <- current" if lab["id"] == current else ""
        port = lab["target_port"] or "no port"
        print(
            f"  {index}. {lab['id']}  "
            f"({lab['machine_name']}, {lab['target_ip'] or 'no IP'}, {port}){mark}"
        )
    return labs


def config_from_lab(folder, previous):
    meta = load_lab_metadata(folder)
    if not meta.get("student_id") or not meta.get("machine_name") or not meta.get("target_ip"):
        print("[-] That lab folder is missing machine_json/metadata.json (student, machine, IP).")
        return None
    return {
        "student_id": meta["student_id"],
        "machine_name": meta["machine_name"],
        "target_ip": meta["target_ip"],
        "target_port": meta.get("assigned_port"),
        "workspace_root": previous.get("workspace_root", "./machines"),
        "research_project": meta.get(
            "research_project",
            previous.get("research_project", "HTB Enterprise AI Generated Pentest Report Study"),
        ),
        "gui_port": previous.get("gui_port", 8765),
        "lab_folder": Path(folder).name,
    }


def apply_cli_config(config, workspace, config_path, *, old_name=None, renamed_from=None):
    if workspace is not None:
        config = dict(config)
        config["lab_folder"] = Path(workspace).name
    save_config(config_path, config)
    workspace = setup_workspace(config, workspace=workspace)
    config["lab_folder"] = Path(workspace).name
    save_config(config_path, config)
    write_lab_metadata(workspace, config)
    if old_name:
        refresh_notes_machine_header(workspace, old_name, config)
        refresh_report_machine_header(workspace, old_name, config)
    if renamed_from:
        print(f"[+] Folder renamed:\n    {renamed_from}\n    -> {workspace}")
    print(f"[+] Active machine: {config['machine_name']}")
    print(f"[+] Workspace:      {workspace}")
    return config, workspace


def session_blocks_workspace_change(session_active):
    if not session_active:
        return False
    print("\n[-] Session logging is active, so the workspace folder cannot move.")
    print("    Exit this logged menu (option 15), then run ./htb --cli again")
    print("    and use option 14 to switch or start a new machine.")
    return True


def change_current_machine(config, workspace, config_path, session_active=False):
    print("\nChange this lab's machine name / target (same folder if the name slug matches).")
    old_name = config["machine_name"]
    old_workspace = Path(workspace).resolve()
    student = prompt_line("Student ID", config.get("student_id") or "")
    machine = prompt_line("Machine name", old_name)
    target = prompt_line("Target IP", config.get("target_ip") or "")
    port = prompt_port(config.get("target_port"))
    updated = dict(config)
    updated.pop("lab_folder", None)
    updated["student_id"] = student
    updated["machine_name"] = machine
    updated["target_ip"] = target
    updated["target_port"] = port
    if not validate_config(updated):
        return config, workspace
    new_workspace = workspace_from_config(updated).resolve()
    if new_workspace != old_workspace:
        if session_blocks_workspace_change(session_active):
            return config, workspace
        if new_workspace.exists():
            print(f"[-] Cannot rename: {new_workspace} already exists.")
            return config, workspace
        old_workspace.rename(new_workspace)
        archives = rename_export_archives(old_workspace, new_workspace)
        config, workspace = apply_cli_config(
            updated,
            new_workspace,
            config_path,
            old_name=old_name,
            renamed_from=old_workspace,
        )
        for archive in archives:
            print(f"[+] Export renamed:\n    {archive}")
        return config, workspace
    return apply_cli_config(updated, new_workspace, config_path, old_name=old_name)


def switch_existing_lab(config, workspace, config_path, session_active=False):
    if session_blocks_workspace_change(session_active):
        return config, workspace
    labs = print_lab_list(config, workspace)
    if not labs:
        return config, workspace
    raw = input("\nSwitch to lab number: ").strip()
    try:
        index = int(raw)
    except ValueError:
        print("[-] Enter a number from the list.")
        return config, workspace
    if not 1 <= index <= len(labs):
        print("[-] That number is not on the list.")
        return config, workspace
    chosen = labs[index - 1]
    if Path(workspace).name == chosen["id"]:
        print("[+] Already on that lab.")
        return config, workspace
    updated = config_from_lab(chosen["path"], config)
    if updated is None or not validate_config(updated):
        return config, workspace
    return apply_cli_config(updated, chosen["path"], config_path)


def start_new_machine(config, workspace, config_path, session_active=False):
    if session_blocks_workspace_change(session_active):
        return config, workspace
    print("\nStart a new machine. The current lab folder is left as-is.")
    student = prompt_line("Student ID", config.get("student_id") or "")
    machine = prompt_line("New machine name", "")
    target = prompt_line("Target IP", "")
    port = prompt_port(None)
    updated = dict(config)
    updated.pop("lab_folder", None)
    updated["student_id"] = student
    updated["machine_name"] = machine
    updated["target_ip"] = target
    updated["target_port"] = port
    if not validate_config(updated):
        return config, workspace
    destination = workspace_from_config(updated)
    if destination.exists():
        print(f"[!] Folder already exists — switching to it:\n    {destination}")
    else:
        print(f"[+] Creating new lab folder:\n    {destination}")
    return apply_cli_config(updated, destination, config_path)


def manage_machine_menu(config, workspace, config_path, session_active=False):
    print("\n" + "=" * 60)
    print("MACHINE / LAB")
    print("=" * 60)
    print(f"Current machine: {config.get('machine_name')}")
    print(f"Student:         {config.get('student_id')}")
    print(f"Target:          {config.get('target_ip')}")
    print(f"Port:            {config.get('target_port') or 'None'}")
    print(f"Workspace:       {workspace}")
    print_lab_list(config, workspace)
    print("\n1. Keep current (back)")
    print("2. Change this lab's machine name / IP / port")
    print("3. Switch to an existing lab")
    print("4. Start a new machine (new workspace)")
    choice = input("\nSelect an option: ").strip()
    if choice in ("", "1"):
        return config, workspace
    if choice == "2":
        return change_current_machine(config, workspace, config_path, session_active)
    if choice == "3":
        return switch_existing_lab(config, workspace, config_path, session_active)
    if choice == "4":
        return start_new_machine(config, workspace, config_path, session_active)
    print("\n[-] Invalid option.")
    return config, workspace


# ============================================================
# HEADER / MENU
# ============================================================

def display_header(config, workspace, session_active=False):
    print("\n" + "=" * 60)
    print(f" {APP_NAME}")
    print("=" * 60)
    print(f"Version:   {APP_VERSION}")
    print(f"Student:   {config['student_id']}")
    print(f"Machine:   {config['machine_name']}")
    print(f"Target:    {config['target_ip']}")
    print(f"Port:      {config.get('target_port') or 'None'}")
    print(f"Workspace: {workspace}")
    print(f"Session:   {'ACTIVE' if session_active else 'NOT ACTIVE / NOT VERIFIED'}")


def display_menu(session_active=False):
    print("\n" + "=" * 60)
    print("HTB RESEARCH MENU")
    print("=" * 60)
    print("1. " + ("Session logging is ACTIVE" if session_active else "Start logged helper session"))
    print("2. Run Nmap service/version reconnaissance")
    print("3. Scan assigned port with Nmap service/version detection")
    print("4. Run Gobuster enumeration")
    print("5. Run other enumeration/recon command + auto-note")
    print("6. Add student research note")
    print("7. Record evidence")
    print("8. Capture milestone screenshot")
    print("9. Show recent research notes")
    print("10. Show collected files")
    print("11. Show research statistics")
    print("12. Validate research data")
    print("13. Create ZIP backup")
    print("14. View / change machine, or start a new one")
    print("15. Exit")


def interactive_mode(config, workspace, config_path, session_active=False):
    while True:
        display_header(config, workspace, session_active)
        display_menu(session_active)
        choice = input("\nSelect an option: ").strip()

        if choice == "1":
            if session_active:
                print("\n[+] Session logging is already active for this helper instance.")
            else:
                start_session_logging(config, workspace, config_path)

        elif choice == "2":
            run_nmap(
                workspace,
                config["target_ip"],
                scan_args=["-Pn", "-sV"],
                description="Nmap service/version reconnaissance",
            )

        elif choice == "3":
            port = config.get("target_port")
            if not port:
                print("\n[-] No assigned target port is configured.")
            else:
                run_nmap(
                    workspace,
                    config["target_ip"],
                    port=port,
                    scan_args=["-Pn", "-sV"],
                    description=f"Nmap assigned-port service/version scan ({port})",
                )

        elif choice == "4":
            run_gobuster(workspace, config)

        elif choice == "5":
            run_enumeration_command(workspace)

        elif choice == "6":
            add_note(workspace)

        elif choice == "7":
            record_evidence(workspace)

        elif choice == "8":
            record_screenshot(workspace)

        elif choice == "9":
            show_recent_notes(workspace)

        elif choice == "10":
            list_files(workspace)

        elif choice == "11":
            research_statistics(workspace)

        elif choice == "12":
            validate_submission(workspace)

        elif choice == "13":
            create_zip(workspace)

        elif choice == "14":
            config, workspace = manage_machine_menu(
                config, workspace, config_path, session_active,
            )

        elif choice == "15":
            print("\n[+] Exiting.")
            print("[+] Keep a backup of your research data.")
            break

        else:
            print("\n[-] Invalid option.")

        pause()


# ============================================================
# CLI
# ============================================================

def parse_arguments():
    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument("--config", default="config.json", help="Path to JSON configuration file.")
    parser.add_argument("--check", action="store_true", help="Run environment checks and exit.")
    parser.add_argument("--validate", action="store_true", help="Validate the research workspace and exit.")
    parser.add_argument("--stats", action="store_true", help="Display research statistics and exit.")
    parser.add_argument("--list", action="store_true", help="List collected files and exit.")
    parser.add_argument("--inside-session", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--session-log", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--version", action="version", version=f"%(prog)s {APP_VERSION}")
    return parser.parse_args()


def main():
    args = parse_arguments()
    print("=" * 60)
    print(APP_NAME)
    print("=" * 60)

    config = load_config(args.config)
    if not validate_config(config):
        sys.exit(1)

    workspace = setup_workspace(config)

    if args.inside_session:
        announce_inside_session(workspace, args.session_log)

    if args.check:
        preflight_check(workspace)
        return
    if args.validate:
        validate_submission(workspace)
        return
    if args.stats:
        research_statistics(workspace)
        return
    if args.list:
        list_files(workspace)
        return

    try:
        interactive_mode(
            config,
            workspace,
            args.config,
            session_active=args.inside_session,
        )
    except KeyboardInterrupt:
        print("\n\n[+] Exiting.")
        print("[+] Keep a backup of your research data.")
        sys.exit(0)


if __name__ == "__main__":
    main()
