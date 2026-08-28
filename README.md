Inspired by: https://github.com/tjoliveros25/htb-research-helper.git

# HTB Helper 2.0

Local field notebook for the HTB Enterprise research study.

It keeps the original helper’s job — session logs, captured tool output,
timestamped notes, evidence, screenshots, validation, ZIP backup — and
adds a **localhost GUI** so notes can be real Markdown (`##` headings,
lists, ` ```python `).

The GUI is **not a remote service**. Python serves a page on
`127.0.0.1` only. The terminal you started it from is still the place
you type HTB commands; `script` (Linux/Parrot) or a captured Windows
`cmd.exe` session records that work, including `ping` / `tracert` /
`ipconfig` output. Ctrl+C stops the current scan, not the logger.

Target lab OS: **Parrot OS** HTB VMs (also Kali/Debian). Windows lab VMs
are supported with the same GUI.

No pip packages. Python 3.9+ standard library only.

**License:** [MIT](LICENSE). MIT license
This is a study aid for **authorized HTB Enterprise labs only**. The
author is **not responsible** for damage, data loss, misuse, or attacks.
You are solely responsible for staying in scope and following HTB rules
and the law.

---

## Fresh Parrot (or Kali) VM

```bash
git clone https://github.com/JxDog72/htb-helper-v2.git
cd htb-helper-v2
chmod +x install.sh htb
./install.sh
./htb
```

`install.sh` detects Parrot/Kali/Debian and installs only helper
packages if they are missing (`python3`, `nmap`, `bsdutils` for
`script`, `xdg-utils`, `scrot`). It does **not** pull the whole
parrot-tools metapackage — the VM image already has gobuster/ffuf/nmap.

First launch opens `http://127.0.0.1:8765/`. Fill in HTB_ID, machine
name, and target IP. After that, `./htb` also wraps **this** terminal in
a logged shell. Keep it open. Use the browser for notes.

```bash
chmod +x htb install.sh   # needed once if git lost the execute bit
./htb                     # GUI + logged shell
./htb --gui-only          # browser only, no logged shell
./htb --cli               # numbered menu (option 14: view/change machine or start a new lab)
./htb --check             # environment check
```

Do **not** use `sudo ./htb`. If you see `Permission denied`, run `chmod +x htb` or `bash ./htb`.

App source lives in `htb_app_lib/`. `README.md` stays in this directory.

Optional hotkey: Parrot keyboard settings → custom shortcut →
command `~/htb-helper-v2/htb` → `Ctrl+Alt+H`.

---

## What you get

Per machine, under `machines/<student>_<machine>/`:

```
logs/              session.log + captured tool output
screenshots/
notes/             notes.md + evidence.md
report/            report.md + media/
files_given/       files the lab handed you
machine_json/      app-only (not in the ZIP)
```

The parent folder is still `student_machine`. ZIP/7z export is written **next to** `machines/` (not inside the lab folder) and contains `student_machine_logs/`, `_screenshots/`, `_notes/` (notes.md + evidence.md), `_report/`, `_files_given/`. `machine_json/` is omitted.

**Rename a machine:** the GUI label comes from
`machines/<folder>/machine_json/metadata.json` (`machine_name`), not from
the folder name alone. Stop `./htb`, edit that field (and
`research_manifest.json` if present), then start again and **Open
selected lab** on the folder that still has your `logs/`. Do not Create
a new workspace for the new name. CLI option **14** renames and moves
the folder so files stay with the lab.

GUI sections:

| Tab | Job |
|-----|-----|
| Notes | Full `.md` editor + live preview. `# Machine` title, `### Lab instructions`, `### Workflow`. Stamp `[HH:MM]` (category optional). |
| Logs | Optional live tail of `session.log`. **New terminal** opens another captured shell as `terminal2_session.log`. Header **Speed up** skips 2.5s polling. |
| Tools | Categories with sub-tools. **Send to terminal** types the command into the logged shell. **Run and capture** also appends to `session.log`. Custom: one Command box. |
| Tool Info | Cheat sheet with category tabs, CyberChef, official CVE links, ICS/Modbus |
| Evidence / Files / Report / Status | Evidence without hashes. Status: ZIP then SCP, or encrypted 7z then [wormhole.app](https://wormhole.app). |

Notes auto-save. `Ctrl+S` save, `Ctrl+N` stamp, `Ctrl+1`–`8` tabs,
`Ctrl+Enter` appends the quick-add box.

---

## Export off Pwnbox

**Status** tab → **Create ZIP**, or install 7z and **Create encrypted 7z** (password box). Archive lands next to `machines/`.

```bash
sudo apt install p7zip-full
```

### 1. Pwnbox → host (SCP)

Fill hostname and username from HTB **View instance details**. Path is filled after you create the archive. Run this **on the PC**, then type the instance password. No space after `host:`.

Command Prompt:

```text
scp USERNAME@htb-xxxxx.htb-cloud.com:/full/path/to/file.zip %USERPROFILE%\Downloads\
```

PowerShell:

```text
scp USERNAME@htb-xxxxx.htb-cloud.com:/full/path/to/file.zip $env:USERPROFILE\Downloads\
```

### 2. Encrypted 7z (not SCP)

Set a password in Status and click **Create encrypted 7z**. Then open
[wormhole.app](https://wormhole.app), upload the `.7z`, and share it for
**one download**. Do not use the SCP box for this path.

### 3. Personal VM

Shared folder or drag-and-drop instead of SCP.

---

## Windows HTB labs

```powershell
cd htb-helper-v2
.\install.ps1
.\htb.cmd
```

Session logging uses a captured `cmd.exe` session (not `Start-Transcript`,
which drops `ping.exe` / `ipconfig.exe` / `tracert.exe` output).
`install.ps1` adds a Start Menu shortcut with **Ctrl+Alt+H**.

---

## Original CLI

`htb_helper.py` is still the capture engine and the numbered menu:

```bash
./htb --cli
python3 htb_app_lib/htb_helper.py
python3 htb_app_lib/htb_helper.py --check
```

Menu **14** shows the current machine name and workspace, lets you rename
this lab (machine / IP / port), switch to an existing folder under
`machines/`, or start a **new** machine (new workspace; the old one stays).
Renaming only the `machines/` folder does not update the GUI until
`machine_json/metadata.json` is edited (or you use this menu).
While a logged session is active, workspace moves are blocked until you
exit the menu and run `./htb --cli` again.

---

## Updating without losing lab data

`machines/` (your notes, logs, evidence, report) and `htb_app_lib/config.json`
are **not** in git. Pulling will not delete them.

```bash
cd htb-helper-v2
# 1. Stop the helper: type exit in the logged terminal, then Ctrl+C
git stash          # only if git says you have local edits
git pull
./htb              # pick the same lab on the start screen
```

If `git pull` complains about local files, `git stash` then `git pull`
then `git stash pop`. Your lab folders stay on disk either way.

---

## License and disclaimer

MIT License — see [`LICENSE`](LICENSE).

HTB Helper is provided **as is**, with **no warranty**. The author
(JxDog72) is not liable for any claim, damage, data loss, or other
liability arising from use of the software. Use it only on systems you
are authorized to test (HTB Enterprise labs for this study). Misuse,
attacks, or out-of-scope scanning are your responsibility.

---

## Important

Data-collection aid only. It does not exploit anything or decide what
to attack. Authorized HTB Enterprise targets only. Follow the research
team’s instructions. Keep failed attempts — they are study data.
