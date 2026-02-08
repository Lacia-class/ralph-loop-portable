#!/usr/bin/env python3
"""Run Codex in a Ralph-style iterative loop."""

from __future__ import annotations

import argparse
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


DEFAULT_CODEX_HOME = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
DEFAULT_STATE_FILE = str(DEFAULT_CODEX_HOME / "ralph-loop.local.json")
PROMISE_PATTERN = re.compile(r"<promise>(.*?)</promise>", flags=re.DOTALL)
NOISY_STDERR_PATTERN = re.compile(r"state db missing rollout path for thread", flags=re.IGNORECASE)
QUOTA_EXHAUSTED_PATTERN = re.compile(
    (
        r"(insufficient_quota|usage_limit_reached|exceeded your current quota|quota[^\\n]*exceeded|"
        r"billing hard limit|out of credits|credit balance is too low|"
        r"you've reached your usage limit|you've hit your usage limit|"
        r"usage limit exceeded|usage limit has been reached|"
        r"配额已用尽|额度已用尽|配额不足|额度不足|超出配额|达到配额上限)"
    ),
    flags=re.IGNORECASE,
)
INTERRUPTED_PATTERN = re.compile(
    (
        r"(task interrupted|interrupted\.|request cancelled|request canceled|"
        r"cancelled by user|canceled by user|操作已中断|任务已中断|已中断)"
    ),
    flags=re.IGNORECASE,
)
TRANSIENT_ERROR_PATTERN = re.compile(
    (
        r"(timeout|timed out|connection (reset|closed|aborted)|network error|"
        r"temporar(?:y|ily)|try again|service unavailable|bad gateway|gateway timeout|"
        r"internal server error|econnreset|etimedout|rate limit|429|503|502)"
    ),
    flags=re.IGNORECASE,
)
THREAD_ID_PATTERN = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
    flags=re.IGNORECASE,
)
ANSI_ESCAPE_PATTERN = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")
ACTIVE_LOG_HANDLE: Any | None = None
BUSY_STATE_MAX_AGE_SECONDS = 6 * 60 * 60


@dataclass
class IterationResult:
    thread_id: str | None
    last_agent_message: str
    return_code: int
    error_kind: str | None


@dataclass
class RuntimeOptions:
    model: str | None
    profile: str | None
    sandbox: str | None
    config: list[str]
    add_dir: list[str]
    full_auto: bool
    dangerously_bypass_approvals_and_sandbox: bool
    show_steps: bool
    display_mode: str
    llm_only: bool
    heartbeat_seconds: int


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def open_log(path: Path) -> None:
    global ACTIVE_LOG_HANDLE
    close_log()
    path.parent.mkdir(parents=True, exist_ok=True)
    ACTIVE_LOG_HANDLE = path.open("a", encoding="utf-8")


def close_log() -> None:
    global ACTIVE_LOG_HANDLE
    if ACTIVE_LOG_HANDLE is None:
        return
    try:
        ACTIVE_LOG_HANDLE.flush()
    except OSError:
        pass
    ACTIVE_LOG_HANDLE.close()
    ACTIVE_LOG_HANDLE = None


def write_log(text: str) -> None:
    if ACTIVE_LOG_HANDLE is None:
        return
    try:
        ACTIVE_LOG_HANDLE.write(text)
        ACTIVE_LOG_HANDLE.flush()
    except OSError:
        pass


def write_stream(stream: Any, text: str, *, also_log: bool = True) -> None:
    if also_log:
        write_log(text)
    try:
        stream.write(text)
    except UnicodeEncodeError:
        encoding = getattr(stream, "encoding", None) or "utf-8"
        if hasattr(stream, "buffer"):
            stream.buffer.write(text.encode(encoding, errors="replace"))
        else:
            safe_text = text.encode(encoding, errors="replace").decode(encoding, errors="replace")
            stream.write(safe_text)
    except OSError:
        # Stream may be detached/unavailable in background console variants.
        return
    try:
        stream.flush()
    except OSError:
        pass


def print_out(message: Any = "", *, end: str = "\n") -> None:
    write_stream(sys.stdout, f"{message}{end}")


def print_err(message: str) -> None:
    write_stream(sys.stderr, f"{message}\n")


def print_loop_info(options: RuntimeOptions, message: str) -> None:
    if options.llm_only:
        write_log(f"{message}\n")
        return
    print_out(message)


def hidden_popen_kwargs() -> dict[str, Any]:
    """Best-effort hidden-window subprocess settings on Windows."""
    if not sys.platform.startswith("win"):
        return {}
    kwargs: dict[str, Any] = {}
    create_no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if create_no_window:
        kwargs["creationflags"] = int(create_no_window)
    try:
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = getattr(subprocess, "SW_HIDE", 0)
        kwargs["startupinfo"] = startupinfo
    except Exception:
        # Keep running even if startupinfo is unavailable.
        pass
    return kwargs


def iter_output_lines_with_heartbeat(
    process: subprocess.Popen[str],
    heartbeat_seconds: int,
    on_heartbeat: Callable[[int], None],
):
    """Yield process stdout lines and emit periodic heartbeat when idle."""
    if process.stdout is None:
        raise RuntimeError("Failed to capture codex output stream.")
    if heartbeat_seconds <= 0:
        for line in process.stdout:
            yield line
        return

    line_queue: queue.Queue[str | object] = queue.Queue()
    sentinel = object()

    def reader() -> None:
        assert process.stdout is not None
        try:
            for line in process.stdout:
                line_queue.put(line)
        finally:
            line_queue.put(sentinel)

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    last_output_at = time.monotonic()

    while True:
        try:
            item = line_queue.get(timeout=float(heartbeat_seconds))
        except queue.Empty:
            idle_seconds = int(time.monotonic() - last_output_at)
            on_heartbeat(idle_seconds)
            continue
        if item is sentinel:
            break
        assert isinstance(item, str)
        last_output_at = time.monotonic()
        yield item


def get_stream_encoding() -> str:
    override = os.environ.get("RALPH_LOOP_ENCODING", "").strip()
    if override:
        return override
    return "utf-8"


def default_log_path_for_state(state_path: Path) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return state_path.with_name(f"{state_path.stem}.{timestamp}.log")


