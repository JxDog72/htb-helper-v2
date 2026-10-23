# Changelog

## 2.1.0

- One version number. Older session logs may say GUI `2.0.0` or CLI `3.4.0`. Those files are left as they were. New session logs record `v2.1.0` and the short commit hash.
- `main` checks GitHub for a newer release and prints `git pull --ff-only` when one exists. A `dev` checkout shows `Dev build` and the latest student release, and does not ask you to update.
- Check Lab is green when the open lab is approved, red when it is not approved, and orange when the name is not on the list. Orange says to reach out to the Team Lead. Acknowledge and continue still opens the lab. The header beside Session matches the open lab. The approved list shows AI, ICS, or General, and the difficulty. If the list cannot be downloaded, work can still continue. Lab folders are not deleted.
- Student update steps are in `htb-update10-22.md`. A lab check request is a pull request that adds one line to `labs/CHECK_REQUESTS.md`, with no link or hint.
- ZIP layout is unchanged: `studentID_machinename/` and `studentID_machinename_report/` side by side.
