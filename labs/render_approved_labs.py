#!/usr/bin/env python3
"""Rewrite labs/APPROVED_LABS.md from labs/approved_labs.json.

The JSON is the source the helper and the morning check edit.
This script does not contact the network and does not delete lab folders.
"""

from pathlib import Path
import json
import sys


HERE = Path(__file__).resolve().parent
JSON_PATH = HERE / "approved_labs.json"
MD_PATH = HERE / "APPROVED_LABS.md"


def load():
    data = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    labs = [lab for lab in data.get("labs") or [] if isinstance(lab, dict)]
    return str(data.get("last_checked") or ""), labs


def table(labs, columns):
    header = "| " + " | ".join(columns) + " |"
    rule = "| " + " | ".join("---" for _ in columns) + " |"
    rows = [header, rule]
    for lab in labs:
        cells = [str(lab.get(key) or "").replace("|", "/") for key in columns]
        rows.append("| " + " | ".join(cells) + " |")
    return "\n".join(rows)


def render(checked, labs):
    groups = {"approved": [], "pending": [], "rejected": []}
    for lab in labs:
        status = str(lab.get("status") or "").lower()
        groups.get(status, groups["pending"]).append(lab)
    lines = [
        "# Approved labs",
        "",
        f"Last checked: {checked or 'unknown'}.",
        "",
        "Generated from `labs/approved_labs.json`. Edit the JSON, then run `python labs/render_approved_labs.py`.",
        "Do not put writeup URLs in either file.",
        "",
        "The helper ZIP opens as two folders: `studentID_machinename/` (logs, screenshots, notes, files_given) and `studentID_machinename_report/` beside it.",
        "",
        f"## Approved ({len(groups['approved'])})",
        "",
        table(groups["approved"], ["name", "type", "category", "difficulty", "field", "description"]),
        "",
        f"## Pending ({len(groups['pending'])})",
        "",
        "Pending and unknown labs: contact Tristan before starting.",
        "",
        table(groups["pending"], ["name", "type", "category", "difficulty", "field", "notes"]),
        "",
        f"## Not approved ({len(groups['rejected'])})",
        "",
        table(groups["rejected"], ["name", "posted", "notes"]),
        "",
    ]
    return "\n".join(lines)


def main():
    checked, labs = load()
    text = render(checked, labs)
    MD_PATH.write_text(text, encoding="utf-8")
    print(f"Wrote {MD_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