def classify_error_kind(lines: list[str]) -> str | None:
    tail = "\n".join(lines[-300:])
    if QUOTA_EXHAUSTED_PATTERN.search(tail):
        return "quota_exhausted"
    if INTERRUPTED_PATTERN.search(tail):
        return "interrupted"
    if TRANSIENT_ERROR_PATTERN.search(tail):
        return "transient_error"
    return None


def record_loop_error(
    state_path: Path,
    *,
    kind: str,
    message: str,
    pause: bool = True,
) -> None:
    try:
        state = load_state(state_path)
    except RuntimeError:
        return
    if state is None:
        return
    if pause:
        state["paused"] = True
        state["paused_at"] = now_utc_iso()
    state["last_error_kind"] = kind
    state["last_error_message"] = message
    state["last_error_at"] = now_utc_iso()
    state["updated_at"] = now_utc_iso()
    save_state(state_path, state)


def unique_keep_order(items: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        key = item.strip()
        if not key:
            continue
        if key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def load_profile_homes() -> dict[str, str]:
    path = Path.home() / ".codex-profiles" / "profiles.json"
    if not path.exists():
        return {}
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, list):
        return {}

    homes: dict[str, str] = {}
    for item in data:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        home = item.get("home")
        if not isinstance(name, str) or not name.strip():
            continue
        if not isinstance(home, str) or not home.strip():
            continue
        homes[name.strip()] = os.path.expandvars(home.strip())
    return homes


def discover_existing_accounts(profile_homes: dict[str, str]) -> list[str]:
    accounts = list(profile_homes.keys())
    home = Path.home()
    for path in home.glob(".codex-*"):
        if not path.is_dir():
            continue
        if path.name == ".codex-profiles":
            continue
        name = path.name[len(".codex-") :]
        if name and name != "profiles":
            accounts.append(name)
    return unique_keep_order(accounts)


def parse_iso_utc(value: str) -> datetime | None:
    raw = value.strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def extract_active_account_from_state(state: dict[str, Any], state_path: Path) -> str | None:
    raw = state.get("account_failover")
    if isinstance(raw, dict) and bool(raw.get("enabled", False)):
        accounts = raw.get("accounts")
        idx = raw.get("current_index")
        if isinstance(accounts, list) and isinstance(idx, int) and 0 <= idx < len(accounts):
            account = accounts[idx]
            if isinstance(account, str) and account.strip():
                return account.strip()

    parent = state_path.parent.name
    if parent.startswith(".codex-") and parent != ".codex-profiles":
        account = parent[len(".codex-") :]
        if account and account != "profiles":
            return account
    return None


def collect_busy_failover_accounts(exclude_state_path: Path) -> set[str]:
    busy: set[str] = set()
    home = Path.home()
    exclude_norm = os.path.normcase(str(exclude_state_path.resolve()))
    now = datetime.now(timezone.utc)

    for codex_home in home.glob(".codex-*"):
        if not codex_home.is_dir() or codex_home.name == ".codex-profiles":
            continue
        for state_path in codex_home.glob("ralph-*.json"):
            try:
                state_norm = os.path.normcase(str(state_path.resolve()))
            except OSError:
                continue
            if state_norm == exclude_norm:
                continue
            try:
                raw = state_path.read_text(encoding="utf-8")
                state = json.loads(raw)
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(state, dict) or not bool(state.get("active", False)):
                continue

            updated_at = state.get("updated_at")
            if isinstance(updated_at, str):
                parsed = parse_iso_utc(updated_at)
                if parsed is not None:
                    age = (now - parsed).total_seconds()
                    if age > BUSY_STATE_MAX_AGE_SECONDS:
                        continue

            account = extract_active_account_from_state(state, state_path)
            if account:
                busy.add(account)

    return busy


def infer_current_account(profile_homes: dict[str, str]) -> str | None:
    codex_home = os.environ.get("CODEX_HOME", "").strip()
    if codex_home:
        current_norm = os.path.normcase(os.path.abspath(codex_home))
        for name, home in profile_homes.items():
            if os.path.normcase(os.path.abspath(home)) == current_norm:
                return name
        base = Path(codex_home).name
        if base.startswith(".codex-") and len(base) > len(".codex-"):
            return base[len(".codex-") :]
    return None


def parse_failover_accounts(raw_values: list[str]) -> list[str]:
    out: list[str] = []
    for raw in raw_values:
        for part in raw.split(","):
            value = part.strip()
            if value:
                out.append(value)
    return unique_keep_order(out)


def get_account_home(account: str, homes: dict[str, str]) -> str:
    mapped = homes.get(account)
    if mapped:
        return os.path.expandvars(mapped)
    return str(Path.home() / f".codex-{account}")


def build_account_failover_state(args: argparse.Namespace) -> dict[str, Any] | None:
    manual_accounts = parse_failover_accounts(list(args.failover_account))
    enabled = bool(args.auto_account_failover or manual_accounts)
    if not enabled:
        return None

    profile_homes = load_profile_homes()
    accounts = manual_accounts if manual_accounts else discover_existing_accounts(profile_homes)
    current = infer_current_account(profile_homes)

    if current:
        if current in accounts:
            idx = accounts.index(current)
            accounts = accounts[idx:] + accounts[:idx]
        else:
            accounts = [current] + accounts

    accounts = unique_keep_order(accounts)
    if not accounts:
        raise RuntimeError(
            "Account failover enabled but no accounts found. "
            "Pass --failover-account or create ~/.codex-profiles/profiles.json."
        )

    account_homes = {name: get_account_home(name, profile_homes) for name in accounts}
    return {
        "enabled": True,
        "accounts": accounts,
        "account_homes": account_homes,
        "current_index": 0,
        "last_switched_at": None,
    }


def get_active_failover_account(state: dict[str, Any]) -> tuple[str, str] | None:
    raw = state.get("account_failover")
    if not isinstance(raw, dict) or not bool(raw.get("enabled", False)):
        return None

    accounts = raw.get("accounts")
    homes = raw.get("account_homes")
    idx = raw.get("current_index")
    if not isinstance(accounts, list) or not isinstance(homes, dict) or not isinstance(idx, int):
        return None
    if idx < 0 or idx >= len(accounts):
        return None

    account = accounts[idx]
    if not isinstance(account, str) or not account.strip():
        return None
    home = homes.get(account)
    if not isinstance(home, str) or not home.strip():
        home = str(Path.home() / f".codex-{account}")
    return account, os.path.expandvars(home)


