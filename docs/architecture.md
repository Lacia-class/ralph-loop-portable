# Architecture

## System Overview

Ralph Loop Portable is a modular automation toolkit for OpenAI Codex CLI that provides two core capabilities:

1. **Ralph Loop** — A resilient, long-running task execution loop
2. **Multi-Agent Team Orchestration** — Lock-based parallel agent coordination

```
┌─────────────────────────────────────────────────────────────┐
│                    Ralph Loop Portable                       │
├────────────────────┬────────────────────┬───────────────────┤
│   Ralph Loop       │   Agent Team       │   Multi-Account   │
│   Engine           │   Harness          │   Manager (cdx)   │
├────────────────────┼────────────────────┼───────────────────┤
│ • Task iteration   │ • Lock-based       │ • Profile switch  │
│ • Auto-retry       │   ownership        │ • Account listing │
│ • Quota failover   │ • Role templates   │ • Quota failover  │
│ • Error persist    │ • Runtime staffing │ • Tab isolation   │
│ • State tracking   │ • Git task backlog │ • Marker-based    │
└────────────────────┴────────────────────┴───────────────────┘
         ▲                    ▲                    ▲
         │                    │                    │
    ralph_loop.py    codex_agent_team.py    codex-profiles/
```

## Component Map

### 1. Ralph Loop Engine (`skills/ralph-loop/`)

The core loop engine that drives autonomous Codex CLI task execution.

**Key files:**
- `ralph_loop.py` — Main loop engine with state management
- `SKILL.md` — Skill definition and invocation protocol

**Features:**
- Persistent state tracking across iterations
- Transient error detection and auto-retry with backoff
- Quota exhaustion detection and multi-account failover
- Structured error persistence (`last_error_kind`, `last_error_message`, `last_error_at`)
- Graceful pause/resume on repeated failures

### 2. Agent Team Harness (`skills/ralph-loop/scripts/agent_team/`)

A lock-based multi-agent coordination system that enables parallel Codex CLI instances.

**Key file:**
- `codex_agent_team.py` — Team harness with CLI interface

**Architecture:**
```
Commander ──────────┐
                    │  git-backed task backlog
Reviewer ───────────┤  current_tasks/*.lock
                    │  isolated workspaces
Worker 1 ───────────┤
Worker 2 ───────────┤
Worker N ───────────┘
```

**Role templates:**
- **Commander** — Strategic task planning and delegation
- **Reviewer** — Code review and quality assurance
- **Worker** — Task execution and implementation

**Runtime operations:**
- Dynamic scaling: add/remove workers without restart
- Account failover: automatic rotation on quota exhaustion
- Task injection: broadcast or targeted command injection

### 3. Multi-Account Manager (`codex-profiles/`)

PowerShell-based account management for seamless profile switching.

**Key files:**
- `profiles.json` — Account configuration registry
- `install.ps1` — Profile installer with marker-based injection
- `codex-multi-account.profile.ps1` — Profile block with `cdx` / `addcdx` functions

**Design principles:**
- Marker-based profile injection (idempotent, safe re-runs)
- Legacy block cleanup (removes old tab-title overrides)
- Non-destructive: preserves existing `profiles.json` by default

### 4. Installer System (`install.ps1`, `uninstall.ps1`, `update-from-local.ps1`)

One-command lifecycle management.

**Install flow:**
1. Copy `skills/ralph-loop/` → `~\.codex\skills\ralph-loop\`
2. Copy `codex-profiles/` → `~\.codex-profiles\`
3. Inject profile blocks into PowerShell profile(s)
4. Source profile to activate aliases

**Update flow (bidirectional sync):**
1. Copy modified local files back to package directory
2. Strip cache artifacts (`__pycache__`, `*.pyc`)
3. Ready for git commit and push

## Data Flow

```
User Command (rl*, rlteam-*)
    │
    ▼
PowerShell Profile Aliases
    │
    ▼
ralph_loop.py / codex_agent_team.py
    │
    ├──▶ Codex CLI (API call)
    │        │
    │        ▼
    │    Task Result
    │        │
    │        ▼
    ├──▶ State Persistence (JSON)
    │
    ├──▶ Error Detection
    │        │
    │        ├──▶ Transient → Auto-retry (backoff)
    │        ├──▶ Quota → Account failover (cdx)
    │        └──▶ Repeated → Pause + persist error
    │
    └──▶ Next Iteration
```

## Design Decisions

1. **PowerShell-native**: All orchestration uses PowerShell for deep Windows integration and zero external dependencies beyond Python.

2. **Lock-file ownership**: Agent team uses filesystem locks rather than a central coordinator, enabling crash recovery and process isolation.

3. **Marker-based injection**: Profile modifications are wrapped in markers (`>>> ralph-loop-portable >>>` / `<<< ralph-loop-portable <<<`) enabling safe idempotent updates and clean removal.

4. **Bidirectional sync**: Users can edit installed files directly, then sync changes back to the portable package for version control.
