#!/usr/bin/env python3
"""Codex Agent Team harness.

This script implements a lock-based multi-agent workflow inspired by long-running
parallel agent teams:
- Multiple Codex accounts run in parallel on isolated working clones.
- Tasks are coordinated through git-tracked backlog + lock files.
- Agents run in autonomous loops through ralph_loop.py in detached mode.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import textwrap
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


TEAM_CONFIG_VERSION = 1
DEFAULT_TEAM_DIRNAME = ".codex-agent-team"
DEFAULT_BRANCH_FALLBACK = "master"
AGENT_NAME_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")

WORKER_ROLE_CYCLE = ("worker_general", "worker_docs", "worker_quality")
ROLE_TEMPLATE_FILE = {
    "commander": "commander.md",
    "reviewer": "reviewer.md",
    "worker_general": "worker_general.md",
    "worker_docs": "worker_docs.md",
    "worker_quality": "worker_quality.md",
}


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def print_err(message: str) -> None:
    sys.stderr.write(f"{message}\n")
    sys.stderr.flush()


def slugify(value: str) -> str:
    out = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip())
    out = out.strip("-._")
    return out.lower() or "team"


def split_csv(raw: str) -> list[str]:
    parts: list[str] = []
    for chunk in raw.replace(";", ",").split(","):
        value = chunk.strip()
        if value:
            parts.extend([x for x in value.split() if x.strip()])
    dedup: list[str] = []
    seen: set[str] = set()
    for item in parts:
        key = item.strip()
        if not key:
            continue
        if key in seen:
            continue
        seen.add(key)
        dedup.append(key)
    return dedup


def unique_keep_order(items: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        value = item.strip()
        if not value:
            continue
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def account_home(account: str) -> Path:
    return Path.home() / f".codex-{account}"


def ensure_account_homes(accounts: list[str]) -> None:
    missing = [acc for acc in accounts if not account_home(acc).exists()]
    if missing:
        raise RuntimeError(
            "Missing CODEX_HOME for accounts: "
            + ", ".join(missing)
            + ". Create them first with cdx/addcdx."
        )


def discover_local_accounts() -> list[str]:
    discovered: list[str] = []
    profiles_json = Path.home() / ".codex-profiles" / "profiles.json"
    if profiles_json.exists():
        try:
            data = json.loads(read_text(profiles_json))
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict):
                        name = item.get("name")
                        if isinstance(name, str) and name.strip():
                            discovered.append(name.strip())
        except Exception:
            pass

    for item in Path.home().glob(".codex-*"):
        if not item.is_dir():
            continue
        name = item.name[len(".codex-") :]
        if name and name != "profiles":
            discovered.append(name)
    return unique_keep_order(discovered)


def run_cmd(
    cmd: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd is not None else None,
        env=env,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if check and result.returncode != 0:
        quoted = " ".join(cmd)
        detail = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"Command failed ({result.returncode}): {quoted}\n{detail}")
    return result


def ensure_git_repo(path: Path) -> None:
    if not (path / ".git").exists():
        raise RuntimeError(f"Not a git repository: {path}")


def git_current_branch(project_path: Path) -> str:
    result = run_cmd(["git", "-C", str(project_path), "rev-parse", "--abbrev-ref", "HEAD"], check=False)
    branch = result.stdout.strip()
    if result.returncode == 0 and branch and branch != "HEAD":
        return branch
    return DEFAULT_BRANCH_FALLBACK


def git_has_changes(repo: Path) -> bool:
    result = run_cmd(["git", "-C", str(repo), "status", "--porcelain"], check=True)
    return bool(result.stdout.strip())


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_text(path: Path, content: str) -> None:
    ensure_dir(path.parent)
    path.write_text(content, encoding="utf-8")


def write_if_missing(path: Path, content: str) -> None:
    if not path.exists():
        write_text(path, content)


def ensure_upstream_bare(project_path: Path, upstream_bare: Path) -> None:
    ensure_dir(upstream_bare.parent)
    if not upstream_bare.exists():
        run_cmd(["git", "clone", "--bare", str(project_path), str(upstream_bare)])
    run_cmd(["git", "-C", str(project_path), "push", "--mirror", str(upstream_bare)])


def ensure_workspace(workspace: Path, upstream_bare: Path, branch: str) -> None:
    if not (workspace / ".git").exists():
        ensure_dir(workspace.parent)
        run_cmd(["git", "clone", str(upstream_bare), str(workspace)])

    run_cmd(["git", "-C", str(workspace), "fetch", "origin", "--prune"])

    local_branch = run_cmd(
        ["git", "-C", str(workspace), "rev-parse", "--verify", branch],
        check=False,
    )
    if local_branch.returncode == 0:
        run_cmd(["git", "-C", str(workspace), "checkout", branch])
    else:
        checkout_track = run_cmd(
            ["git", "-C", str(workspace), "checkout", "-b", branch, f"origin/{branch}"],
            check=False,
        )
        if checkout_track.returncode != 0:
            run_cmd(["git", "-C", str(workspace), "checkout", "-B", branch])

    run_cmd(["git", "-C", str(workspace), "config", "pull.rebase", "true"])
    run_cmd(["git", "-C", str(workspace), "pull", "--rebase", "origin", branch], check=False)


def script_root() -> Path:
    # .../skills/ralph-loop/scripts/agent_team/codex_agent_team.py
    return Path(__file__).resolve().parents[2]


def ralph_loop_script() -> Path:
    installed = Path.home() / ".codex" / "skills" / "ralph-loop" / "scripts" / "ralph_loop.py"
    if installed.exists():
        return installed
    local = script_root() / "scripts" / "ralph_loop.py"
    if local.exists():
        return local
    return installed


def template_dir() -> Path:
    return script_root() / "templates" / "agent-team"


def render_template(raw: str, variables: dict[str, str]) -> str:
    out = raw
    for key, value in variables.items():
        out = out.replace(f"{{{{{key}}}}}", value)
    return out


@dataclass
class AgentSpec:
    name: str
    role: str
    account: str
    workspace: str
    prompt_file: str
    state_file: str
    log_file: str


def build_state_path(team_name: str, account: str, agent_name: str, suffix: str) -> str:
    home = account_home(account)
    slug = slugify(f"{team_name}-{agent_name}")
    return str(home / f"ralph-team-{slug}.{suffix}")


def make_agent_spec(
    *,
    team_name: str,
    team_root: Path,
    agent_name: str,
    role: str,
    account: str,
) -> AgentSpec:
    return AgentSpec(
        name=agent_name,
        role=role,
        account=account,
        workspace=str((team_root / "workspaces" / agent_name).resolve()),
        prompt_file=str((team_root / "prompts" / f"{agent_name}.md").resolve()),
        state_file=build_state_path(team_name, account, agent_name, "json"),
        log_file=build_state_path(team_name, account, agent_name, "log"),
    )


def agent_spec_from_dict(item: dict[str, Any]) -> AgentSpec:
    return AgentSpec(
        name=str(item["name"]),
        role=str(item["role"]),
        account=str(item["account"]),
        workspace=str(item["workspace"]),
        prompt_file=str(item["prompt_file"]),
        state_file=str(item["state_file"]),
        log_file=str(item["log_file"]),
    )


def build_agent_specs(
    *,
    team_name: str,
    team_root: Path,
    commander_account: str,
    reviewer_account: str,
    worker_accounts: list[str],
) -> list[AgentSpec]:
    specs: list[AgentSpec] = []
    specs.append(
        make_agent_spec(
            team_name=team_name,
            team_root=team_root,
            agent_name="commander",
            role="commander",
            account=commander_account,
        )
    )
    specs.append(
        make_agent_spec(
            team_name=team_name,
            team_root=team_root,
            agent_name="reviewer",
            role="reviewer",
            account=reviewer_account,
        )
    )

    for idx, account in enumerate(worker_accounts):
        role = WORKER_ROLE_CYCLE[idx % len(WORKER_ROLE_CYCLE)]
        specs.append(
            make_agent_spec(
                team_name=team_name,
                team_root=team_root,
                agent_name=f"worker-{idx + 1}-{account}",
                role=role,
                account=account,
            )
        )

    return specs


def ensure_prompt_files(
    agents: list[AgentSpec],
    *,
    project_path: Path,
    team_root: Path,
    branch: str,
    overwrite: bool,
) -> None:
    templates = template_dir()
    if not templates.exists():
        raise RuntimeError(f"Template directory not found: {templates}")

    harness_path = str(Path(__file__).resolve())
    for agent in agents:
        tpl_name = ROLE_TEMPLATE_FILE.get(agent.role)
        if tpl_name is None:
            raise RuntimeError(f"Unknown role template for role: {agent.role}")
        tpl_path = templates / tpl_name
        if not tpl_path.exists():
            raise RuntimeError(f"Missing role template: {tpl_path}")

        raw = read_text(tpl_path)
        rendered = render_template(
            raw,
            {
                "PROJECT_PATH": str(project_path),
                "TEAM_ROOT": str(team_root),
                "BRANCH_NAME": branch,
                "AGENT_NAME": agent.name,
                "ACCOUNT_NAME": agent.account,
                "HARNESS_SCRIPT": harness_path,
            },
        ).rstrip() + "\n"

        prompt_path = Path(agent.prompt_file)
        if overwrite or not prompt_path.exists():
            write_text(prompt_path, rendered)


def seed_coordination_files(repo: Path, branch: str) -> None:
    protocol = textwrap.dedent(
        """
        # Agent Team Protocol

        This repository is running in autonomous multi-agent mode.

        ## Backlog format

        Use three files:
        - `task_backlog/P0.md`
        - `task_backlog/P1.md`
        - `task_backlog/P2.md`

        Task line format:
        - `[ ] TASK_ID | short title | owner:any | acceptance:<single sentence>`
        - `[x] TASK_ID | done by <agent> | commit:<hash>`

        ## Lock protocol

        All active tasks must have a lock file in `current_tasks/`:
        - `current_tasks/<TASK_ID>.lock`

        Lock content example:
        ```json
        {
          "task_id": "P0-101",
          "owner": "worker-1-foo",
          "account": "foo",
          "claimed_at": "2026-02-08T12:00:00Z"
        }
        ```

        Claim flow:
        1. `git pull --rebase origin __BRANCH__`
        2. ensure lock file is absent
        3. create lock file
        4. commit + push
        5. if push fails, resolve and choose another task

        Release flow:
        1. finish implementation + validation + push
        2. mark backlog item done
        3. delete lock file in a final coordination commit + push

        ## Reporting

        Each agent maintains:
        - `progress/<agent-name>.md`

        Keep reports concise and machine-greppable.
        Prefix important single-line diagnostics with:
        - `ERROR:`
        - `BLOCKER:`
        - `DONE:`
        """
    ).strip()
    protocol = protocol.replace("__BRANCH__", branch)

    write_if_missing(repo / "AGENT_TEAM_PROTOCOL.md", protocol + "\n")
    ensure_dir(repo / "current_tasks")
    write_if_missing(repo / "current_tasks" / ".gitkeep", "")
    ensure_dir(repo / "progress")
    write_if_missing(repo / "progress" / ".gitkeep", "")
    ensure_dir(repo / "task_backlog")
    write_if_missing(
        repo / "task_backlog" / "P0.md",
        "# P0 Backlog\n\n- [ ] P0-001 | bootstrap first executable milestone | owner:any | acceptance:first runnable end-to-end path works\n",
    )
    write_if_missing(
        repo / "task_backlog" / "P1.md",
        "# P1 Backlog\n\n",
    )
    write_if_missing(
        repo / "task_backlog" / "P2.md",
        "# P2 Backlog\n\n",
    )
    ensure_dir(repo / "agent_logs")
    write_if_missing(repo / "agent_logs" / ".gitkeep", "")

    if git_has_changes(repo):
        run_cmd(["git", "-C", str(repo), "add", "AGENT_TEAM_PROTOCOL.md", "current_tasks", "task_backlog", "progress", "agent_logs"])
        run_cmd(
            ["git", "-C", str(repo), "commit", "-m", "chore(agent-team): initialize lock protocol and backlog"],
            check=False,
        )
        run_cmd(["git", "-C", str(repo), "push", "origin", branch], check=False)


def load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise RuntimeError(f"Team config not found: {path}")
    raw = read_text(path)
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise RuntimeError(f"Invalid config object: {path}")
    return data


def save_config(path: Path, data: dict[str, Any]) -> None:
    write_text(path, json.dumps(data, ensure_ascii=True, indent=2) + "\n")


def find_agent(config: dict[str, Any], selector: str) -> dict[str, Any] | None:
    selector = selector.strip()
    if not selector:
        return None
    agents = config.get("agents", [])
    if not isinstance(agents, list):
        return None
    for item in agents:
        if not isinstance(item, dict):
            continue
        if item.get("name") == selector:
            return item
    for item in agents:
        if not isinstance(item, dict):
            continue
        if item.get("account") == selector:
            return item
    return None


def selected_agents(config: dict[str, Any], only_raw: str) -> list[dict[str, Any]]:
    agents = config.get("agents", [])
    if not isinstance(agents, list):
        raise RuntimeError("Invalid config: agents list missing")
    if not only_raw.strip():
        return [x for x in agents if isinstance(x, dict)]
    selectors = split_csv(only_raw)
    chosen: list[dict[str, Any]] = []
    seen: set[str] = set()
    for selector in selectors:
        item = find_agent(config, selector)
        if item is None:
            raise RuntimeError(f"Unknown agent selector: {selector}")
        name = str(item.get("name", ""))
        if name and name not in seen:
            seen.add(name)
            chosen.append(item)
    return chosen


def config_agents(config: dict[str, Any]) -> list[dict[str, Any]]:
    raw = config.get("agents", [])
    if not isinstance(raw, list):
        raise RuntimeError("Invalid config: agents list missing")
    return [item for item in raw if isinstance(item, dict)]


def account_pool(config: dict[str, Any]) -> list[str]:
    pool: list[str] = []
    raw = config.get("account_pool", [])
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, str) and item.strip():
                pool.append(item.strip())
    for agent in config_agents(config):
        account = agent.get("account")
        if isinstance(account, str) and account.strip():
            pool.append(account.strip())
    return unique_keep_order(pool)


def ensure_account_pool(config: dict[str, Any]) -> list[str]:
    pool = account_pool(config)
    if not pool:
        pool = discover_local_accounts()
    config["account_pool"] = unique_keep_order(pool)
    return list(config["account_pool"])


def validate_agent_name(name: str) -> None:
    if not name.strip():
        raise RuntimeError("Agent name cannot be empty.")
    if not AGENT_NAME_PATTERN.fullmatch(name.strip()):
        raise RuntimeError("Agent name must match [A-Za-z0-9._-]+")


def generate_worker_name(config: dict[str, Any], account: str) -> str:
    existing = {str(item.get("name", "")) for item in config_agents(config)}
    account_slug = slugify(account).replace(".", "-")
    if not account_slug:
        account_slug = "acct"
    idx = 1
    while True:
        candidate = f"worker-{idx}-{account_slug}"
        if candidate not in existing:
            return candidate
        idx += 1


def choose_account_for_new_worker(
    config: dict[str, Any],
    *,
    requested_account: str,
    allow_account_reuse: bool,
) -> str:
    pool = ensure_account_pool(config)
    used_accounts = {
        str(item.get("account", "")).strip()
        for item in config_agents(config)
        if isinstance(item.get("account"), str) and str(item.get("account", "")).strip()
    }

    if requested_account.strip():
        account = requested_account.strip()
        ensure_account_homes([account])
        if (not allow_account_reuse) and account in used_accounts:
            raise RuntimeError(
                f"Account '{account}' is already assigned. Use --allow-account-reuse to override."
            )
        if account not in pool:
            pool.append(account)
            config["account_pool"] = unique_keep_order(pool)
        return account

    unassigned = [acc for acc in pool if acc not in used_accounts]
    for account in unassigned:
        if account_home(account).exists():
            return account

    if allow_account_reuse:
        for account in pool:
            if account_home(account).exists():
                return account

    raise RuntimeError(
        "No free account available for new worker. "
        "Provide --account, remove existing worker, or use --allow-account-reuse."
    )


def state_active(state_file: Path) -> tuple[bool, int | None, bool | None]:
    if not state_file.exists():
        return False, None, None
    try:
        data = json.loads(read_text(state_file))
    except Exception:
        return False, None, None
    if not isinstance(data, dict):
        return False, None, None
    active = bool(data.get("active", False))
    iteration = data.get("iteration")
    paused = data.get("paused")
    return active, int(iteration) if isinstance(iteration, int) else None, bool(paused) if isinstance(paused, bool) else None


def run_ralph(
    account: str,
    cmd_args: list[str],
    *,
    cwd: Path,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    ralph = ralph_loop_script()
    if not ralph.exists():
        raise RuntimeError(f"ralph_loop.py not found: {ralph}")
    py_cmd = [sys.executable, "-u", str(ralph), *cmd_args]
    env = os.environ.copy()
    env["CODEX_HOME"] = str(account_home(account))
    return run_cmd(py_cmd, cwd=cwd, env=env, check=check)


def print_process_result(prefix: str, result: subprocess.CompletedProcess[str]) -> None:
    print(prefix)
    if result.stdout.strip():
        print(result.stdout.strip())
    if result.stderr.strip():
        print(result.stderr.strip())


def start_options_from_namespace(args: argparse.Namespace) -> dict[str, Any]:
    auto_failover_enabled = not bool(getattr(args, "no_auto_account_failover", False))
    if bool(getattr(args, "auto_account_failover", False)):
        auto_failover_enabled = True
    return {
        "max_iterations": int(getattr(args, "max_iterations", 0)),
        "display": str(getattr(args, "display", "native")),
        "heartbeat_seconds": int(getattr(args, "heartbeat_seconds", 20)),
        "llm_only": bool(getattr(args, "llm_only", False)),
        "detach_console": bool(getattr(args, "detach_console", False)),
        "model": str(getattr(args, "model", "")),
        "profile": str(getattr(args, "profile", "")),
        "sandbox": str(getattr(args, "sandbox", "")),
        "full_auto": bool(getattr(args, "full_auto", False)),
        "dangerous": bool(getattr(args, "dangerous", True)),
        "auto_account_failover": auto_failover_enabled,
        "failover_accounts": str(getattr(args, "failover_accounts", "")),
        "completion_promise": str(getattr(args, "completion_promise", "")),
    }


def start_one_agent(
    *,
    config: dict[str, Any],
    agent: dict[str, Any],
    options: dict[str, Any],
    restart: bool,
) -> None:
    branch = str(config.get("branch", DEFAULT_BRANCH_FALLBACK))
    upstream = Path(str(config["upstream_bare_repo"])).resolve()

    account = str(agent["account"])
    workspace = Path(str(agent["workspace"])).resolve()
    prompt_file = Path(str(agent["prompt_file"])).resolve()
    state_file = Path(str(agent["state_file"])).resolve()
    log_file = Path(str(agent["log_file"])).resolve()
    name = str(agent.get("name", account))

    ensure_workspace(workspace, upstream, branch)

    active, _, _ = state_active(state_file)
    if active and not restart:
        print(f"[skip] {name}: already active ({state_file})")
        return
    if active and restart:
        run_ralph(account, ["cancel", "--state-file", str(state_file)], cwd=workspace, check=False)

    ensure_dir(log_file.parent)
    ensure_dir(state_file.parent)

    cmd = [
        "start",
        "--prompt-file",
        str(prompt_file),
        "--max-iterations",
        str(int(options["max_iterations"])),
        "--state-file",
        str(state_file),
        "--log-file",
        str(log_file),
        "--display",
        str(options["display"]),
        "--heartbeat-seconds",
        str(int(options["heartbeat_seconds"])),
        "--detach",
    ]

    if bool(options["detach_console"]):
        cmd.append("--detach-console")
    if bool(options["llm_only"]):
        cmd.append("--llm-only")
    if str(options["model"]).strip():
        cmd.extend(["--model", str(options["model"]).strip()])
    if str(options["profile"]).strip():
        cmd.extend(["--profile", str(options["profile"]).strip()])
    if str(options["sandbox"]).strip():
        cmd.extend(["--sandbox", str(options["sandbox"]).strip()])
    if bool(options["full_auto"]):
        cmd.append("--full-auto")
    if bool(options["auto_account_failover"]):
        cmd.append("--auto-account-failover")
        for item in split_csv(str(options["failover_accounts"])):
            cmd.extend(["--failover-account", item])
    if str(options["completion_promise"]).strip():
        cmd.extend(["--completion-promise", str(options["completion_promise"]).strip()])
    if bool(options["dangerous"]):
        cmd.append("--dangerously-bypass-approvals-and-sandbox")

    result = run_ralph(account, cmd, cwd=workspace, check=True)
    print_process_result(f"[start] {name} ({account})", result)


def cmd_init(args: argparse.Namespace) -> int:
    project_path = Path(args.project_path).resolve()
    ensure_git_repo(project_path)

    branch = args.branch.strip() if args.branch else git_current_branch(project_path)
    team_name = slugify(args.team_name.strip() if args.team_name else project_path.name)
    team_root = Path(args.team_root).resolve() if args.team_root else (project_path / DEFAULT_TEAM_DIRNAME).resolve()
    ensure_dir(team_root)
    ensure_dir(team_root / "workspaces")
    ensure_dir(team_root / "prompts")

    accounts = split_csv(args.accounts)
    if len(accounts) < 1:
        raise RuntimeError("At least one account is required.")
    ensure_account_homes(accounts)

    commander_account = args.commander.strip() if args.commander else accounts[0]
    reviewer_account = args.reviewer.strip() if args.reviewer else (accounts[1] if len(accounts) > 1 else accounts[0])
    worker_accounts = split_csv(args.workers) if args.workers else [a for a in accounts if a not in {commander_account, reviewer_account}]
    if not worker_accounts:
        worker_accounts = list(accounts)

    used_accounts = [commander_account, reviewer_account, *worker_accounts]
    ensure_account_homes(list(dict.fromkeys(used_accounts)))

    upstream_bare = (team_root / "upstream.git").resolve()
    ensure_upstream_bare(project_path, upstream_bare)

    agents = build_agent_specs(
        team_name=team_name,
        team_root=team_root,
        commander_account=commander_account,
        reviewer_account=reviewer_account,
        worker_accounts=worker_accounts,
    )

    for item in agents:
        workspace = Path(item.workspace)
        ensure_workspace(workspace, upstream_bare, branch)
        run_cmd(["git", "-C", str(workspace), "config", "user.name", f"agent-{item.name}"])
        run_cmd(["git", "-C", str(workspace), "config", "user.email", f"{item.name}@local.invalid"])

    ensure_prompt_files(
        agents,
        project_path=project_path,
        team_root=team_root,
        branch=branch,
        overwrite=bool(args.overwrite_prompts),
    )

    commander_workspace = Path(agents[0].workspace)
    seed_coordination_files(commander_workspace, branch)

    config_path = (team_root / "team_config.json").resolve()
    config = {
        "config_version": TEAM_CONFIG_VERSION,
        "team_name": team_name,
        "project_path": str(project_path),
        "team_root": str(team_root),
        "branch": branch,
        "upstream_bare_repo": str(upstream_bare),
        "created_at": now_utc_iso(),
        "account_pool": unique_keep_order(accounts),
        "agents": [asdict(x) for x in agents],
        "runtime": {
            "last_start_at": None,
            "last_stop_at": None,
            "last_update_at": now_utc_iso(),
            "last_start_options": {
                "max_iterations": 0,
                "display": "native",
                "heartbeat_seconds": 20,
                "llm_only": False,
                "detach_console": False,
                "model": "",
                "profile": "",
                "sandbox": "",
                "full_auto": False,
                "dangerous": True,
                "auto_account_failover": True,
                "failover_accounts": "",
                "completion_promise": "",
            },
        },
    }
    save_config(config_path, config)

    print("Codex Agent Team initialized.")
    print(f"Config: {config_path}")
    print(f"Branch: {branch}")
    print(f"Commander: {commander_account}")
    print(f"Reviewer: {reviewer_account}")
    print(f"Workers: {', '.join(worker_accounts)}")
    print("")
    print("Next:")
    print(f'python "{Path(__file__).resolve()}" start --config "{config_path}" --max-iterations 0')
    return 0


def cmd_start(args: argparse.Namespace) -> int:
    config_path = Path(args.config).resolve()
    config = load_config(config_path)
    agents = selected_agents(config, args.only)
    options = start_options_from_namespace(args)

    for agent in agents:
        start_one_agent(config=config, agent=agent, options=options, restart=bool(args.restart))

    runtime = config.setdefault("runtime", {})
    if isinstance(runtime, dict):
        runtime["last_start_at"] = now_utc_iso()
        runtime["last_update_at"] = now_utc_iso()
        runtime["last_start_options"] = options
        save_config(config_path, config)
    return 0


def run_state_command(
    *,
    config_path: Path,
    only_raw: str,
    action: str,
    extra_args: list[str] | None = None,
) -> dict[str, Any]:
    config = load_config(config_path)
    agents = selected_agents(config, only_raw)
    payload = list(extra_args) if extra_args else []

    for agent in agents:
        account = str(agent["account"])
        workspace = Path(str(agent["workspace"])).resolve()
        state_file = Path(str(agent["state_file"])).resolve()
        name = str(agent.get("name", account))
        cmd = [action, "--state-file", str(state_file), *payload]
        result = run_ralph(account, cmd, cwd=workspace, check=False)
        print_process_result(f"[{action}] {name} ({account})", result)

    runtime = config.setdefault("runtime", {})
    if isinstance(runtime, dict):
        runtime["last_update_at"] = now_utc_iso()
        if action == "cancel":
            runtime["last_stop_at"] = now_utc_iso()
    save_config(config_path, config)
    return config


def cmd_stop(args: argparse.Namespace) -> int:
    config_path = Path(args.config).resolve()
    run_state_command(config_path=config_path, only_raw=args.only, action="cancel")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    config = load_config(Path(args.config).resolve())
    agents = selected_agents(config, args.only)
    pool = ensure_account_pool(config)
    assigned_all = {
        str(agent.get("account", "")).strip()
        for agent in config_agents(config)
        if isinstance(agent.get("account"), str) and str(agent.get("account", "")).strip()
    }
    free_all = [acc for acc in pool if acc not in assigned_all]

    print(f"Team: {config.get('team_name')}")
    print(f"Project: {config.get('project_path')}")
    print(f"Branch: {config.get('branch')}")
    print(f"Accounts total: {len(pool)} | assigned: {len(assigned_all)} | free: {len(free_all)}")
    if free_all:
        print(f"Free accounts: {', '.join(free_all)}")
    print("")

    for agent in agents:
        name = str(agent.get("name", "unknown"))
        account = str(agent.get("account", ""))
        state_file = Path(str(agent.get("state_file", "")))
        log_file = Path(str(agent.get("log_file", "")))
        workspace = str(agent.get("workspace", ""))
        active, iteration, paused = state_active(state_file)
        log_time = ""
        if log_file.exists():
            log_time = log_file.stat().st_mtime
            log_time = datetime.fromtimestamp(log_time).isoformat(timespec="seconds")
        print(f"[{name}] account={account} active={active} paused={paused} iteration={iteration}")
        print(f"  state: {state_file}")
        print(f"  log:   {log_file} ({log_time or 'missing'})")
        print(f"  repo:  {workspace}")

    commander = find_agent(config, "commander")
    if commander is not None:
        current_tasks = Path(str(commander["workspace"])) / "current_tasks"
        lock_files = sorted([x for x in current_tasks.glob("*.lock") if x.is_file()])
        print("")
        print(f"Locks: {len(lock_files)}")
        for item in lock_files:
            print(f"  - {item.name}")
    return 0


def tail_file(path: Path, lines: int, follow: bool) -> int:
    if not path.exists():
        raise RuntimeError(f"Log file not found: {path}")

    content = path.read_text(encoding="utf-8", errors="replace").splitlines()
    for line in content[-lines:]:
        print(line)

    if not follow:
        return 0

    with path.open("r", encoding="utf-8", errors="replace") as handle:
        handle.seek(0, os.SEEK_END)
        while True:
            line = handle.readline()
            if line:
                print(line.rstrip("\n"))
                continue
            time.sleep(0.4)


def cmd_watch(args: argparse.Namespace) -> int:
    config = load_config(Path(args.config).resolve())
    agent = find_agent(config, args.agent)
    if agent is None:
        raise RuntimeError(f"Unknown agent: {args.agent}")
    log_file = Path(str(agent["log_file"])).resolve()
    return tail_file(log_file, args.lines, args.follow)


def cmd_watch_all(args: argparse.Namespace) -> int:
    config = load_config(Path(args.config).resolve())
    agents = selected_agents(config, args.only)
    entries: list[tuple[str, Path]] = []
    for agent in agents:
        name = str(agent.get("name", "unknown"))
        log_file = Path(str(agent.get("log_file", ""))).resolve()
        entries.append((name, log_file))

    for name, path in entries:
        print(f"== {name} :: {path}")
        if path.exists():
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            for line in lines[-args.lines :]:
                print(f"[{name}] {line}")
        else:
            print(f"[{name}] (log file missing)")

    if not args.follow:
        return 0

    readers: dict[str, tuple[Path, Any]] = {}
    for name, path in entries:
        if not path.exists():
            ensure_dir(path.parent)
            write_text(path, "")
        handle = path.open("r", encoding="utf-8", errors="replace")
        handle.seek(0, os.SEEK_END)
        readers[name] = (path, handle)

    try:
        while True:
            had_output = False
            for name, (path, handle) in list(readers.items()):
                if not path.exists():
                    continue
                size = path.stat().st_size
                if size < handle.tell():
                    handle.close()
                    handle = path.open("r", encoding="utf-8", errors="replace")
                    readers[name] = (path, handle)
                while True:
                    line = handle.readline()
                    if not line:
                        break
                    had_output = True
                    print(f"[{name}] {line.rstrip()}")
            if not had_output:
                time.sleep(0.4)
    finally:
        for _, handle in readers.values():
            try:
                handle.close()
            except OSError:
                pass


def cmd_accounts(args: argparse.Namespace) -> int:
    config = load_config(Path(args.config).resolve())
    pool = ensure_account_pool(config)
    assigned = {
        str(agent.get("account", "")).strip()
        for agent in config_agents(config)
        if isinstance(agent.get("account"), str) and str(agent.get("account", "")).strip()
    }
    print("Accounts:")
    for account in pool:
        home = account_home(account)
        assigned_mark = "assigned" if account in assigned else "free"
        home_mark = "ok" if home.exists() else "missing-home"
        print(f"- {account} | {assigned_mark} | {home_mark} | {home}")
    return 0


def cmd_refresh_prompts(args: argparse.Namespace) -> int:
    config = load_config(Path(args.config).resolve())
    team_root = Path(str(config.get("team_root", ""))).resolve()
    project_path = Path(str(config.get("project_path", ""))).resolve()
    branch = str(config.get("branch", DEFAULT_BRANCH_FALLBACK))
    agents = selected_agents(config, args.only)
    specs = [agent_spec_from_dict(x) for x in agents]
    ensure_prompt_files(
        specs,
        project_path=project_path,
        team_root=team_root,
        branch=branch,
        overwrite=True,
    )
    print(f"Refreshed prompts: {len(specs)}")
    return 0


def cmd_add_worker(args: argparse.Namespace) -> int:
    config_path = Path(args.config).resolve()
    config = load_config(config_path)
    team_root_raw = config.get("team_root")
    project_path_raw = config.get("project_path")
    upstream_raw = config.get("upstream_bare_repo")
    if not isinstance(team_root_raw, str) or not team_root_raw.strip():
        raise RuntimeError("Invalid config: team_root missing")
    if not isinstance(project_path_raw, str) or not project_path_raw.strip():
        raise RuntimeError("Invalid config: project_path missing")
    if not isinstance(upstream_raw, str) or not upstream_raw.strip():
        raise RuntimeError("Invalid config: upstream_bare_repo missing")

    team_root = Path(team_root_raw).resolve()
    project_path = Path(project_path_raw).resolve()
    branch = str(config.get("branch", DEFAULT_BRANCH_FALLBACK))
    team_name = str(config.get("team_name", "team"))
    upstream = Path(upstream_raw).resolve()

    account = choose_account_for_new_worker(
        config,
        requested_account=str(args.account or ""),
        allow_account_reuse=bool(args.allow_account_reuse),
    )
    role = str(args.role)
    if role not in WORKER_ROLE_CYCLE:
        raise RuntimeError(f"Invalid worker role: {role}")

    name = str(args.name or "").strip()
    if not name:
        name = generate_worker_name(config, account)
    validate_agent_name(name)
    if find_agent(config, name) is not None:
        raise RuntimeError(f"Agent already exists: {name}")

    spec = make_agent_spec(
        team_name=team_name,
        team_root=team_root,
        agent_name=name,
        role=role,
        account=account,
    )

    ensure_workspace(Path(spec.workspace), upstream, branch)
    run_cmd(["git", "-C", str(spec.workspace), "config", "user.name", f"agent-{spec.name}"])
    run_cmd(["git", "-C", str(spec.workspace), "config", "user.email", f"{spec.name}@local.invalid"])

    ensure_prompt_files(
        [spec],
        project_path=project_path,
        team_root=team_root,
        branch=branch,
        overwrite=bool(args.overwrite_prompt),
    )

    agents = config_agents(config)
    agents.append(asdict(spec))
    config["agents"] = agents

    pool = ensure_account_pool(config)
    if account not in pool:
        pool.append(account)
        config["account_pool"] = unique_keep_order(pool)

    runtime = config.setdefault("runtime", {})
    if isinstance(runtime, dict):
        runtime["last_update_at"] = now_utc_iso()
    save_config(config_path, config)

    print(f"Added worker: {name}")
    print(f"Role: {role}")
    print(f"Account: {account}")
    print(f"Workspace: {spec.workspace}")

    if not args.no_start:
        options = start_options_from_namespace(args)
        start_one_agent(config=config, agent=asdict(spec), options=options, restart=False)
        runtime = config.setdefault("runtime", {})
        if isinstance(runtime, dict):
            runtime["last_start_options"] = options
            runtime["last_start_at"] = now_utc_iso()
            runtime["last_update_at"] = now_utc_iso()
        save_config(config_path, config)
    return 0


def cmd_remove_agent(args: argparse.Namespace) -> int:
    config_path = Path(args.config).resolve()
    config = load_config(config_path)
    selector = args.agent.strip()
    agents = config_agents(config)
    target = next((x for x in agents if str(x.get("name", "")) == selector), None)
    if target is None:
        matches = [x for x in agents if str(x.get("account", "")) == selector]
        if len(matches) > 1:
            names = ", ".join(str(x.get("name", "")) for x in matches)
            raise RuntimeError(
                f"Selector '{selector}' matches multiple agents by account: {names}. "
                "Use --agent with exact agent name."
            )
        target = matches[0] if matches else None
    if target is None:
        raise RuntimeError(f"Unknown agent: {args.agent}")

    role = str(target.get("role", ""))
    name = str(target.get("name", ""))
    account = str(target.get("account", ""))
    if role in {"commander", "reviewer"} and not args.force:
        raise RuntimeError(
            f"Refusing to remove {role} '{name}' without --force. "
            "Create a replacement first or pass --force explicitly."
        )

    workspace = Path(str(target["workspace"])).resolve()
    state_file = Path(str(target["state_file"])).resolve()
    result = run_ralph(
        account,
        ["cancel", "--state-file", str(state_file)],
        cwd=workspace,
        check=False,
    )
    print_process_result(f"[cancel] {name} ({account})", result)

    config["agents"] = [x for x in config_agents(config) if str(x.get("name", "")) != name]

    runtime = config.setdefault("runtime", {})
    if isinstance(runtime, dict):
        runtime["last_update_at"] = now_utc_iso()
    save_config(config_path, config)
    print(f"Removed agent from team config: {name}")
    return 0


def cmd_enqueue(args: argparse.Namespace) -> int:
    config = load_config(Path(args.config).resolve())
    branch = str(config.get("branch", DEFAULT_BRANCH_FALLBACK))
    commander = find_agent(config, "commander")
    if commander is None:
        raise RuntimeError("Commander agent not found in config.")

    workspace = Path(str(commander["workspace"])).resolve()
    task_file = workspace / "task_backlog" / f"{args.priority}.md"
    write_if_missing(task_file, f"# {args.priority} Backlog\n\n")

    task_id = args.task_id.strip() if args.task_id else f"{args.priority}-{int(time.time())}"
    line = f"- [ ] {task_id} | {args.title.strip()} | owner:any | acceptance:{args.acceptance.strip()}\n"

    run_cmd(["git", "-C", str(workspace), "pull", "--rebase", "origin", branch], check=False)
    with task_file.open("a", encoding="utf-8") as handle:
        if task_file.stat().st_size > 0:
            handle.write("\n")
        handle.write(line)

    run_cmd(["git", "-C", str(workspace), "add", str(task_file)])
    run_cmd(
        ["git", "-C", str(workspace), "commit", "-m", f"chore(tasks): enqueue {task_id}"],
        check=False,
    )
    if not args.no_push:
        run_cmd(["git", "-C", str(workspace), "push", "origin", branch], check=False)
    print(f"Enqueued task: {task_id}")
    print(f"File: {task_file}")
    return 0


def cmd_claim_lock(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).resolve()
    ensure_git_repo(workspace)
    task_id = args.task_id.strip()
    owner = args.owner.strip()
    branch = args.branch.strip()
    lock_file = workspace / "current_tasks" / f"{task_id}.lock"
    ensure_dir(lock_file.parent)

    run_cmd(["git", "-C", str(workspace), "pull", "--rebase", "origin", branch], check=False)
    if lock_file.exists():
        print(f"LOCKED: {task_id}")
        return 2

    payload = {
        "task_id": task_id,
        "owner": owner,
        "account": args.account.strip() if args.account else "",
        "claimed_at": now_utc_iso(),
    }
    write_text(lock_file, json.dumps(payload, ensure_ascii=True, indent=2) + "\n")
    run_cmd(["git", "-C", str(workspace), "add", str(lock_file)])
    run_cmd(
        ["git", "-C", str(workspace), "commit", "-m", f"lock(task): claim {task_id} by {owner}"],
        check=False,
    )
    pushed = run_cmd(["git", "-C", str(workspace), "push", "origin", branch], check=False)
    if pushed.returncode != 0:
        print("LOCK_PUSH_FAILED")
        print((pushed.stderr or pushed.stdout).strip())
        return 3
    print(f"LOCK_CLAIMED: {task_id}")
    return 0


def cmd_release_lock(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).resolve()
    ensure_git_repo(workspace)
    task_id = args.task_id.strip()
    owner = args.owner.strip()
    branch = args.branch.strip()
    lock_file = workspace / "current_tasks" / f"{task_id}.lock"

    run_cmd(["git", "-C", str(workspace), "pull", "--rebase", "origin", branch], check=False)
    if not lock_file.exists():
        print(f"LOCK_ABSENT: {task_id}")
        return 0

    lock_file.unlink(missing_ok=True)
    run_cmd(["git", "-C", str(workspace), "add", "-A", "current_tasks"])
    run_cmd(
        ["git", "-C", str(workspace), "commit", "-m", f"lock(task): release {task_id} by {owner}"],
        check=False,
    )
    run_cmd(["git", "-C", str(workspace), "push", "origin", branch], check=False)
    print(f"LOCK_RELEASED: {task_id}")
    return 0


def cmd_pause(args: argparse.Namespace) -> int:
    config_path = Path(args.config).resolve()
    run_state_command(config_path=config_path, only_raw=args.only, action="pause")
    return 0


def cmd_resume(args: argparse.Namespace) -> int:
    config_path = Path(args.config).resolve()
    run_state_command(config_path=config_path, only_raw=args.only, action="resume")
    return 0


def cmd_inject(args: argparse.Namespace) -> int:
    instruction = " ".join(args.instruction).strip()
    if not instruction:
        raise RuntimeError("Instruction cannot be empty.")

    config_path = Path(args.config).resolve()
    extra = []
    if args.prepend:
        extra.append("--prepend")
    extra.append(instruction)
    run_state_command(
        config_path=config_path,
        only_raw=args.only,
        action="inject",
        extra_args=extra,
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Codex Agent Team harness.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="Initialize team workspaces, prompts, and config.")
    p_init.add_argument("--project-path", required=True)
    p_init.add_argument("--accounts", required=True, help="Comma-separated account list.")
    p_init.add_argument("--commander", default="")
    p_init.add_argument("--reviewer", default="")
    p_init.add_argument("--workers", default="", help="Comma-separated worker accounts.")
    p_init.add_argument("--team-root", default="", help="Defaults to <project>/.codex-agent-team")
    p_init.add_argument("--team-name", default="")
    p_init.add_argument("--branch", default="")
    p_init.add_argument("--overwrite-prompts", action="store_true")
    p_init.set_defaults(handler=cmd_init)

    p_start = sub.add_parser("start", help="Start detached Ralph loops for all team agents.")
    p_start.add_argument("--config", required=True)
    p_start.add_argument("--only", default="", help="Comma-separated agent names/accounts.")
    p_start.add_argument("--max-iterations", type=int, default=0)
    p_start.add_argument("--display", choices=("native", "json"), default="native")
    p_start.add_argument("--heartbeat-seconds", type=int, default=20)
    p_start.add_argument("--llm-only", action="store_true")
    p_start.add_argument("--detach-console", action="store_true")
    p_start.add_argument("--model", default="")
    p_start.add_argument("--profile", default="")
    p_start.add_argument("--sandbox", choices=("read-only", "workspace-write", "danger-full-access"), default="")
    p_start.add_argument("--full-auto", action="store_true")
    p_start.add_argument("--dangerous", action="store_true", default=True)
    p_start.add_argument(
        "--no-auto-account-failover",
        action="store_true",
        help="Disable quota failover; enabled by default.",
    )
    p_start.add_argument("--auto-account-failover", action="store_true")
    p_start.add_argument("--failover-accounts", default="")
    p_start.add_argument("--completion-promise", default="")
    p_start.add_argument("--restart", action="store_true")
    p_start.set_defaults(handler=cmd_start)

    p_stop = sub.add_parser("stop", help="Stop team agents via ralph cancel.")
    p_stop.add_argument("--config", required=True)
    p_stop.add_argument("--only", default="")
    p_stop.set_defaults(handler=cmd_stop)

    p_status = sub.add_parser("status", help="Show status for all team agents.")
    p_status.add_argument("--config", required=True)
    p_status.add_argument("--only", default="")
    p_status.set_defaults(handler=cmd_status)

    p_watch = sub.add_parser("watch", help="Tail a specific agent log.")
    p_watch.add_argument("--config", required=True)
    p_watch.add_argument("--agent", required=True, help="Agent name or account.")
    p_watch.add_argument("--lines", type=int, default=120)
    p_watch.add_argument("--follow", action="store_true")
    p_watch.set_defaults(handler=cmd_watch)

    p_watch_all = sub.add_parser("watch-all", help="Tail logs for all selected agents.")
    p_watch_all.add_argument("--config", required=True)
    p_watch_all.add_argument("--only", default="", help="Comma-separated agent names/accounts.")
    p_watch_all.add_argument("--lines", type=int, default=60)
    p_watch_all.add_argument("--follow", action="store_true")
    p_watch_all.set_defaults(handler=cmd_watch_all)

    p_accounts = sub.add_parser("accounts", help="List account pool and assignment state.")
    p_accounts.add_argument("--config", required=True)
    p_accounts.set_defaults(handler=cmd_accounts)

    p_refresh = sub.add_parser("refresh-prompts", help="Regenerate prompt files from templates.")
    p_refresh.add_argument("--config", required=True)
    p_refresh.add_argument("--only", default="", help="Comma-separated agent names/accounts.")
    p_refresh.set_defaults(handler=cmd_refresh_prompts)

    p_add_worker = sub.add_parser("add-worker", help="Add one worker agent dynamically.")
    p_add_worker.add_argument("--config", required=True)
    p_add_worker.add_argument("--name", default="")
    p_add_worker.add_argument("--account", default="")
    p_add_worker.add_argument("--role", choices=WORKER_ROLE_CYCLE, default="worker_general")
    p_add_worker.add_argument("--allow-account-reuse", action="store_true")
    p_add_worker.add_argument("--overwrite-prompt", action="store_true")
    p_add_worker.add_argument("--no-start", action="store_true")
    p_add_worker.add_argument("--max-iterations", type=int, default=0)
    p_add_worker.add_argument("--display", choices=("native", "json"), default="native")
    p_add_worker.add_argument("--heartbeat-seconds", type=int, default=20)
    p_add_worker.add_argument("--llm-only", action="store_true")
    p_add_worker.add_argument("--detach-console", action="store_true")
    p_add_worker.add_argument("--model", default="")
    p_add_worker.add_argument("--profile", default="")
    p_add_worker.add_argument("--sandbox", choices=("read-only", "workspace-write", "danger-full-access"), default="")
    p_add_worker.add_argument("--full-auto", action="store_true")
    p_add_worker.add_argument("--dangerous", action="store_true", default=True)
    p_add_worker.add_argument("--no-auto-account-failover", action="store_true")
    p_add_worker.add_argument("--auto-account-failover", action="store_true")
    p_add_worker.add_argument("--failover-accounts", default="")
    p_add_worker.add_argument("--completion-promise", default="")
    p_add_worker.set_defaults(handler=cmd_add_worker)

    p_remove_agent = sub.add_parser("remove-agent", help="Remove one agent dynamically.")
    p_remove_agent.add_argument("--config", required=True)
    p_remove_agent.add_argument("--agent", required=True, help="Agent name or account.")
    p_remove_agent.add_argument("--force", action="store_true", help="Allow removing commander/reviewer.")
    p_remove_agent.set_defaults(handler=cmd_remove_agent)

    p_enqueue = sub.add_parser("enqueue", help="Append one task to backlog.")
    p_enqueue.add_argument("--config", required=True)
    p_enqueue.add_argument("--priority", choices=("P0", "P1", "P2"), required=True)
    p_enqueue.add_argument("--task-id", default="")
    p_enqueue.add_argument("--title", required=True)
    p_enqueue.add_argument("--acceptance", required=True)
    p_enqueue.add_argument("--no-push", action="store_true")
    p_enqueue.set_defaults(handler=cmd_enqueue)

    p_claim = sub.add_parser("claim-lock", help="Claim one task lock via git commit/push.")
    p_claim.add_argument("--workspace", required=True)
    p_claim.add_argument("--branch", default=DEFAULT_BRANCH_FALLBACK)
    p_claim.add_argument("--task-id", required=True)
    p_claim.add_argument("--owner", required=True)
    p_claim.add_argument("--account", default="")
    p_claim.set_defaults(handler=cmd_claim_lock)

    p_release = sub.add_parser("release-lock", help="Release one task lock via git commit/push.")
    p_release.add_argument("--workspace", required=True)
    p_release.add_argument("--branch", default=DEFAULT_BRANCH_FALLBACK)
    p_release.add_argument("--task-id", required=True)
    p_release.add_argument("--owner", required=True)
    p_release.set_defaults(handler=cmd_release_lock)

    p_pause = sub.add_parser("pause", help="Pause selected running agents.")
    p_pause.add_argument("--config", required=True)
    p_pause.add_argument("--only", default="")
    p_pause.set_defaults(handler=cmd_pause)

    p_resume = sub.add_parser("resume", help="Resume selected paused agents.")
    p_resume.add_argument("--config", required=True)
    p_resume.add_argument("--only", default="")
    p_resume.set_defaults(handler=cmd_resume)

    p_inject = sub.add_parser("inject", help="Inject one-shot instruction to selected agents.")
    p_inject.add_argument("--config", required=True)
    p_inject.add_argument("--only", default="")
    p_inject.add_argument("--prepend", action="store_true", help="Inject at queue front.")
    p_inject.add_argument("instruction", nargs="+")
    p_inject.set_defaults(handler=cmd_inject)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return int(args.handler(args))
    except KeyboardInterrupt:
        print_err("Interrupted.")
        return 130
    except RuntimeError as exc:
        print_err(f"Error: {exc}")
        return 1
    except Exception as exc:
        print_err(f"Unhandled error: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