def apply_active_failover_account(state: dict[str, Any]) -> bool:
    active = get_active_failover_account(state)
    if active is None:
        return True
    _, home = active
    if not Path(home).exists():
        return False
    os.environ["CODEX_HOME"] = home
    return True


def try_switch_failover_account(
    state: dict[str, Any],
    state_path: Path,
    options: RuntimeOptions,
    reason: str,
) -> bool:
    raw = state.get("account_failover")
    if not isinstance(raw, dict) or not bool(raw.get("enabled", False)):
        return False
    if reason != "quota_exhausted":
        return False

    accounts = raw.get("accounts")
    homes = raw.get("account_homes")
    idx = raw.get("current_index")
    if not isinstance(accounts, list) or not isinstance(homes, dict) or not isinstance(idx, int):
        return False
    count = len(accounts)
    if count <= 1:
        return False

    busy_accounts = collect_busy_failover_accounts(exclude_state_path=state_path)

    # First pass prefers accounts not currently used by another active task.
    # If all accounts are busy, fall back to a second pass that allows busy accounts.
    for allow_busy in (False, True):
        for step in range(1, count):
            next_idx = (idx + step) % count
            next_account = accounts[next_idx]
            if not isinstance(next_account, str) or not next_account.strip():
                continue

            if not allow_busy and next_account in busy_accounts:
                print_loop_info(
                    options,
                    f"[ralph-loop] Failover skipped account '{next_account}' (in use by another active task).",
                )
                continue

            next_home = homes.get(next_account)
            if not isinstance(next_home, str) or not next_home.strip():
                next_home = str(Path.home() / f".codex-{next_account}")
            next_home = os.path.expandvars(next_home)
            if not Path(next_home).exists():
                print_loop_info(
                    options,
                    f"[ralph-loop] Failover skipped account '{next_account}' (home missing: {next_home}).",
                )
                continue

            old_account = accounts[idx] if idx < len(accounts) and isinstance(accounts[idx], str) else "unknown"
            raw["current_index"] = next_idx
            raw["last_switched_at"] = now_utc_iso()
            state["account_failover"] = raw
            state["thread_id"] = None
            state["last_failover_from"] = old_account
            state["last_failover_to"] = next_account
            state["updated_at"] = now_utc_iso()
            save_state(state_path, state)
            os.environ["CODEX_HOME"] = next_home
            wrapped = next_idx <= idx
            wrapped_note = " (wrapped to start of account list)" if wrapped else ""
            if allow_busy and busy_accounts and next_account in busy_accounts:
                wrapped_note = f"{wrapped_note} (all accounts busy, reusing busy account)"
            print_loop_info(
                options,
                (
                    f"[ralph-loop] Quota exhausted on account '{old_account}'. "
                    f"Switched to '{next_account}' and retrying current iteration{wrapped_note}."
                ),
            )
            return True

    return False


def load_state(state_path: Path) -> dict[str, Any] | None:
    if not state_path.exists():
        return None
    try:
        raw = state_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"Failed to read state file '{state_path}': {exc}") from exc
    try:
        state = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"State file '{state_path}' is not valid JSON: {exc}") from exc
    if not isinstance(state, dict):
        raise RuntimeError(f"State file '{state_path}' must be a JSON object.")
    return state


def save_state(state_path: Path, state: dict[str, Any]) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = state_path.with_suffix(state_path.suffix + ".tmp")
    body = json.dumps(state, ensure_ascii=True, indent=2) + "\n"
    tmp_path.write_text(body, encoding="utf-8")
    tmp_path.replace(state_path)


def remove_state(state_path: Path) -> None:
    try:
        state_path.unlink(missing_ok=True)
    except OSError as exc:
        raise RuntimeError(f"Failed to remove state file '{state_path}': {exc}") from exc


def normalize_promise_text(value: str) -> str:
    # Ignore all whitespace so accidental line wraps or pasted newlines
    # do not prevent promise matching.
    return "".join(value.split())


def extract_promise_text(last_agent_message: str) -> str | None:
    match = PROMISE_PATTERN.search(last_agent_message)
    if not match:
        return None
    return normalize_promise_text(match.group(1))


def get_inject_queue(state: dict[str, Any]) -> list[str]:
    raw = state.get("inject_queue", [])
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, str) and item.strip()]


def compose_iteration_prompt(base_prompt: str, injection: str | None) -> str:
    if not injection:
        return base_prompt
    return (
        "[OPERATOR OVERRIDE]\n"
        "Apply this operator instruction for this iteration only.\n"
        "If it conflicts with the base prompt, prefer this override.\n"
        f"{injection}\n"
        "[/OPERATOR OVERRIDE]\n\n"
        "[BASE PROMPT]\n"
        f"{base_prompt}\n"
        "[/BASE PROMPT]"
    )


def resolve_codex_invocation() -> list[str] | None:
    """Resolve the safest way to invoke Codex CLI.

    On Windows, prefer `node .../codex.js` over `codex.cmd` so prompts containing
    CMD metacharacters (for example `<promise>...</promise>`) are not mangled by cmd.exe.
    """
    if sys.platform.startswith("win"):
        codex_cmd = shutil.which("codex.cmd")
        if codex_cmd:
            cmd_path = Path(codex_cmd)
            npm_bin_dir = cmd_path.parent
            codex_js = npm_bin_dir / "node_modules" / "@openai" / "codex" / "bin" / "codex.js"
            if codex_js.exists():
                node_in_bin = npm_bin_dir / "node.exe"
                if node_in_bin.exists():
                    return [str(node_in_bin), str(codex_js)]
                node_from_path = shutil.which("node")
                if node_from_path:
                    return [node_from_path, str(codex_js)]
            return [codex_cmd]

        codex_exe = shutil.which("codex.exe")
        if codex_exe:
            return [codex_exe]

        codex_plain = shutil.which("codex")
        if codex_plain:
            return [codex_plain]
        return None

    codex_plain = shutil.which("codex")
    if codex_plain:
        return [codex_plain]
    return None


