# Troubleshooting

## Common Issues

### Installation

#### Profile not loading after install

**Symptom**: `rlstatus` or `cdx` commands not found after running `install.ps1`.

**Fix**: Source your profile manually:

```powershell
. $PROFILE
```

If that doesn't work, check which profile file exists:

```powershell
Test-Path "$env:USERPROFILE\Documents\WindowsPowerShell\Microsoft.PowerShell_profile.ps1"
Test-Path "$env:USERPROFILE\Documents\PowerShell\Microsoft.PowerShell_profile.ps1"
```

#### Execution policy blocks install

**Symptom**: `install.ps1 cannot be loaded because running scripts is disabled`

**Fix**:

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

### Ralph Loop

#### Loop exits silently

**Symptom**: The loop stops without error messages.

**Cause**: Transient API errors may not be caught by older versions.

**Fix**: Update to v0.2.0+ which includes auto-retry for:
- `task interrupted`
- Network timeout/reset
- HTTP 429/502/503 responses

#### Quota exhaustion stops the loop

**Symptom**: Loop pauses with `usage_limit_reached` or similar messages.

**Fix**: 
1. Ensure multiple accounts are configured: `cdx -List`
2. Verify failover is enabled (default in v0.2.0+)
3. Add more accounts if needed: `addcdx <account-name>`

#### State file corruption

**Symptom**: Loop fails to read state or behaves unexpectedly.

**Fix**: Check the state file for valid JSON:

```powershell
Get-Content "$env:USERPROFILE\.codex\skills\ralph-loop\state.json" | ConvertFrom-Json
```

If corrupted, back up and reset:

```powershell
Copy-Item state.json state.json.bak
Remove-Item state.json
```

### Agent Team

#### Workers not picking up tasks

**Symptom**: `rlteam-status` shows tasks in backlog but workers are idle.

**Fix**:
1. Check for stale lock files: `ls current_tasks/*.lock`
2. Remove locks from crashed workers manually
3. Verify worker accounts are authenticated: `cdx -List`

#### Commander can't scale team

**Symptom**: `add-worker` or `remove-agent` commands fail from commander prompt.

**Fix**: Ensure the harness script path and config path are correct:

```powershell
python "$env:USERPROFILE\.codex\skills\ralph-loop\scripts\agent_team\codex_agent_team.py" accounts --config "team_config.json"
```

#### Account failover not working

**Symptom**: Loop stops on quota instead of switching accounts.

**Fix**:
1. Ensure you started with failover enabled: `rlteam-start` (default) not `rlteam-start -NoAutoFailover`
2. Ensure at least 2 accounts are configured
3. Check that unfailed accounts have remaining quota

### Multi-Account (cdx)

#### `cdx` command not found

**Symptom**: `cdx` not recognized as a command.

**Fix**: Re-source your profile or re-run the codex-profiles installer:

```powershell
& "$env:USERPROFILE\.codex-profiles\install.ps1"
. $PROFILE
```

#### Account switch doesn't take effect

**Symptom**: After `cdx <account>`, Codex CLI still uses the previous account.

**Fix**: Open a new terminal tab/window after switching, or source the profile:

```powershell
. $PROFILE
```

## Getting Help

If your issue isn't covered here:

1. Check [existing issues](https://github.com/Lacia-class/ralph-loop-portable/issues)
2. Open a [new issue](https://github.com/Lacia-class/ralph-loop-portable/issues/new/choose) with the bug report template
3. Include your environment details, steps to reproduce, and relevant logs
