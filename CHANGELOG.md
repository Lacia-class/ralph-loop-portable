# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.0] - 2026-03-10

### Added
- `CONTRIBUTING.md` with development workflow and contribution guidelines
- `LICENSE` (MIT) for clear open-source licensing
- GitHub Issue & PR templates for structured community engagement
- `docs/architecture.md` covering system design and component overview
- `docs/troubleshooting.md` for common issues and solutions

### Changed
- Enhanced `README.md` with badges, clearer structure, and feature highlights
- Improved `.gitignore` with comprehensive Python/PowerShell exclusions

## [0.2.0] - 2026-02-08

### Added
- **Agent Team mode** (`rlteam-*` commands): lock-based multi-agent harness
  - Isolated workspace per agent
  - Git-backed task backlog with `current_tasks/*.lock` ownership
  - Commander / reviewer / worker role templates
  - Runtime staffing: `rlteam-add`, `rlteam-rm`, `rlteam-accounts`
  - Account failover enabled by default for long autonomous runs

### Improved
- **Reliability updates**:
  - Transient interruption auto-retry (`task interrupted`, network timeout/reset, 429/502/503)
  - Internal iteration exceptions auto-retry with bounded backoff
  - Repeated failures now pause loop and persist error fields (`last_error_kind`, `last_error_message`, `last_error_at`)
- **Quota failover matching** expanded:
  - `usage_limit_reached`
  - `You've hit your usage limit`
  - `usage limit has been reached`
- Portable sync strips Python cache artifacts (`__pycache__`, `*.pyc`)

## [0.1.0] - 2026-01-15

### Added
- Initial portable package with one-command install/uninstall
- `skills/ralph-loop/` skill (Python loop engine + SKILL.md)
- PowerShell profile shortcut block (`rl*` aliases)
- `codex-profiles/` multi-account management (`cdx`, `addcdx`)
- Cross-machine portability via `install.ps1` / `uninstall.ps1`
- `update-from-local.ps1` for bidirectional sync