def build_codex_command(
    options: RuntimeOptions,
    prompt: str,
    thread_id: str | None,
    codex_invocation: list[str],
    *,
    json_mode: bool,
    last_message_file: Path | None = None,
) -> list[str]:
    cmd = [*codex_invocation, "exec", "--skip-git-repo-check"]

    if json_mode:
        cmd.append("--json")
    if last_message_file is not None:
        cmd.extend(["--output-last-message", str(last_message_file)])

    if options.model:
        cmd.extend(["-m", options.model])
    if options.profile:
        cmd.extend(["-p", options.profile])
    if options.sandbox:
        cmd.extend(["-s", options.sandbox])
    if options.full_auto:
        cmd.append("--full-auto")
    if options.dangerously_bypass_approvals_and_sandbox:
        cmd.append("--dangerously-bypass-approvals-and-sandbox")

    for item in options.config:
        cmd.extend(["-c", item])
    for item in options.add_dir:
        cmd.extend(["--add-dir", item])

    if thread_id:
        cmd.append("resume")
        cmd.append(thread_id)

    cmd.append(prompt)
    return cmd


def run_iteration(
    options: RuntimeOptions,
    prompt: str,
    thread_id: str | None,
    codex_invocation: list[str],
    state_path: Path,
) -> IterationResult:
    if options.display_mode == "json" or options.show_steps:
        return run_iteration_json(options, prompt, thread_id, codex_invocation)
    return run_iteration_native(options, prompt, thread_id, codex_invocation, state_path)


def run_iteration_json(
    options: RuntimeOptions,
    prompt: str,
    thread_id: str | None,
    codex_invocation: list[str],
) -> IterationResult:
    stream_encoding = get_stream_encoding()
    cmd = build_codex_command(
        options,
        prompt,
        thread_id,
        codex_invocation,
        json_mode=True,
    )
    resolved_thread_id = thread_id
    last_agent_message = ""
    observed_lines: list[str] = []

    try:
        process = subprocess.Popen(
            cmd,
            text=True,
            encoding=stream_encoding,
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1,
            **hidden_popen_kwargs(),
        )
    except OSError as exc:
        raise RuntimeError(f"Failed to run codex command: {exc}") from exc

    heartbeat_seconds = options.heartbeat_seconds
    if heartbeat_seconds <= 0 and options.llm_only:
        heartbeat_seconds = 20

    for raw_line in iter_output_lines_with_heartbeat(
        process,
        heartbeat_seconds=heartbeat_seconds,
        on_heartbeat=lambda idle: print_loop_info(
            options,
            f"[ralph-loop] Iteration running... no new output for {idle}s.",
        ),
    ):
        write_log(raw_line)
        observed_lines.append(raw_line.rstrip("\n"))
        if len(observed_lines) > 500:
            observed_lines = observed_lines[-500:]
        line = raw_line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            if NOISY_STDERR_PATTERN.search(line):
                continue
            if not options.llm_only:
                print_err(line)
            continue

        event_type = event.get("type")
        if event_type == "thread.started":
            value = event.get("thread_id")
            if isinstance(value, str):
                resolved_thread_id = value
                if options.show_steps and not options.llm_only:
                    print_out(f"[step] thread: {value}")
            continue

        if event_type == "item.started":
            item = event.get("item")
            if isinstance(item, dict) and options.show_steps and not options.llm_only:
                item_type = item.get("type")
                if item_type == "command_execution":
                    command = item.get("command")
                    if isinstance(command, str) and command:
                        print_out(f"[step] run: {command}")
            continue

        if event_type == "item.completed":
            item = event.get("item")
            if not isinstance(item, dict):
                continue

            item_type = item.get("type")
            if item_type == "agent_message":
                value = item.get("text")
                if isinstance(value, str):
                    last_agent_message = value
                    if options.show_steps and not options.llm_only:
                        print_out(f"[assistant] {value}")
                continue

            if item_type == "command_execution" and options.show_steps and not options.llm_only:
                command = item.get("command")
                exit_code = item.get("exit_code")
                if isinstance(command, str) and command:
                    print_out(f"[step] done ({exit_code}): {command}")
                output = item.get("aggregated_output")
                if isinstance(output, str) and output.strip():
                    print_out(output.rstrip("\n"))
                continue

            if options.show_steps and not options.llm_only and item_type == "reasoning":
                print_out("[step] thinking")
                continue

            if options.show_steps and not options.llm_only and item_type == "tool_call":
                text = item.get("text")
                if isinstance(text, str) and text.strip():
                    print_out(f"[step] tool_call: {text.strip()}")
            continue

    return_code = process.wait()
    error_kind = classify_error_kind(observed_lines) if return_code != 0 else None

    if last_agent_message and (options.llm_only or not options.show_steps):
        print_out(last_agent_message)

    return IterationResult(
        thread_id=resolved_thread_id,
        last_agent_message=last_agent_message,
        return_code=return_code,
        error_kind=error_kind,
    )


