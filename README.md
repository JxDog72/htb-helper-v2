# HTB Helper 4.0

Local field notebook for the HTB Enterprise research study.

It keeps the original helper’s job — session logs, captured tool output,
timestamped notes, evidence, screenshots, validation, ZIP backup — and
adds a **localhost GUI** so notes can be real Markdown (`##` headings,
lists, ` ```python ` fences) without fighting a numbered CLI prompt.

The GUI is **not a remote service**. Python serves a page on
`127.0.0.1` only. The terminal you started it from is still the place
you type HTB commands; `script` (Linux/Parrot) or a captured Windows
`cmd.exe` session records that work, including `ping` / `tracert` /
`ipconfig` output. Ctrl+C stops the current scan, not the logger.

Target lab OS: **Parrot OS** HTB VMs (also Kali/Debian). Windows lab VMs
are supported with the same GUI.

No pip packages. Python 3.9+ standard library only.

---

## Fresh Parrot (or Kali) VM

```bash
git clone https://github.com/JxDog72/HTB-Helper_V2.0.git
cd HTB-Helper_V2.0
chmod +x install.sh htb
./install.sh
./htb
```

`install.sh` detects Parrot/Kali/Debian and installs only helper
packages if they are missing (`python3`, `nmap`, `bsdutils` for
`script`, `xdg-utils`, `scrot`). It does **not** pull the whole
parrot-tools metapackage — the VM image already has gobuster/ffuf/nmap.

First launch opens `http://127.0.0.1:8765/`. Fill in student ID, machine
name, and target IP. After that, `./htb` also wraps **this** terminal in
a logged shell. Keep it open. Use the browser for notes.

```bash
chmod +x htb install.sh   # needed once if git lost the execute bit
./htb                     # GUI + logged shell
./htb --gui-only          # browser only, no logged shell
./htb --cli               # original numbered menu
./htb --check             # environment check
```

Do **not** use `sudo ./htb`. If you see `Permission denied`, run `chmod +x htb` or `bash ./htb`.

App source lives in `htb_app_lib/`. `README.md` stays in this directory.

Optional hotkey: Parrot keyboard settings → custom shortcut →
command `~/HTB-Helper_V2.0/htb` → `Ctrl+Alt+H`.

---

## What you get

Per machine, under `machines/<student>_<machine>/`:

```
logs/            session.log + captured tool output
screenshots/
notes/notes.md   one continuous Markdown file, timestamped entries
notes/evidence.md
notes/report_draft.md
metadata.json
research_manifest.json
```

GUI sections:

| Tab | Job |
|-----|-----|
| Notes | Full `.md` editor + live preview. Stamp `### [time] [CATEGORY]`. Quick-add supports headings, bullets, fenced code. |
| Logs | Tail `session.log` and other files in `logs/` |
| Tools | Numbered **categories** (Network, Web/Fuzzing, DNS/OSINT, SMB/AD, HTTP, Custom) with sub-tools |
| Tool Info | Cheat sheet: one-line description, syntax, flags, examples |
| Evidence / Files / Report / Status | Same study workflow as v3, plus ZIP + validate |

Notes auto-save. `Ctrl+S` save, `Ctrl+N` stamp, `Ctrl+1`–`8` tabs,
`Ctrl+Enter` appends the quick-add box.

---

## Windows HTB labs

```powershell
cd HTB-Helper_V2.0
.\install.ps1
.\htb.cmd
```

Session logging uses a captured `cmd.exe` session (not `Start-Transcript`,
which drops `ping.exe` / `ipconfig.exe` / `tracert.exe` output).
`install.ps1` adds a Start Menu shortcut with **Ctrl+Alt+H**.

---

## Original CLI

`htb_helper.py` is still the capture engine and the old menu:

```bash
python3 htb_app_lib/htb_helper.py
python3 htb_app_lib/htb_helper.py --check
```

---

## Important

Data-collection aid only. It does not exploit anything or decide what
to attack. Authorized HTB Enterprise targets only. Follow the research
team’s instructions. Keep failed attempts — they are study data.
