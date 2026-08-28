# HTB Helper 2.0 — Quick start (Parrot VM)

## 1. Copy onto the box

```bash
git clone https://github.com/JxDog72/htb-helper-v2.git
cd htb-helper-v2
chmod +x install.sh htb
./install.sh
```

If `git` is not available, copy the folder onto the VM (USB, Python
http.server from another box, HTB file transfer, etc.).

## 2. Start

```bash
./htb
```

Browser: `http://127.0.0.1:8765/`

Fill in student ID, machine name, target IP (assigned port optional).

## 3. Confirm logging

In the **same terminal** that ran `./htb`, you should now have a logged
shell. Run:

```bash
whoami
pwd
```

Check **Logs** in the GUI — those lines should appear in `session.log`.

Renaming the folder under `machines/` does **not** change the name in the
GUI. Stop the helper, edit
`machines/<student>_<machine>/machine_json/metadata.json` and set
`"machine_name"`, optionally rename the folder to match, then `./htb`
and **Open selected lab**. Or use `./htb --cli` option **14**.

Do the rest of the lab in that terminal. Do not close it until you are
done for the session. If it dies, run `./htb` again; it creates
`session2.log`, `session3.log`, … and never overwrites.

## 4. Notes

Use the **Notes** tab. Markdown works (fences need a closing ` ``` `):

````markdown
Apache on 80

- directory listing on /backup
- login form on /admin

```python
print("FLAG")
```
````

`Ctrl+N` stamps `[HH:MM]`. Category chips default to None. Only the machine
title uses `#`; lab instructions and Workflow use `###`.

## 5. Tools

**Tools** tab is categorized (1 Network, 2 Web/Fuzzing, …). Each run
asks *why*, streams output, and writes a raw `.txt` under `logs/`.
Including that run in notes.md is a dropdown (default **No**). Copy the
`tee` line if you want the same save in your own terminal. Target IP and
port update that command as you type.

**Tool Info** is the cheat sheet (syntax + flags), grouped in tabs. It
does not run anything.

You can still type nmap/gobuster yourself in the logged terminal.

## 6. Finish and export

1. Evidence + screenshots for milestones
2. Status → **Create ZIP** (SCP) or encrypted 7z (wormhole.app, not SCP)
3. Copy the archive to your host using one of the three methods below
4. `exit` the logged shell
5. Keep the archive

### 1. Pwnbox → host (SCP)

Use **View instance details** on HTB: hostname, username, password.

1. On Pwnbox, Status fills **Path** after you create the ZIP (full path, e.g. `…/machines/jxdog72_htb-lab_4_….zip`). Use this SCP path for ZIP only.
2. On your **Windows PC** (not inside Pwnbox), run **one** of these. **No space after the colon.**

Command Prompt:

```text
scp USERNAME@htb-xxxxx.htb-cloud.com:/full/path/to/file.zip %USERPROFILE%\Downloads\
```

PowerShell:

```text
scp USERNAME@htb-xxxxx.htb-cloud.com:/full/path/to/file.zip $env:USERPROFILE\Downloads\
```

3. Enter the instance password when prompted.

`$HOME\Downloads` does **not** work in Command Prompt. A space after `host:` makes scp try to download `./` and fail with `not a regular file`.

### 2. Encrypted 7z (not SCP) — wormhole.app

This path is **not** SCP. Parrot may not include 7z until you install it:

```bash
sudo apt install p7zip-full
```

In **Status**: set a 7z password → **Create encrypted 7z**. The file is written **next to** `machines/` (not inside the lab folder). Header encryption (`-mhe=on`) hides filenames.

Then on Pwnbox open [https://wormhole.app](https://wormhole.app), upload that `.7z`, and share it for **one download** to your other machine. Do not use the SCP box for the 7z.

Manual equivalent:

```bash
7z a -t7z -mhe=on -p /path/to/student_machine_TIMESTAMP.7z student_machine/
```

### 3. Personal VM

Skip SCP. Use a VirtualBox/VMware **shared folder**, or drag the zip/7z onto your host desktop.

CLI equivalents still work:

```bash
./htb --check
./htb --cli
python3 htb_app_lib/htb_helper.py --validate
python3 htb_app_lib/htb_helper.py --stats
```

In `./htb --cli`, option **14** views/changes the machine name or starts a new lab.
