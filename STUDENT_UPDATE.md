# Update HTB Helper

Use the folder you already cloned. Stay on `main`. This update does not delete lab folders, notes, logs, or `config.json`.

Being several commits behind is normal. One pull brings all of them.

## 1. Stop the helper

If a terminal is running `./htb`, type `exit`, then press Ctrl+C in that same window.

If you started it by clicking the `htb` file, open any terminal and run:

```bash
pkill -f htb_app.py
```

## 2. Go to the helper folder

This is the folder that contains the `htb` file.

```bash
cd ~/htb-helper-v2
```

If `git status` says `not a git repository`, you are in the folder above it. Run `ls`, then `cd` into the inner folder and try again.

## 3. Update

```bash
git remote -v
git status
git pull --ff-only
./htb
```

`git remote -v` should show `https://github.com/JxDog72/htb-helper-v2.git`.

`git status` may say the branch is behind by several commits and can be fast-forwarded. That is the message you want. `git pull --ff-only` downloads every one of those commits.

On Windows, use the same `git` commands in the helper folder, then start with `htb.cmd`.

## 4. If the pull stops

Copy the full message and send it to the Team Lead. Leave the folder as it is.

Do not run `git reset --hard`, `git clean`, or `git stash -u`.

## Ask for a lab to be checked

You can open a pull request when you want a lab name checked. The request is the lab name only.

Do not include a link, a hint, a flag, or a password. Do not merge the request. The Team Lead checks the lab and updates the list.

1. Open [labs/CHECK_REQUESTS.md](https://github.com/JxDog72/htb-helper-v2/blob/main/labs/CHECK_REQUESTS.md).
2. Click the pencil icon.
3. GitHub will ask you to fork the repository. Accept that.
4. Add one new line: `Your Lab Name — please check this lab.`
5. Click **Propose changes**, then **Create pull request**.
6. Stop there.

Sending the Team Lead the lab name is enough if you do not want to open a pull request.
