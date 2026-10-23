"""Version, dev-build notice, release check, and approved-lab lookup.

Stdlib only. No API keys. Never contacts Hack The Box.
The lab list is the public JSON on main. A failed download does not
block the student, and this module never deletes lab files.
"""

from __future__ import annotations

from pathlib import Path
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request


LIB = Path(__file__).resolve().parent
ROOT = LIB.parent
VERSION_FILE = ROOT / "VERSION"
LABS_FILE = ROOT / "labs" / "approved_labs.json"
RELEASE_API = "https://api.github.com/repos/JxDog72/htb-helper-v2/releases/latest"
LABS_URL = "https://raw.githubusercontent.com/JxDog72/htb-helper-v2/main/labs/approved_labs.json"
RELEASES_PAGE = "https://github.com/JxDog72/htb-helper-v2/releases/latest"
CACHE_SECONDS = 6 * 60 * 60
NET_TIMEOUT = 3.0

SKIP_NETWORK = False

_lab_cache = {"data": None, "source": ""}


def _read_version_file():
    try:
        text = VERSION_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        text = ""
    text = text.lstrip("vV").strip()
    return text or "0.0.0"


APP_VERSION = _read_version_file()


def parse_version(value):
    """Turn v2.1.0 or 2.1 into a 3-tuple. Pre-release suffixes are ignored."""
    text = str(value or "").strip()
    if text[:1] in ("v", "V"):
        text = text[1:]
    text = text.split("-", 1)[0].split("+", 1)[0]
    parts = []
    for piece in text.split("."):
        digits = ""
        for ch in piece:
            if ch.isdigit():
                digits += ch
            else:
                break
        if digits == "" and not parts:
            continue
        parts.append(int(digits or "0"))
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def version_is_newer(remote, local):
    return parse_version(remote) > parse_version(local)


def _cache_file():
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        folder = Path(base) / "htb-helper"
    else:
        folder = Path.home() / ".cache" / "htb-helper"
    return folder / "update-check.json"


def _run_git(args):
    try:
        result = subprocess.run(
            ["git", "-C", str(ROOT), *args],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if result.returncode != 0:
        return ""
    return (result.stdout or "").strip()


def git_branch():
    if not (ROOT / ".git").exists():
        return ""
    branch = _run_git(["rev-parse", "--abbrev-ref", "HEAD"])
    if branch == "HEAD":
        return ""
    return branch


def git_short_hash():
    if not (ROOT / ".git").exists():
        return ""
    return _run_git(["rev-parse", "--short", "HEAD"])


def is_dev_checkout():
    branch = git_branch()
    return bool(branch) and branch != "main"


def has_tracked_changes():
    if not (ROOT / ".git").exists():
        return False
    text = _run_git(["status", "--porcelain", "--untracked-files=no"])
    return bool(text)


def _fetch_json(url):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "htb-helper",
            "Accept": "application/vnd.github+json",
        },
    )
    with urllib.request.urlopen(request, timeout=NET_TIMEOUT) as response:
        raw = response.read().decode("utf-8", errors="replace")
    return json.loads(raw)


def _load_release_cache():
    path = _cache_file()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    fetched = float(data.get("fetched_at") or 0)
    if time.time() - fetched > CACHE_SECONDS:
        return None
    if "tag" not in data:
        return None
    return data


def _save_release_cache(tag, body):
    path = _cache_file()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"fetched_at": time.time(), "tag": tag, "body": body}) + "\n",
            encoding="utf-8",
        )
    except OSError:
        return


def latest_release():
    """Return {tag, body, ok}. ok is False when the network check did not succeed."""
    if SKIP_NETWORK:
        return {"tag": "", "body": "", "ok": False, "reason": "skipped"}
    cached = _load_release_cache()
    if cached is not None:
        return {"tag": str(cached.get("tag") or ""), "body": str(cached.get("body") or ""), "ok": True, "reason": "cache"}
    try:
        payload = _fetch_json(RELEASE_API)
    except (OSError, urllib.error.URLError, json.JSONDecodeError, TimeoutError, ValueError):
        return {"tag": "", "body": "", "ok": False, "reason": "offline"}
    tag = str(payload.get("tag_name") or "")
    body = str(payload.get("body") or "")
    if not tag:
        return {"tag": "", "body": "", "ok": False, "reason": "empty"}
    _save_release_cache(tag, body)
    return {"tag": tag, "body": body, "ok": True, "reason": "network"}


