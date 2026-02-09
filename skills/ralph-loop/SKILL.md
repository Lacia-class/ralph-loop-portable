---
name: ralph-loop
description: Run Codex in a Ralph-style iterative loop by repeatedly sending the same prompt back into the same Codex thread until completion criteria are met. Use when the user asks for ralph loop behavior, autonomous retry loops, continuous self-correction, overnight iterative coding, or keep-going-until-done automation with Codex.
---

# Ralph Loop

Use `scripts/ralph_loop.py` to loop `codex exec` and `codex exec resume` against the same thread.

## Commands

```powershell
python "$env:USERPROFILE\.codex\skills\ralph-loop\scripts\ralph_loop.py" start "your task prompt"
```

## PowerShell shortcuts (recommended)

If your PowerShell profile already defines these aliases/functions:

- `rla`: set account by `CODEX_HOME` (for example `rla man`)
- `rls`: start loop with watch mode (real-time highlighted output)
- `rlsraw`: start loop in original non-highlight mode
- `rlx`: run any subcommand (`status/pause/resume/inject/cancel`)
- `rlb`: run subcommand using `bal` account
- `rlwatch` / `rlw`: start loop with real-time colored output highlighting
- `rllog`: show current/latest task log for an account (`-Follow` to stream)
- `rlreson`: one-command startup preset for `C:\Users\walty\Desktop\reson` (llm-only + isolated state/log + auto failover)
- `rlproj`: generic one-command startup for any project path (same defaults as long-run preset, and auto-follow log)
- `rls` / `rlsraw` / `rlwatch`: auto failover is now enabled by default; use `-NoAutoFailover` to disable

Example with account + max iterations + completion promise:

```powershell
rls '按计划执行任务。如果达成任务条件，就在最后一行精确输出：<promise>任务完成</promise>' -a man -MaxIterations 50 --completion-promise '任务完成'
```

Intervene during loop:

```powershell
rlx status -a man
rlx pause -a man
rlx inject -a man '本轮只输出：注入成功。最后一行输出：<promise>任务完成</promise>'
rlx resume -a man
rlx cancel -a man
rllog -a man
rllog -a man -Follow
```

Real-time watch mode:

```powershell
rlwatch '每轮默认只输出：基础输出。除非出现 [OPERATOR OVERRIDE] 且其中明确要求，否则不要输出任何<promise>标签。' -a man -MaxIterations 100
```

Watch mode with step details:

```powershell
rlwatch '按计划执行任务。' -a man -ShowSteps --completion-promise 'DONE_123'
```

### Start loop

```powershell
python "$env:USERPROFILE\.codex\skills\ralph-loop\scripts\ralph_loop.py" start "Build REST API and output <promise>DONE</promise> when complete." --completion-promise "DONE" --max-iterations 30
```

### Background mode

```powershell
python "$env:USERPROFILE\.codex\skills\ralph-loop\scripts\ralph_loop.py" start "Build REST API" --max-iterations 30 --detach
```

### Pause / inject / resume

```powershell
python "$env:USERPROFILE\.codex\skills\ralph-loop\scripts\ralph_loop.py" pause
python "$env:USERPROFILE\.codex\skills\ralph-loop\scripts\ralph_loop.py" inject "This round only: fix tests first."
python "$env:USERPROFILE\.codex\skills\ralph-loop\scripts\ralph_loop.py" resume
```

### Status / cancel

```powershell
python "$env:USERPROFILE\.codex\skills\ralph-loop\scripts\ralph_loop.py" status
python "$env:USERPROFILE\.codex\skills\ralph-loop\scripts\ralph_loop.py" cancel
```

## Display modes

- `--display native`: default, reuse Codex human output formatting (closest to normal `codex exec` view).
- `--display json`: parse JSON events in the wrapper.
- `--show-steps`: force JSON parsing and print internal command/tool steps.
- `--llm-only`: only print assistant replies (suppress loop/status/step/banners).
- `--heartbeat-seconds`: emit periodic "still running" heartbeat when no new output appears (default `20`, `0` disables).
- `--prompt-file`: read prompt from UTF-8 file directly inside `ralph_loop.py` (recommended on Windows to avoid Chinese argument mojibake).
- default state file path follows `CODEX_HOME` (`$CODEX_HOME/ralph-loop.local.json`).