def run_iteration_native(
    options: RuntimeOptions,
    prompt: str,
    thread_id: str | None,
    codex_invocation: list[str],
    state_path: Path,
) -> IterationResult:
    stream_encoding = get_stream_encoding()
    last_message_file = state_path.with_suffix(".last-message.txt")
    cmd = build_codex_command(
        options,
        prompt,
        thread_id,
        codex_invocation,
        json_mode=False,
        last_message_file=last_message_file,
    )
    resolved_thread_id = thread_id
    observed_lines: list[str] = []

    try:
        process = subprocess.Popen(
            cmd,
            text=True,
            encoding=stream_encoding,
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1,
            **hidden_popen_kwargs(),
        )
    except OSError as exc:
        raise RuntimeError(f"Failed to run codex command: {exc}") from exc

    heartbeat_seconds = options.heartbeat_seconds
    if heartbeat_seconds <= 0 and options.llm_only:
        heartbeat_seconds = 20

    for raw_line in iter_output_lines_with_heartbeat(
        process,
        heartbeat_seconds=heartbeat_seconds,
        on_heartbeat=lambda idle: print_loop_info(
            options,
            f"[ralph-loop] Iteration running... no new output for {idle}s.",
        ),
    ):
        write_log(raw_line)
        observed_lines.append(raw_line.rstrip("\n"))
        if len(observed_lines) > 500:
            observed_lines = observed_lines[-500:]
        if NOISY_STDERR_PATTERN.search(raw_line):
            continue

        if not options.llm_only:
            write_stream(sys.stdout, raw_line, also_log=False)

        plain = ANSI_ESCAPE_PATTERN.sub("", raw_line)
        plain_lower = plain.lower()
        if resolved_thread_id is None and (
            "codex session" in plain_lower or "session id:" in plain_lower
        ):
            match = THREAD_ID_PATTERN.search(plain)
            if match:
                resolved_thread_id = match.group(0)

    return_code = process.wait()
    error_kind = classify_error_kind(observed_lines) if return_code != 0 else None

    last_agent_message = ""
    if last_message_file.exists():
        try:
            last_agent_message = last_message_file.read_text(encoding="utf-8").strip()
        finally:
            last_message_file.unlink(missing_ok=True)

    if options.llm_only and last_agent_message:
        print_out(last_agent_message)

    return IterationResult(
        thread_id=resolved_thread_id,
        last_agent_message=last_agent_message,
        return_code=return_code,
        error_kind=error_kind,
    )


def validate_state(state: dict[str, Any], state_path: Path) -> tuple[int, int, str | None, str | None]:
    iteration = state.get("iteration")
    max_iterations = state.get("max_iterations")
    completion_promise = state.get("completion_promise")
    thread_id = state.get("thread_id")

    if not isinstance(iteration, int) or iteration < 1:
        raise RuntimeError(f"State file '{state_path}' has invalid 'iteration'.")
    if not isinstance(max_iterations, int) or max_iterations < 0:
        raise RuntimeError(f"State file '{state_path}' has invalid 'max_iterations'.")
    if completion_promise is not None and not isinstance(completion_promise, str):
        raise RuntimeError(f"State file '{state_path}' has invalid 'completion_promise'.")
    if thread_id is not None and not isinstance(thread_id, str):
        raise RuntimeError(f"State file '{state_path}' has invalid 'thread_id'.")

    return iteration, max_iterations, completion_promise, thread_id


def runtime_options_from_args(args: argparse.Namespace) -> RuntimeOptions:
    return RuntimeOptions(
        model=args.model,
        profile=args.profile,
        sandbox=args.sandbox,
        config=list(args.config),
        add_dir=list(args.add_dir),
        full_auto=bool(args.full_auto),
        dangerously_bypass_approvals_and_sandbox=bool(args.dangerously_bypass_approvals_and_sandbox),
        show_steps=bool(args.show_steps),
        display_mode=args.display,
        llm_only=bool(args.llm_only),
        heartbeat_seconds=int(args.heartbeat_seconds),
    )


def runtime_options_from_state(state: dict[str, Any]) -> RuntimeOptions:
    raw = state.get("runtime_options", {})
    if not isinstance(raw, dict):
        raw = {}

    display_mode = raw.get("display_mode")
    if not isinstance(display_mode, str) or display_mode not in {"native", "json"}:
        display_mode = "native"
    heartbeat_seconds = raw.get("heartbeat_seconds", 20)
    if not isinstance(heartbeat_seconds, int) or heartbeat_seconds < 0:
        heartbeat_seconds = 20

    return RuntimeOptions(
        model=raw.get("model") if isinstance(raw.get("model"), str) else None,
        profile=raw.get("profile") if isinstance(raw.get("profile"), str) else None,
        sandbox=raw.get("sandbox") if isinstance(raw.get("sandbox"), str) else None,
        config=[item for item in raw.get("config", []) if isinstance(item, str)],
        add_dir=[item for item in raw.get("add_dir", []) if isinstance(item, str)],
        full_auto=bool(raw.get("full_auto", False)),
        dangerously_bypass_approvals_and_sandbox=bool(
            raw.get("dangerously_bypass_approvals_and_sandbox", False)
        ),
        show_steps=bool(raw.get("show_steps", False)),
        display_mode=display_mode,
        llm_only=bool(raw.get("llm_only", False)),
        heartbeat_seconds=heartbeat_seconds,
    )


def start_detached_runner(state_path: Path, log_path: Path, *, show_console: bool = False) -> int:
    script_path = Path(__file__).resolve()
    command = [sys.executable, "-u", str(script_path), "run", "--state-file", str(state_path)]
    log_path.parent.mkdir(parents=True, exist_ok=True)
    popen_kwargs: dict[str, Any] = {}
    stdout_target: Any = subprocess.DEVNULL
    stderr_target: Any = subprocess.DEVNULL
    close_fds = True

    if sys.platform.startswith("win"):
        if show_console:
            create_new_console = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
            if create_new_console:
                popen_kwargs["creationflags"] = int(create_new_console)
            stdout_target = None
            stderr_target = None
            close_fds = False
        else:
            popen_kwargs.update(hidden_popen_kwargs())
    else:
        popen_kwargs.update(hidden_popen_kwargs())

    process = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=stdout_target,
        stderr=stderr_target,
        close_fds=close_fds,
        **popen_kwargs,
    )
    return int(process.pid)