def _note_lines(body):
    lines = []
    for line in str(body or "").splitlines():
        clean = line.strip()
        if not clean:
            continue
        lines.append(clean)
        if len(lines) >= 10:
            break
    return lines


def update_status():
    """Status for the terminal and the Status tab. Never raises."""
    version = APP_VERSION
    branch = git_branch()
    commit = git_short_hash()
    dev = is_dev_checkout()
    identity = f"{branch} @ {commit}" if branch and commit else (commit or branch or "unknown")
    info = {
        "version": version,
        "branch": branch,
        "commit": commit,
        "dev": dev,
        "update_available": False,
        "latest": "",
        "terminal_lines": [],
        "status_line": f"Version: v{version}",
        "detail_lines": [],
    }
    try:
        release = latest_release()
    except Exception:
        release = {"tag": "", "body": "", "ok": False}
    latest_tag = str(release.get("tag") or "")
    latest_num = latest_tag.lstrip("vV")
    if dev:
        dev_line = f"Dev build v{version} ({identity})"
        if release.get("ok") and latest_num:
            student_line = f"Latest student release: v{latest_num}"
            info["latest"] = latest_num
        elif SKIP_NETWORK:
            student_line = "Latest student release: (check skipped)"
        else:
            student_line = "Latest student release: (could not check)"
        info["terminal_lines"] = [dev_line, student_line]
        info["status_line"] = dev_line
        info["detail_lines"] = [student_line]
        return info

    info["status_line"] = f"Version: v{version}"
    if not release.get("ok"):
        if SKIP_NETWORK:
            info["detail_lines"] = ["Update check skipped."]
        else:
            info["detail_lines"] = ["Could not check for updates. Starting anyway."]
        info["terminal_lines"] = [info["status_line"], *info["detail_lines"]]
        return info

    info["latest"] = latest_num
    if not version_is_newer(latest_tag, version):
        info["status_line"] = f"Version: v{version} (latest)"
        info["terminal_lines"] = [info["status_line"]]
        return info

    info["update_available"] = True
    info["status_line"] = f"Update available: v{latest_num} (you have v{version})"
    lines = [
        f"HTB-Helper v{latest_num} is available (you have v{version}).",
    ]
    notes = _note_lines(release.get("body"))
    if notes:
        lines.append("What's new:")
        lines.extend(f"  - {note}" for note in notes)
    if (ROOT / ".git").exists():
        lines.append("To update, run:")
        lines.append(f'  git -C "{ROOT}" pull --ff-only')
        if has_tracked_changes():
            lines.append("You have local changes. Run git stash before pulling.")
            lines.append("That stash does not include machines/, notes, or config.json.")
    else:
        lines.append(
            "Download the latest release from "
            f"{RELEASES_PAGE}, or clone the repo for easy updates."
        )
    info["terminal_lines"] = lines
    info["detail_lines"] = lines[1:]
    return info


def print_release_status():
    try:
        info = update_status()
    except Exception:
        return
    lines = info.get("terminal_lines") or []
    if not lines:
        return
    print()
    for line in lines:
        print(line)
    print()


def _normalize_lab_name(value):
    text = str(value or "")
    text = re.sub(r"\([^)]*\)", " ", text)
    text = text.replace("_", " ").replace("-", " ")
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def _load_local_labs():
    try:
        data = json.loads(LABS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("labs"), list):
        return None
    return data


def load_lab_list():
    """Fetch the public list. Dev checkouts fall back to the file in this folder."""
    if _lab_cache["data"] is not None:
        return _lab_cache["data"], _lab_cache["source"]
    data = None
    source = ""
    if not SKIP_NETWORK:
        try:
            data = _fetch_json(LABS_URL)
            source = "main"
        except (OSError, urllib.error.URLError, json.JSONDecodeError, TimeoutError, ValueError):
            data = None
    if not isinstance(data, dict) or not isinstance(data.get("labs"), list):
        data = None
        source = ""
    if data is None and is_dev_checkout():
        local = _load_local_labs()
        if local is not None:
            data = local
            source = "dev-copy"
    if data is not None:
        _lab_cache["data"] = data
        _lab_cache["source"] = source
    return data, source


