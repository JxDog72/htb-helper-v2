# Update HTB Helper

Use the folder you already cloned. Stay on `main`. This update does not delete lab folders, notes, logs, or `config.json`.

Some folders are several commits behind. Some are already up to date and still need this version started again. One pull covers both.

## 1. Close it if it is open

Close HTB Helper before you update. Close the browser tab. Then stop the program.

If a terminal is running `./htb`, type `exit`, then press Ctrl+C in that same window.

`exit` closes the logged shell. Ctrl+C stops the helper.

If you started it by clicking the `htb` file and there is no terminal, open any terminal and run:

```bash
pkill -f htb_app.py
```

`pkill -f htb_app.py` stops a helper that was left running with no terminal.

## 2. Go to the helper folder

This is the folder that contains the `htb` file. If you cloned it in your home folder, run:

```bash
cd ~/htb-helper-v2
```

`cd ~/htb-helper-v2` moves the terminal into that folder. Use your real path if the folder lives somewhere else.

Check that you are in the right place:

```bash
git status
```

`git status` shows whether this folder is the helper and whether an update is waiting.

If it says `not a git repository`, you are in the folder above it. List what is here, then move into the inner folder:

```bash
ls
cd htb-helper-v2
```

`ls` prints the names in the current folder. `cd htb-helper-v2` moves into the inner folder. Then run `git status` again.

## 3. Update

Confirm this folder downloads from the class repository:

```bash
git remote -v
```

`git remote -v` prints the address this folder updates from. It should show `https://github.com/JxDog72/htb-helper-v2.git`.

See whether an update is waiting:

```bash
git status
```

`git status` may say the branch is behind by several commits and can be fast-forwarded. It may not. This is the first full release, so a folder can show no commits behind and still need the new version. Either message is fine. Run the pull next.

Download them:

```bash
git pull --ff-only
```

`git pull --ff-only` downloads every waiting update in one step. It does not mix in extra changes, and it leaves your lab folders alone.

Start the helper:

```bash
./htb
```

`./htb` starts HTB Helper on Linux.

On Windows, use the same `git` commands in the helper folder, then start it with:

```bat
htb.cmd
```

`htb.cmd` starts HTB Helper on Windows.

## 4. If the pull stops

Copy the full message and send it to the Team Lead. Leave the folder as it is.

## Ask for a lab to be checked

You can open a pull request when you want a lab name checked. The request is the lab name only.

Do not include a link, a hint, a flag, or a password. Do not merge the request. The Team Lead checks the lab and updates the list.

1. Open [labs/CHECK_REQUESTS.md](https://github.com/JxDog72/htb-helper-v2/blob/main/labs/CHECK_REQUESTS.md).
2. Click the pencil icon. That lets you edit the page.
3. GitHub will ask you to fork the repository. Accept that. A fork is your own copy where the edit can live.
4. Add one new line: `Your Lab Name — please check this lab.`
5. Click **Propose changes**, then **Create pull request**. That sends the lab name to the Team Lead.
6. Stop there. Do not click merge.

Sending the Team Lead the lab name is enough if you do not want to open a pull request.

## Troubleshooting: black screen

This is uncommon. It can happen if the terminal was closed while the page was still open, and the browser kept a bad copy of that page. The lab folder is still there.

Close that browser tab. Start the helper again with `./htb` (or `htb.cmd` on Windows) and open the page from the new terminal.

If the page is still black, hard-refresh that tab with Ctrl+Shift+R. That reloads the page without the saved copy. Clearing the browser cache for `127.0.0.1` does the same thing and is the larger step.
