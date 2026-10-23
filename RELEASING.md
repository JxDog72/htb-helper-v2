# Releasing to students

Students only get `main`. Test on `dev` first. This does not delete `machines/`, notes, logs, or `config.json`.

On the Windows copy, the remote named `github` is `https://github.com/JxDog72/htb-helper-v2.git`. The remote named `origin` is a different fork. Push by that URL.

When the dev copy looks right:

```bash
git checkout main
git pull https://github.com/JxDog72/htb-helper-v2.git main
git merge dev
git tag -a v2.1.0 -m "v2.1.0"
git push https://github.com/JxDog72/htb-helper-v2.git main
git push https://github.com/JxDog72/htb-helper-v2.git v2.1.0
```

Then open GitHub → Releases → draft a release from that tag. Write a few plain lines about what changed. Those lines are what the update check shows students.

Bump the single `VERSION` file before the next tag. Add a section to `CHANGELOG.md`. Do not tag until the update check is already in that release, or students on the previous tag will not see the notice.

The morning lab check edits `labs/approved_labs.json` on `main` and opens a pull request when a lab should be marked not approved. Pull `main` before merging `dev`, so that file is not overwritten. Then run:

```bash
python labs/render_approved_labs.py
```
