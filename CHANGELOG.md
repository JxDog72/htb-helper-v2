# Changelog

## 2.1.0

- One version number. Older session logs may say GUI `2.0.0` or CLI `3.4.0`. Those files are left as they were. New session logs record `v2.1.0` and the short commit hash.
- `main` checks GitHub for a newer release and prints `git pull --ff-only` when one exists. A `dev` checkout shows `Dev build` and the latest student release, and does not ask you to update.
- Status → Check lab reads `labs/approved_labs.json` from `main`. Unknown labs say to contact Tristan. If the list cannot be downloaded, contact Tristan or Jalen. Work can still continue. Lab folders are not deleted.
- ZIP layout is unchanged: `studentID_machinename/` and `studentID_machinename_report/` side by side.