def configured_machine_name():
    path = LIB / "config.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    if not isinstance(data, dict):
        return ""
    name = str(data.get("machine_name") or "").strip()
    if name in ("", "MachineName"):
        return ""
    return name


def check_lab(name):
    """Match a lab name. Unreachable lists do not block work."""
    query = str(name or "").strip()
    unreachable = (
        "Couldn't reach the approved lab list. Check with the Team lead. "
        "You can still go on."
    )
    unknown = "Not sure this lab is approved. Check with the Team lead before you start."
    result = {
        "ok": False,
        "query": query,
        "status": "",
        "tone": "unsure",
        "headline": "CHECK WITH THE TEAM LEAD",
        "reachable": False,
        "message": unreachable if query else unknown,
        "last_checked": "",
        "source": "",
        "block": False,
    }
    if not query:
        result["message"] = "Type a lab name to check."
        return result
    data, source = load_lab_list()
    if not data:
        result["message"] = unreachable
        result["headline"] = f"{query} — CHECK WITH THE TEAM LEAD"
        return result
    result["reachable"] = True
    result["source"] = source
    result["last_checked"] = str(data.get("last_checked") or "")
    wanted = _normalize_lab_name(query)
    match = None
    for lab in data.get("labs") or []:
        if not isinstance(lab, dict):
            continue
        names = [lab.get("name")]
        aliases = lab.get("aliases") or []
        if isinstance(aliases, list):
            names.extend(aliases)
        if any(_normalize_lab_name(item) == wanted and wanted for item in names):
            match = lab
            break
    if match is None:
        result["ok"] = True
        result["status"] = "unknown"
        result["tone"] = "unsure"
        result["headline"] = f"{query} — CHECK WITH THE TEAM LEAD"
        result["message"] = unknown
        return result
    status = str(match.get("status") or "").strip().lower()
    posted = str(match.get("posted") or "").strip()
    checked = result["last_checked"] or "the last check"
    if status == "approved":
        message = f"Approved. No public writeup found as of {checked}."
    elif status == "rejected":
        if posted:
            message = (
                "Not approved. A public writeup or specific hints exist "
                f"(posted {posted}). Pick another lab."
            )
        else:
            message = "Not approved. A public writeup or specific hints exist. Pick another lab."
        result["block"] = True
    else:
        result["status"] = "pending"
        message = unknown
        status = "pending"
    if source == "dev-copy":
        message += " Lab list is the copy in this dev folder. Students read the list from main."
    label = str(match.get("name") or query)
    if status == "approved":
        tone, headline = "approved", f"{label} — APPROVED"
    elif status == "rejected":
        tone, headline = "rejected", f"{label} — NOT APPROVED"
    else:
        tone, headline = "unsure", f"{label} — CHECK WITH THE TEAM LEAD"
    result["ok"] = True
    result["status"] = status
    result["tone"] = tone
    result["headline"] = headline
    result["message"] = message
    result["name"] = label
    return result


def lab_names():
    data, source = load_lab_list()
    if not data:
        return {"ok": False, "names": [], "source": source, "last_checked": ""}
    names = []
    for lab in data.get("labs") or []:
        if isinstance(lab, dict) and lab.get("name"):
            names.append({
                "name": str(lab.get("name")),
                "status": str(lab.get("status") or ""),
            })
    return {
        "ok": True,
        "names": names,
        "source": source,
        "last_checked": str(data.get("last_checked") or ""),
    }


def session_header_extra():
    """Lines added to a new session log. Does not rewrite old logs."""
    branch = git_branch()
    commit = git_short_hash()
    if branch and commit:
        where = f"{branch} @ {commit}"
    elif commit:
        where = commit
    else:
        where = "no git"
    lines = [f"Helper: v{APP_VERSION} ({where})"]
    machine = configured_machine_name()
    if machine:
        try:
            checked = check_lab(machine)
            lines.append(f"Lab check ({machine}): {checked.get('message')}")
        except Exception:
            lines.append(
                f"Lab check ({machine}): Couldn't reach the approved lab list. "
                "Check with the Team lead. You can still go on."
            )
    return "\n".join(lines) + "\n"