def run_loop(state_path: Path, options: RuntimeOptions) -> int:
    codex_invocation = resolve_codex_invocation()
    if codex_invocation is None:
        print_err("Error: 'codex' was not found in PATH.")
        remove_state(state_path)
        return 1

    paused_notice_printed = False
    transient_retry_count = 0
    crash_retry_count = 0
    max_transient_retries = 3
    max_crash_retries = 2

    while True:
        current = load_state(state_path)
        if current is None:
            print_loop_info(options, "Ralph loop canceled (state file removed).")
            return 0
        if not apply_active_failover_account(current):
            print_err("[ralph-loop] Active failover account home is missing.")
            remove_state(state_path)
            return 1

        try:
            iteration, max_iterations, completion_promise, thread_id = validate_state(current, state_path)
        except RuntimeError as exc:
            print_err(str(exc))
            remove_state(state_path)
            return 1

        prompt = current.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            print_err(f"State file '{state_path}' has invalid 'prompt'.")
            remove_state(state_path)
            return 1

        paused = bool(current.get("paused", False))
        if paused:
            if not paused_notice_printed:
                print_loop_info(options, "[ralph-loop] Paused. Waiting for resume...")
                paused_notice_printed = True
            time.sleep(1.0)
            continue
        paused_notice_printed = False

        inject_queue = get_inject_queue(current)
        injected_instruction = None
        if inject_queue:
            injected_instruction = inject_queue[0]
            current["inject_queue"] = inject_queue[1:]
            current["last_injection_applied_at"] = now_utc_iso()
            current["updated_at"] = now_utc_iso()
            save_state(state_path, current)
            print_loop_info(options, "[ralph-loop] Applying injected instruction for this iteration.")

        iteration_prompt = compose_iteration_prompt(prompt, injected_instruction)

        print_loop_info(options, f"\n[ralph-loop] Iteration {iteration}")
        try:
            result = run_iteration(
                options,
                prompt=iteration_prompt,
                thread_id=thread_id,
                codex_invocation=codex_invocation,
                state_path=state_path,
            )
            crash_retry_count = 0
        except Exception:
            crash_retry_count += 1
            detail = traceback.format_exc().rstrip("\n")
            print_err("[ralph-loop] Unexpected internal exception during iteration.")
            if detail:
                print_err(detail)
            if crash_retry_count <= max_crash_retries:
                backoff = min(20, 5 * crash_retry_count)
                print_loop_info(
                    options,
                    (
                        "[ralph-loop] Retrying same iteration after internal error "
                        f"({crash_retry_count}/{max_crash_retries}) in {backoff}s."
                    ),
                )
                time.sleep(float(backoff))
                continue

            record_loop_error(
                state_path,
                kind="iteration_exception",
                message="Repeated internal exception in iteration runner (see log).",
                pause=True,
            )
            print_loop_info(
                options,
                "[ralph-loop] Loop paused due to repeated internal errors. Run resume after fixes.",
            )
            crash_retry_count = 0
            continue

        if result.return_code != 0:
            current_after_error = load_state(state_path)
            if current_after_error is not None and try_switch_failover_account(
                current_after_error,
                state_path=state_path,
                options=options,
                reason=result.error_kind or "",
            ):
                transient_retry_count = 0
                continue
            retryable = result.error_kind in {"interrupted", "transient_error"}
            if retryable and transient_retry_count < max_transient_retries:
                transient_retry_count += 1
                backoff = min(20, 5 * transient_retry_count)
                print_loop_info(
                    options,
                    (
                        "[ralph-loop] Transient codex interruption detected; retrying same iteration "
                        f"({transient_retry_count}/{max_transient_retries}) in {backoff}s."
                    ),
                )
                time.sleep(float(backoff))
                continue

            transient_retry_count = 0
            message = f"Codex exited with code {result.return_code}."
            print_err(f"[ralph-loop] {message}")
            record_loop_error(
                state_path,
                kind=result.error_kind or "codex_exit",
                message=message,
                pause=True,
            )
            print_loop_info(
                options,
                "[ralph-loop] Loop paused after execution failure. Fix issue then run resume/cancel.",
            )
            continue

        transient_retry_count = 0

        if not result.thread_id:
            message = "Missing thread id from codex output."
            print_err(f"[ralph-loop] {message}")
            record_loop_error(
                state_path,
                kind="missing_thread_id",
                message=message,
                pause=True,
            )
            print_loop_info(
                options,
                "[ralph-loop] Loop paused after protocol error. Run resume/cancel after checking logs.",
            )
            continue

        if not result.last_agent_message:
            message = "No assistant message detected in codex output."
            print_err(f"[ralph-loop] {message}")
            record_loop_error(
                state_path,
                kind="missing_assistant_message",
                message=message,
                pause=True,
            )
            print_loop_info(
                options,
                "[ralph-loop] Loop paused after protocol error. Run resume/cancel after checking logs.",
            )
            continue

        latest = load_state(state_path)
        if latest is None:
            print_loop_info(
                options,
                (
                    "[ralph-loop] Loop stopped because state file disappeared during iteration. "
                    f"State: {state_path}. "
                    "Usually this means cancel was issued from another terminal or the state file was removed."
                ),
            )
            return 0

        normalized_completion_promise = (
            normalize_promise_text(completion_promise) if completion_promise else None
        )
        promise_text = extract_promise_text(result.last_agent_message)
        if normalized_completion_promise and promise_text == normalized_completion_promise:
            print_loop_info(
                options,
                f"[ralph-loop] Completion promise matched: <promise>{completion_promise}</promise>",
            )
            remove_state(state_path)
            return 0

        if max_iterations > 0 and iteration >= max_iterations:
            print_loop_info(options, f"[ralph-loop] Max iterations reached: {max_iterations}")
            remove_state(state_path)
            return 0

        latest["thread_id"] = result.thread_id
        latest["iteration"] = iteration + 1
        latest.pop("last_error_kind", None)
        latest.pop("last_error_message", None)
        latest.pop("last_error_at", None)
        latest["updated_at"] = now_utc_iso()
        save_state(state_path, latest)


