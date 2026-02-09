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

## 6. Agent Team mode (Codex-native)

This package now includes a lock-based multi-agent harness that mirrors the
"agent teams" workflow in Codex:
- isolated workspace per agent
- git-backed task backlog
- `current_tasks/*.lock` ownership protocol
- parallel long-running loops per account
- commander/reviewer/worker role templates

Quick start:

```powershell
. $PROFILE

rlteam-init `
  -ProjectPath "C:\path\to\repo" `
  -Accounts "mers,htoo,yiye,man,bal"

rlteam-start
rlteam-status
```

Useful commands:
- `rlteam-status`
- `rlteam-watch -Agent commander -Follow`
- `rlteam-watchall -Follow`
- `rlteam-pause` / `rlteam-resume`
- `rlteam-inject -Only commander "..."` (or broadcast to all by omitting `-Only`)
- `rlteam-accounts` (show free/assigned accounts)
- `rlteam-refresh` (refresh commander/worker prompts to latest templates)
- `rlteam-add -Role worker_general` (add worker during runtime)
- `rlteam-rm -Agent worker-1-xxx` (remove worker during runtime)
- `rlteam-task -Priority P0 -Title "..." -Acceptance "..."`
- `rlteam-stop`

Notes:
- `rlteam-start` now enables account failover by default for long autonomous runs.
- Disable failover only when needed: `rlteam-start -NoAutoFailover`.
- Commander can self-scale team from prompt using:
  - `python "{{HARNESS_SCRIPT}}" accounts --config "{{TEAM_ROOT}}\\team_config.json"`
  - `python "{{HARNESS_SCRIPT}}" add-worker --config "{{TEAM_ROOT}}\\team_config.json" --role worker_general`
  - `python "{{HARNESS_SCRIPT}}" remove-agent --config "{{TEAM_ROOT}}\\team_config.json" --agent "<worker-name>"`

Direct script path:
- `%USERPROFILE%\.codex\skills\ralph-loop\scripts\agent_team\codex_agent_team.py`

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
