# Contributing to Ralph Loop Portable

Thank you for your interest in contributing! This guide will help you get started.

## Getting Started

### Prerequisites

- **Windows** with PowerShell 5.1+ or PowerShell 7+
- **Python 3.9+**
- **Git**
- **OpenAI Codex CLI** installed and authenticated (`codex --version`)

### Local Development Setup

1. Fork and clone the repository:

   ```powershell
   git clone https://github.com/<your-user>/ralph-loop-portable.git
   cd ralph-loop-portable
   ```

2. Install locally:

   ```powershell
   powershell -ExecutionPolicy Bypass -File .\install.ps1
   . $PROFILE
   ```

3. Verify installation:

   ```powershell
   rlstatus        # should show loop state
   cdx -List       # should list configured accounts
   ```

## Development Workflow

### Making Changes

1. Create a feature branch:

   ```bash
   git checkout -b feat/your-feature-name
   ```

2. Edit the source files. Key directories:
   - `skills/ralph-loop/` — Core loop engine (`ralph_loop.py`) and skill definition (`SKILL.md`)
   - `skills/ralph-loop/scripts/agent_team/` — Agent team harness
   - `profile/` — PowerShell profile blocks (aliases, shortcuts)
   - `codex-profiles/` — Multi-account management scripts

3. Test your changes locally by reinstalling:

   ```powershell
   powershell -ExecutionPolicy Bypass -File .\install.ps1
   . $PROFILE
   ```

4. If you edited installed files directly (under `~\.codex\skills\` or `~\.codex-profiles\`), sync them back:

   ```powershell
   powershell -ExecutionPolicy Bypass -File .\update-from-local.ps1
   ```

### Commit Messages

We follow [Conventional Commits](https://www.conventionalcommits.org/):

- `feat:` — New features
- `fix:` — Bug fixes
- `docs:` — Documentation changes
- `chore:` — Maintenance tasks
- `refactor:` — Code restructuring without behavior change

Example:

```
feat(agent-team): add graceful shutdown on SIGINT
fix(loop): handle 429 rate-limit with exponential backoff
docs: update README with agent team quick start
```

### Pull Requests

1. Push your branch and open a PR against `main`.
2. Describe **what** changed and **why**.
3. Link related issues if applicable.
4. Ensure your changes don't break the install/uninstall cycle.

## Architecture Overview

See [docs/architecture.md](docs/architecture.md) for a detailed component map.

```
ralph-loop-portable/
├── skills/ralph-loop/          # Core skill
│   ├── ralph_loop.py           # Loop engine
│   ├── SKILL.md                # Skill definition
│   └── scripts/agent_team/     # Multi-agent harness
├── profile/                    # PowerShell aliases
├── codex-profiles/             # Multi-account management
├── install.ps1                 # One-command installer
├── uninstall.ps1               # Clean uninstaller
└── update-from-local.ps1       # Bidirectional sync
```

## Reporting Bugs

Please use the [Bug Report template](https://github.com/Lacia-class/ralph-loop-portable/issues/new?template=bug_report.md) and include:

- Your OS version and PowerShell version
- Codex CLI version (`codex --version`)
- Steps to reproduce
- Expected vs actual behavior
- Relevant log output

## Feature Requests

We welcome feature requests! Please use the [Feature Request template](https://github.com/Lacia-class/ralph-loop-portable/issues/new?template=feature_request.md).

## Code of Conduct

Be respectful and constructive. We're building tools to help developers be more productive — let's keep the community welcoming for everyone.

## License

By contributing, you agree that your contributions will be licensed under the [MIT License](LICENSE).
