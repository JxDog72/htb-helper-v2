# HTB Helper 4.0 — Quick start (Parrot VM)

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
print("this is a real fence")
```
````

`Ctrl+N` stamps `[HH:MM]`. Category chips default to None. Only the machine
title uses `#`; lab instructions and Workflow use `###`.

## 5. Tools

**Tools** tab is categorized (1 Network, 2 Web/Fuzzing, …). Each run
asks *why*, streams output, and writes a raw `.txt` under
`<student>_<machine>_logs/`. Including that run in notes.md is a dropdown
(default **No**). Copy the `tee` line if you want the same save in your
own terminal.

**Tool Info** is the cheat sheet (syntax + flags), grouped in tabs. It
does not run anything.

You can still type nmap/gobuster yourself in the logged terminal.

## 6. Finish

1. Evidence + screenshots for milestones
2. Status → ZIP for host (download off Pwnbox)
3. Optional: `zip -e` then send via https://wormhole.app
4. `exit` the logged shell
5. Keep the ZIP

CLI equivalents still work:

```bash
./htb --check
python3 htb_helper.py --validate
python3 htb_helper.py --stats
```