def handle_start(args: argparse.Namespace) -> int:
    state_path = Path(args.state_file)
    prompt = ""
    if args.prompt_file:
        prompt_path = Path(args.prompt_file)
        if not prompt_path.exists():
            print_err(f"Error: prompt file not found: {prompt_path}")
            return 1
        try:
            prompt = prompt_path.read_text(encoding="utf-8-sig").strip()
        except OSError as exc:
            print_err(f"Error: failed to read prompt file '{prompt_path}': {exc}")
            return 1
        except UnicodeDecodeError:
            print_err(
                f"Error: prompt file '{prompt_path}' must be UTF-8 (or UTF-8 BOM)."
            )
            return 1
    else:
        prompt = " ".join(args.prompt).strip()
    if not prompt:
        print_err("Error: prompt is required (inline prompt or --prompt-file).")
        return 1
    if args.max_iterations < 0:
        print_err("Error: --max-iterations must be >= 0.")
        return 1
    if args.completion_promise is not None and not args.completion_promise.strip():
        print_err("Error: --completion-promise cannot be empty.")
        return 1
    if args.heartbeat_seconds < 0:
        print_err("Error: --heartbeat-seconds must be >= 0.")
        return 1
    if args.detach_console and not args.detach:
        print_err("Error: --detach-console requires --detach.")
        return 1
    if args.llm_only and args.show_steps:
        print_err("Error: --llm-only cannot be used with --show-steps.")
        return 1

    existing_state = load_state(state_path)
    if existing_state is not None and not args.force:
        print_err(
            f"Error: state file already exists at '{state_path}'. "
            "Use --force to replace it or run cancel first."
        )
        return 1

    normalized_completion_promise = (
        normalize_promise_text(args.completion_promise)
        if args.completion_promise is not None
        else None
    )
    try:
        account_failover = build_account_failover_state(args)
    except RuntimeError as exc:
        print_err(f"Error: {exc}")
        return 1
    if account_failover is not None:
        active = get_active_failover_account({"account_failover": account_failover})
        if active is None:
            print_err("Error: failed to initialize account failover state.")
            return 1
        _, initial_home = active
        if not Path(initial_home).exists():
            print_err(f"Error: failover initial account home not found: {initial_home}")
            return 1
        os.environ["CODEX_HOME"] = initial_home

    log_path: Path | None = None
    if not args.no_log:
        log_path = Path(args.log_file) if args.log_file else default_log_path_for_state(state_path)
    if args.detach and log_path is None:
        print_err("Error: --detach requires logging. Remove --no-log or provide --log-file.")
        return 1

    runtime_options = {
        "model": args.model,
        "profile": args.profile,
        "sandbox": args.sandbox,
        "config": list(args.config),
        "add_dir": list(args.add_dir),
        "full_auto": bool(args.full_auto),
        "dangerously_bypass_approvals_and_sandbox": bool(args.dangerously_bypass_approvals_and_sandbox),
        "show_steps": bool(args.show_steps),
        "display_mode": args.display,
        "llm_only": bool(args.llm_only),
        "heartbeat_seconds": int(args.heartbeat_seconds),
    }

    state = {
        "active": True,
        "iteration": 1,
        "max_iterations": int(args.max_iterations),
        "completion_promise": normalized_completion_promise,
        "thread_id": None,
        "paused": False,
        "inject_queue": [],
        "started_at": now_utc_iso(),
        "updated_at": now_utc_iso(),
        "working_directory": str(Path.cwd()),
        "prompt": prompt,
        "log_file": str(log_path) if log_path else None,
        "account_failover": account_failover,
        "runtime_options": runtime_options,
    }
    save_state(state_path, state)

    options = runtime_options_from_args(args)

    if args.detach:
        assert log_path is not None
        print_loop_info(options, "Ralph loop activated.")
        print_loop_info(options, f"State file: {state_path}")
        print_loop_info(options, f"Max iterations: {args.max_iterations if args.max_iterations > 0 else 'unlimited'}")
        print_loop_info(
            options,
            f"Completion promise: {normalized_completion_promise if normalized_completion_promise else 'none'}",
        )
        if account_failover is not None:
            accounts = account_failover.get("accounts", [])
            if isinstance(accounts, list):
                print_loop_info(options, f"Account failover: {' -> '.join(str(x) for x in accounts)}")
        try:
            pid = start_detached_runner(
                state_path=state_path,
                log_path=log_path,
                show_console=bool(args.detach_console),
            )
        except OSError as exc:
            remove_state(state_path)
            print_err(f"Error: failed to start detached runner: {exc}")
            return 1

        current = load_state(state_path) or state
        current["runner_pid"] = pid
        current["detached"] = True
        current["detached_console"] = bool(args.detach_console)
        current["log_file"] = str(log_path)
        current["updated_at"] = now_utc_iso()
        save_state(state_path, current)

        print_loop_info(options, f"Detached runner started (PID {pid}).")
        if args.detach_console:
            print_loop_info(options, "Detached runner console: visible.")
        print_loop_info(options, f"Log file: {log_path}")
        return 0

    if log_path is not None:
        open_log(log_path)
    try:
        print_loop_info(options, "Ralph loop activated.")
        print_loop_info(options, f"State file: {state_path}")
        print_loop_info(
            options,
            f"Max iterations: {args.max_iterations if args.max_iterations > 0 else 'unlimited'}",
        )
        print_loop_info(
            options,
            f"Completion promise: {normalized_completion_promise if normalized_completion_promise else 'none'}",
        )
        if account_failover is not None:
            accounts = account_failover.get("accounts", [])
            if isinstance(accounts, list):
                print_loop_info(options, f"Account failover: {' -> '.join(str(x) for x in accounts)}")
        if log_path is not None:
            print_loop_info(options, f"Log file: {log_path}")
        return run_loop(state_path=state_path, options=options)
    finally:
        close_log()


def handle_run(args: argparse.Namespace) -> int:
    state_path = Path(args.state_file)
    state = load_state(state_path)
    if state is None:
        print_err(f"Error: state file not found at '{state_path}'.")
        return 1
    log_path_raw = state.get("log_file")
    log_path: Path | None = None
    if isinstance(log_path_raw, str) and log_path_raw.strip():
        log_path = Path(log_path_raw)

    if log_path is not None:
        open_log(log_path)
    try:
        return run_loop(state_path=state_path, options=runtime_options_from_state(state))
    finally:
        close_log()


def handle_cancel(args: argparse.Namespace) -> int:
    state_path = Path(args.state_file)
    state = load_state(state_path)
    if state is None:
        print("No active Ralph loop found.")
        return 0

    iteration = state.get("iteration", "?")
    runner_pid = state.get("runner_pid")

    if isinstance(runner_pid, int) and runner_pid > 0:
        if sys.platform.startswith("win"):
            subprocess.run(
                ["taskkill", "/PID", str(runner_pid), "/T", "/F"],
                capture_output=True,
                text=True,
                check=False,
            )
        else:
            try:
                os.kill(runner_pid, 15)
            except OSError:
                pass

    remove_state(state_path)
    print(f"Canceled Ralph loop (was at iteration {iteration}).")
    return 0