## Task logs

- Every `start` run now writes a task log by default (both normal mode and `--llm-only`).
- Default path format: next to state file, like `ralph-loop.local.20260207-235430.log`.
- Use `--log-file <path>` to set a custom log path.
- Use `--no-log` to disable logs for foreground runs.
- `--detach` requires logging (keep default or pass `--log-file`).

## Long-running task isolation (important)

- For long tasks, do not use the default shared state file.
- Use a dedicated `--state-file` and `--log-file` per task.
- If you see "Loop stopped because state file disappeared during iteration", the task state file was removed (usually by `cancel` from another terminal or a conflicting task using the same state file).

Example:

```powershell
$sf = "$env:USERPROFILE\.codex-yiye\ralph-reso.json"
$lf = "$env:USERPROFILE\.codex-yiye\ralph-reso.log"
rls 'your long task prompt' -a yiye -MaxIterations 100 --state-file $sf --log-file $lf
```

Then control the same task with the same state file:

```powershell
rlx status -a yiye --state-file $sf
rlx pause -a yiye --state-file $sf
rlx resume -a yiye --state-file $sf
rlx cancel -a yiye --state-file $sf
```

## Account failover on quota

- Use `--auto-account-failover` to enable automatic account switching when quota is exhausted.
- Use `--failover-account` to define account order (repeat or comma-separated).
- If account order is not provided, it auto-discovers existing local accounts (`~/.codex-profiles/profiles.json` + `~/.codex-*` dirs).
- On switch, loop retries the same iteration on the next account.
- On switch, thread id is reset (the next account starts a fresh Codex thread with the same loop prompt).
- Account switching rotates cyclically (not one pass only), so earlier accounts can be retried after quota recovers.
- Remaining-quota warnings (for example 25%/10%/5% left) do not trigger failover; only exhausted/insufficient quota errors do.
- When multiple loop tasks run at the same time, failover now prefers accounts not currently used by other active Ralph loops (based on active state files). If all are busy, it falls back to reuse a busy account so tasks can still progress.

Example:

```powershell
rls '按计划执行任务。完成时输出<promise>DONE</promise>' -a yiye -AutoFailover -FailoverAccount yiye,man,bal --completion-promise DONE
```

## Canonical reson startup

Use this as a stable template for your `reson` long-run loop (llm-only + isolated state/log + auto failover):

```powershell
cd C:\Users\walty\Desktop\reson

$sf = "$env:USERPROFILE\.codex-yiye\ralph-reson-dev.json"
$lf = "$env:USERPROFILE\.codex-yiye\ralph-reson-dev.log"

$prompt = @'
<your long prompt here>
'@

rlsraw $prompt -a yiye -MaxIterations 300 -AutoFailover --state-file $sf --log-file $lf --completion-promise LOOP_DONE --llm-only
```

Monitor/control the same task:

```powershell
rllog -a yiye -Follow
rlx status -a yiye --state-file $sf
rlx pause -a yiye --state-file $sf
rlx resume -a yiye --state-file $sf
rlx cancel -a yiye --state-file $sf
rllog -a yiye -StateFile $sf -Follow
rllog -a yiye -LogFile $lf -Follow
```

## Generic cross-project startup

Use this to avoid redesigning commands every time:

```powershell
rlproj "C:\path\to\repo" -PromptFile ".\loop_prompt.md" -a yiye -MaxIterations 300
```

Or inline prompt:

```powershell
rlproj "C:\path\to\repo" -Prompt "your long loop prompt here" -a yiye -MaxIterations 300
```

Defaults:

- `llm-only` enabled
- auto account failover enabled (cyclic rotation)
- isolated state/log under `~/.codex-<account>/ralph-<project>.json|.log`
- default `-PromptFile` is read as UTF-8
- starts detached and immediately follows the task log in real time

Useful options:

```powershell
rlproj "C:\path\to\repo" -PromptFile ".\loop_prompt.md" -a yiye -FailoverAccount yiye,man,bal
rlproj "C:\path\to\repo" -PromptFile ".\loop_prompt.md" -NoLlmOnly -NoAutoFailover
rlproj "C:\path\to\repo" -PromptFile ".\loop_prompt.md" -NoWatch
rlproj "C:\path\to\repo" -PromptFile ".\loop_prompt.md" -StateTag task-a
rlproj "C:\path\to\repo" -PromptFile ".\loop_prompt.md" -HeartbeatSeconds 5
rlproj "C:\path\to\repo" -PromptFile ".\loop_prompt.md" -NativeConsole
```

Notes:

- `-NativeConsole` now disables inline `rlproj` log watch by default (prevents duplicate output in two windows).
- If you want to monitor logs from the original window while using `-NativeConsole`, run `rllog -a <account> -LogFile <log> -Follow` manually.

If you run multiple tasks in the same repo at the same time, set a different `-StateTag` for each task so their state/log files do not collide.

## Codex Agent Team mode

This skill now includes a full lock-based multi-agent harness:
- script: `%USERPROFILE%\.codex\skills\ralph-loop\scripts\agent_team\codex_agent_team.py`
- templates: `%USERPROFILE%\.codex\skills\ralph-loop\templates\agent-team\`
- profile shortcuts:
  - `rlteam-init`
  - `rlteam-start`
  - `rlteam-status`
  - `rlteam-watch`
  - `rlteam-task`
  - `rlteam-stop`

Example:

```powershell
. $PROFILE

rlteam-init `
  -ProjectPath "C:\Users\walty\Desktop\reson" `
  -Accounts "mers,htoo,yiye,man,bal"

rlteam-start -MaxIterations 0
rlteam-status
rlteam-watch -Agent commander -Follow
rlteam-watchall -Follow
```

Team protocol files are initialized in repo:
- `AGENT_TEAM_PROTOCOL.md`
- `task_backlog/P0.md`, `task_backlog/P1.md`, `task_backlog/P2.md`
- `current_tasks/*.lock`
- `progress/*.md`

Team runtime control:

```powershell
rlteam-pause
rlteam-resume
rlteam-inject -Only commander "re-split P0 backlog into 30-minute tasks"
rlteam-inject "all workers: prioritize flaky test fixes this round"
```

Notes:
- `rlteam-start` enables account failover by default.
- Disable only if needed: `rlteam-start -NoAutoFailover`.
- Runtime staffing (while loop is running):
  - `rlteam-refresh` (for existing teams to load latest commander scaling instructions)
  - `rlteam-accounts`
  - `rlteam-add -Role worker_general`
  - `rlteam-rm -Agent worker-1-xxx`

Commander can also call from its own iteration:

```powershell
python "{{HARNESS_SCRIPT}}" accounts --config "{{TEAM_ROOT}}\team_config.json"
python "{{HARNESS_SCRIPT}}" add-worker --config "{{TEAM_ROOT}}\team_config.json" --role worker_general
python "{{HARNESS_SCRIPT}}" remove-agent --config "{{TEAM_ROOT}}\team_config.json" --agent "worker-1-xxx"
```

## Failure handling (important)

- Quota failover now also matches these messages:
  - `usage_limit_reached`
  - `You've hit your usage limit`
  - `usage limit has been reached`
- Transient failures are retried automatically with bounded backoff:
  - interrupted requests (`task interrupted`)
  - temporary network/service errors (`timeout`, `connection reset`, `429/502/503`, etc.)
- If repeated failures still happen, the loop is paused instead of silently disappearing.
- Check failure reason with:

```powershell
rlx status -a <account> --state-file <state_file>
```

Look for:

- `last_error_kind`
- `last_error_message`
- `last_error_at`

## Notes

- Use `--max-iterations` as safety guard.
- Completion promise matches text inside `<promise>...</promise>` and ignores whitespace differences (spaces/newlines).
- This is not the interactive TUI; control it via pause/inject/resume/cancel.
- `-MaxIterations 0` means unlimited iterations.
- If output text looks garbled on Windows terminals, set `RALPH_LOOP_ENCODING` explicitly (example: `$env:RALPH_LOOP_ENCODING='gbk'` or `'utf-8'`).
