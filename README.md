# Ralph Loop Portable

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![GitHub release](https://img.shields.io/github/v/release/Lacia-class/ralph-loop-portable)](https://github.com/Lacia-class/ralph-loop-portable/releases)
[![GitHub issues](https://img.shields.io/github/issues/Lacia-class/ralph-loop-portable)](https://github.com/Lacia-class/ralph-loop-portable/issues)

> Portable automation toolkit for OpenAI Codex CLI — resilient loop execution, multi-account management, and multi-agent team orchestration in one package.

## Features

- **🔁 Ralph Loop Engine** — Resilient, long-running task execution with auto-retry, quota failover, and persistent state tracking
- **👥 Agent Team Orchestration** — Lock-based multi-agent harness with commander/reviewer/worker roles, runtime scaling, and git-backed task backlog
- **🔄 Multi-Account Management** — Seamless account switching (`cdx`), profile isolation, and automatic quota failover
- **📦 One-Command Install** — Portable package with idempotent install/uninstall across machines
- **🛡️ Fault Tolerance** — Transient error auto-retry, bounded backoff, and structured error persistence

## Quick Start

### Prerequisites

- Windows with PowerShell 5.1+
- [OpenAI Codex CLI](https://github.com/openai/codex) installed (`codex --version`)
- Python 3.9+ (`python --version`)

### Install

```powershell
git clone https://github.com/Lacia-class/ralph-loop-portable.git
cd ralph-loop-portable
powershell -ExecutionPolicy Bypass -File .\install.ps1
. $PROFILE
```

This installs:
- Ralph Loop skill + aliases (`rl*`)
- Multi-account launcher (`cdx`, `addcdx`)
- `~\.codex-profiles` configuration

### Verify

```powershell
rlstatus          # Check loop state
cdx -List         # List configured accounts
rlteam-status     # Check agent team (if initialized)
```

## Usage

### Ralph Loop

The loop engine drives autonomous Codex CLI task execution with built-in resilience:

```powershell
rlstart           # Start the loop
rlstatus          # Check current state
rlpause           # Pause execution
rlresume          # Resume execution
rlstop            # Stop the loop
```

### Multi-Account Management

Switch between Codex CLI accounts seamlessly:

```powershell
cdx -List              # List all accounts
cdx <account-name>     # Switch to account
addcdx <account-name>  # Add new account
```

### Agent Team Mode

Orchestrate multiple Codex CLI instances in parallel:

```powershell
# Initialize a team
rlteam-init `
  -ProjectPath "C:\path\to\repo" `
  -Accounts "account1,account2,account3"

# Start the team
rlteam-start
rlteam-status

# Monitor
rlteam-watch -Agent commander -Follow
rlteam-watchall -Follow

# Control
rlteam-pause / rlteam-resume
rlteam-inject -Only commander "review all pending PRs"
rlteam-inject "focus on test coverage"    # broadcast to all

# Scale at runtime
rlteam-add -Role worker_general
rlteam-rm -Agent worker-1-xxx
rlteam-accounts                           # show free/assigned

# Stop
rlteam-stop
```

## Package Structure

```
ralph-loop-portable/
├── skills/ralph-loop/              # Core skill
│   ├── ralph_loop.py               # Loop engine
│   ├── SKILL.md                    # Skill definition
│   └── scripts/agent_team/         # Multi-agent harness
├── profile/                        # PowerShell aliases
│   └── ralph-loop.profile.ps1
├── codex-profiles/                 # Multi-account management
│   ├── profiles.json               # Account registry
│   ├── install.ps1                 # Profile installer
│   ├── codex-multi-account.profile.ps1
│   ├── QUICKSTART.md
│   └── README.md
├── docs/                           # Documentation
│   ├── architecture.md             # System design
│   └── troubleshooting.md          # Common issues
├── .github/                        # GitHub templates
│   ├── ISSUE_TEMPLATE/
│   └── pull_request_template.md
├── install.ps1                     # One-command installer
├── uninstall.ps1                   # Clean uninstaller
├── update-from-local.ps1           # Bidirectional sync
├── CHANGELOG.md                    # Version history
├── CONTRIBUTING.md                 # Contribution guide
└── LICENSE                         # MIT License
```

## Cross-Machine Portability

### Install on a new machine

```powershell
git clone https://github.com/Lacia-class/ralph-loop-portable.git
cd ralph-loop-portable
powershell -ExecutionPolicy Bypass -File .\install.ps1
. $PROFILE
```

### Sync local changes back to package

```powershell
powershell -ExecutionPolicy Bypass -File .\update-from-local.ps1
git add .
git commit -m "chore: sync local updates"
git push
```

### Uninstall

```powershell
powershell -ExecutionPolicy Bypass -File .\uninstall.ps1
```

## Reliability

Since v0.2.0, the loop engine includes production-grade fault tolerance:

| Error type | Handling |
|---|---|
| Transient interruption | Auto-retry (task interrupted, timeout, 429/502/503) |
| Internal exception | Retry with bounded exponential backoff |
| Quota exhaustion | Automatic account failover via `cdx` |
| Repeated failures | Pause loop + persist error fields in state |

Error state fields: `last_error_kind`, `last_error_message`, `last_error_at`

## Notes

- Profile injection is **idempotent** and marker-based — safe to re-run
- Existing `profiles.json` is preserved by default (use `-ForceProfilesJson` to overwrite)
- Agent team failover is enabled by default; disable with `rlteam-start -NoAutoFailover`
- `update-from-local.ps1` automatically strips `__pycache__` and `.pyc` files

## Documentation

- [Architecture](docs/architecture.md) — System design and component overview
- [Troubleshooting](docs/troubleshooting.md) — Common issues and solutions
- [Contributing](CONTRIBUTING.md) — Development workflow and guidelines
- [Changelog](CHANGELOG.md) — Version history

## ⚠️ Disclaimer / 免责声明

> **This project is for educational and learning purposes only.**
>
> **本项目仅供学习与研究用途，请勿用于任何商业或非法目的。**

This project is an **independent, community-built tool** and is **not affiliated with, endorsed by, or officially associated with OpenAI** in any way. "Codex" and "OpenAI" are trademarks of OpenAI, Inc.

- **For learning and research only.** This project is published solely for technical learning and research purposes. The author(s) do not encourage or endorse any use that violates third-party terms of service.
- **The author assumes no responsibility.** The author(s) shall not be held liable for any direct, indirect, incidental, or consequential damages, losses, account suspensions, API charges, or any other consequences arising from the use or misuse of this software.
- **Use at your own risk.** By using this software, you acknowledge that you bear full responsibility for your own actions, including compliance with all applicable laws, regulations, and platform policies.
- **API costs are your responsibility.** This toolkit automates interactions with the OpenAI Codex CLI. You are solely responsible for monitoring and managing your API usage and any associated charges.
- **No warranty.** This software is provided "as is", without warranty of any kind, express or implied. See the [LICENSE](LICENSE) for full terms.

> 使用本软件即表示您已阅读并同意以上声明。因使用本项目产生的一切后果（包括但不限于账号封禁、费用产生、数据丢失等）均由使用者自行承担，与项目作者无关。

## Contributing

Contributions are welcome! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## License

[MIT](LICENSE) © Lacia-class
