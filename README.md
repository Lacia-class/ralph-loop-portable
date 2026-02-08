# Ralph Loop Portable

Portable package for your customized `ralph-loop + cdx multi-account` setup.

It includes:

- `skills/ralph-loop/` (`ralph_loop.py`, `SKILL.md`)
- PowerShell shortcut block (`profile/ralph-loop.profile.ps1`)
- `codex-profiles/` (`profiles.json`, `install.ps1`, docs, multi-account profile block)
- One-command install/uninstall scripts

## 1. Publish to GitHub

```powershell
cd C:\Users\walty\Desktop\Agent_team\ralph-loop-portable
git init
git add .
git commit -m "chore: add portable ralph-loop package"
git branch -M main
git remote add origin https://github.com/<your-user>/<your-repo>.git
git push -u origin main
```

## 2. Install on this machine

```powershell
cd C:\Users\walty\Desktop\Agent_team\ralph-loop-portable
powershell -ExecutionPolicy Bypass -File .\install.ps1
. $PROFILE
```

What this installs by default:

- Ralph loop skill + aliases (`rl*`)
- Multi-account launcher (`cdx`, `addcdx`)
- `~\.codex-profiles` files

If you only want multi-account restore from a backed-up `.codex-profiles` folder:

```powershell
& "$env:USERPROFILE\.codex-profiles\install.ps1"
. $PROFILE
```

## 3. Install on a new machine

Prerequisites:

- Codex CLI already installed and usable (`codex --version`)
- Python available (`python --version`)

Then:

```powershell
git clone https://github.com/<your-user>/<your-repo>.git
cd <your-repo>
powershell -ExecutionPolicy Bypass -File .\install.ps1
. $PROFILE
```

## 4. Update package after local changes

If you edit local files in:

- `%USERPROFILE%\.codex\skills\ralph-loop\`
- `%USERPROFILE%\.codex-profiles\`
- `%USERPROFILE%\Documents\WindowsPowerShell\Microsoft.PowerShell_profile.ps1`

run:

```powershell
cd C:\Users\walty\Desktop\Agent_team\ralph-loop-portable
powershell -ExecutionPolicy Bypass -File .\update-from-local.ps1
git add .
git commit -m "chore: sync local ralph-loop updates"
git push
```

## 5. Uninstall

```powershell
cd C:\Users\walty\Desktop\Agent_team\ralph-loop-portable
powershell -ExecutionPolicy Bypass -File .\uninstall.ps1
```

## Notes

- `install.ps1` updates both profile files if present:
  - `%USERPROFILE%\Documents\WindowsPowerShell\Microsoft.PowerShell_profile.ps1`
  - `%USERPROFILE%\Documents\PowerShell\Microsoft.PowerShell_profile.ps1`
- Profile injection is marker-based and idempotent:
  - `# >>> ralph-loop-portable >>>`
  - `# <<< ralph-loop-portable <<<`
  - `# >>> codex-profiles-portable >>>`
  - `# <<< codex-profiles-portable <<<`
- By default, existing `~\.codex-profiles\profiles.json` is preserved. Use `-ForceProfilesJson` to overwrite.
- Multi-account profile block intentionally does not override `cd`.
- Multi-account installer removes legacy tab-title block that overwrote `cd` (if present).
- List accounts with `cdx -List` (and `cdx list` compatibility is also supported).

## Reliability updates (2026-02-08)

- Added safer loop behavior to reduce silent exits:
  - transient interruption auto-retry (`task interrupted`, network timeout/reset, 429/502/503 text patterns)
  - internal iteration exceptions auto-retry with bounded backoff
  - repeated failures now pause loop and persist error fields in state (`last_error_kind`, `last_error_message`, `last_error_at`)
- Expanded quota failover matching:
  - now includes `usage_limit_reached`
  - now includes `You've hit your usage limit`
  - now includes `usage limit has been reached`
- Portable sync now strips Python cache artifacts when updating from local (`__pycache__`, `*.pyc`).