def handle_status(args: argparse.Namespace) -> int:
    state_path = Path(args.state_file)
    state = load_state(state_path)
    if state is None:
        print("No active Ralph loop found.")
        return 0
    print(json.dumps(state, indent=2, ensure_ascii=True))
    return 0


def handle_pause(args: argparse.Namespace) -> int:
    state_path = Path(args.state_file)
    state = load_state(state_path)
    if state is None:
        print("No active Ralph loop found.")
        return 0

    if bool(state.get("paused", False)):
        print("Ralph loop is already paused.")
        return 0

    state["paused"] = True
    state["paused_at"] = now_utc_iso()
    state["updated_at"] = now_utc_iso()
    save_state(state_path, state)
    print("Paused Ralph loop.")
    return 0


def handle_resume(args: argparse.Namespace) -> int:
    state_path = Path(args.state_file)
    state = load_state(state_path)
    if state is None:
        print("No active Ralph loop found.")
        return 0

    if not bool(state.get("paused", False)):
        print("Ralph loop is already running.")
        return 0

    state["paused"] = False
    state["resumed_at"] = now_utc_iso()
    state["updated_at"] = now_utc_iso()
    save_state(state_path, state)
    print("Resumed Ralph loop.")
    return 0


def handle_inject(args: argparse.Namespace) -> int:
    state_path = Path(args.state_file)
    state = load_state(state_path)
    if state is None:
        print("No active Ralph loop found.")
        return 0

    instruction = " ".join(args.instruction).strip()
    if not instruction:
        print_err("Error: injection text is required.")
        return 1

    queue = get_inject_queue(state)
    if args.prepend:
        queue.insert(0, instruction)
    else:
        queue.append(instruction)

    state["inject_queue"] = queue
    state["last_injected_at"] = now_utc_iso()
    state["updated_at"] = now_utc_iso()
    save_state(state_path, state)

    position = "front" if args.prepend else "back"
    print(f"Queued injected instruction at {position}. Queue size: {len(queue)}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Ralph-style loop driver for Codex CLI.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_start = sub.add_parser("start", help="Start a Ralph loop.")
    p_start.add_argument("prompt", nargs="*", help="Prompt to replay every iteration.")
    p_start.add_argument(
        "--prompt-file",
        type=str,
        default=None,
        help="Read full prompt from UTF-8 text file (avoids Windows CLI encoding issues).",
    )
    p_start.add_argument("--max-iterations", type=int, default=0, help="0 means unlimited.")
    p_start.add_argument("--completion-promise", type=str, default=None)
    p_start.add_argument("--state-file", default=DEFAULT_STATE_FILE)
    p_start.add_argument("--force", action="store_true", help="Overwrite existing state file.")
    p_start.add_argument("--detach", action="store_true", help="Run loop in background.")
    p_start.add_argument(
        "--detach-console",
        action="store_true",
        help="With --detach on Windows, run worker in a visible console window for realtime monitoring.",
    )
    p_start.add_argument("--log-file", type=str, default=None, help="Optional log file path.")
    p_start.add_argument("--no-log", action="store_true", help="Disable task log file for foreground mode.")
    p_start.add_argument("--model", type=str, default=None)
    p_start.add_argument("--profile", type=str, default=None)
    p_start.add_argument(
        "--sandbox",
        type=str,
        default=None,
        choices=("read-only", "workspace-write", "danger-full-access"),
    )
    p_start.add_argument("--config", action="append", default=[], help="Repeatable key=value.")
    p_start.add_argument("--add-dir", action="append", default=[], help="Repeatable directory.")
    p_start.add_argument("--full-auto", action="store_true")
    p_start.add_argument("--dangerously-bypass-approvals-and-sandbox", action="store_true")
    p_start.add_argument(
        "--auto-account-failover",
        action="store_true",
        help="When quota is exhausted, switch to the next account and retry the same iteration.",
    )
    p_start.add_argument(
        "--failover-account",
        action="append",
        default=[],
        help="Repeatable or comma-separated account names for quota failover order.",
    )
    p_start.add_argument(
        "--display",
        choices=("native", "json"),
        default="native",
        help="native = Codex built-in human formatting, json = custom parser output.",
    )
    p_start.add_argument("--show-steps", action="store_true", help="Show per-iteration command steps.")
    p_start.add_argument(
        "--llm-only",
        action="store_true",
        help="Only print assistant messages; suppress loop/status/tool output.",
    )
    p_start.add_argument(
        "--heartbeat-seconds",
        type=int,
        default=20,
        help="Emit heartbeat when no new output is seen for N seconds (0 disables).",
    )
    p_start.set_defaults(handler=handle_start)

    p_run = sub.add_parser("run", help=argparse.SUPPRESS)
    p_run.add_argument("--state-file", default=DEFAULT_STATE_FILE)
    p_run.set_defaults(handler=handle_run)

    p_cancel = sub.add_parser("cancel", help="Cancel an active Ralph loop.")
    p_cancel.add_argument("--state-file", default=DEFAULT_STATE_FILE)
    p_cancel.set_defaults(handler=handle_cancel)

    p_status = sub.add_parser("status", help="Show active loop state.")
    p_status.add_argument("--state-file", default=DEFAULT_STATE_FILE)
    p_status.set_defaults(handler=handle_status)

    p_pause = sub.add_parser("pause", help="Pause loop between iterations.")
    p_pause.add_argument("--state-file", default=DEFAULT_STATE_FILE)
    p_pause.set_defaults(handler=handle_pause)

    p_resume = sub.add_parser("resume", help="Resume a paused loop.")
    p_resume.add_argument("--state-file", default=DEFAULT_STATE_FILE)
    p_resume.set_defaults(handler=handle_resume)

    p_inject = sub.add_parser("inject", help="Inject a one-shot instruction for next iteration.")
    p_inject.add_argument("instruction", nargs="+", help="Instruction text to inject.")
    p_inject.add_argument("--state-file", default=DEFAULT_STATE_FILE)
    p_inject.add_argument("--prepend", action="store_true", help="Insert at front of queue.")
    p_inject.set_defaults(handler=handle_inject)

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
    except Exception:
        detail = traceback.format_exc().rstrip("\n")
        print_err("Error: unhandled exception in ralph_loop.py")
        if detail:
            print_err(detail)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
