# HTB Helper 4.0 — Quick start (Parrot VM)

## 1. Copy onto the box

```bash
git clone https://github.com/JxDog72/htb-helper.git
cd htb-helper
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

Use the **Notes** tab. Markdown works:

```markdown
## Apache on 80

- directory listing on /backup
- login form on /admin

```python
print("this is a real fence")
```
```

Stamp a heading (`Ctrl+N`) whenever you change approach. Record dead
ends.

## 5. Tools

**Tools** tab is categorized (1 Network, 2 Web/Fuzzing, …). Each run
asks *why*, streams output, writes a raw file under `logs/`, and appends
a timeline note.

**Tool Info** is the cheat sheet (syntax + flags). It does not run
anything.

You can still type nmap/gobuster yourself in the logged terminal. That
is the source of truth for interactive work.

## 6. Finish

1. Evidence + screenshots for milestones
2. Status → Validate
3. Status → ZIP backup
4. `exit` the logged shell
5. Keep the ZIP

CLI equivalents still work:

```bash
./htb --check
python3 htb_helper.py --validate
python3 htb_helper.py --stats
```
