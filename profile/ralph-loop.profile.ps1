# ========== Ralph Loop Shortcuts ==========
function Invoke-RalphLoopScript {
  [CmdletBinding()]
  param(
    [Parameter(ValueFromRemainingArguments=$true)]
    [string[]]$Args
  )

  $script = "$env:USERPROFILE\.codex\skills\ralph-loop\scripts\ralph_loop.py"
  if (!(Test-Path $script)) {
    $portable = Join-Path $PSScriptRoot "..\skills\ralph-loop\scripts\ralph_loop.py"
    if (Test-Path $portable) {
      $script = (Resolve-Path $portable).Path
    } else {
      throw "ralph_loop.py not found: $script"
    }
  }
  python -u $script @Args
}

function Set-RalphAccount {
  [CmdletBinding()]
  param(
    [Parameter(Position=0)]
    [string]$Account = "bal"
  )

  $target = "$env:USERPROFILE\.codex-$Account"
  if (!(Test-Path $target)) { throw "Codex account home not found: $target" }
  $env:CODEX_HOME = $target
  Write-Host "CODEX_HOME -> $env:CODEX_HOME"
}

function Invoke-RalphLoop {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory=$true, Position=0, ValueFromRemainingArguments=$true)]
    [string[]]$Rest,
    [Alias("a")]
    [string]$Account = ""
  )

  if ($Account) {
    Set-RalphAccount $Account
  } elseif (!$env:CODEX_HOME) {
    Set-RalphAccount "bal"
  }
  rl @Rest
}

function Invoke-RalphLoopBal {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory=$true, Position=0, ValueFromRemainingArguments=$true)]
    [string[]]$Rest
  )

  Invoke-RalphLoop @Rest -Account "bal"
}

function Start-RalphLoop {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory=$true, Position=0)]
    [string]$Prompt,
    [Alias("a")]
    [string]$Account = "",
    [int]$MaxIterations = 100,
    [switch]$Safe,
    [switch]$AutoFailover,
    [switch]$NoAutoFailover,
    [string[]]$FailoverAccount = @(),
    [Parameter(ValueFromRemainingArguments=$true)]
    [string[]]$ExtraArgs
  )

  $cmd = @("start", $Prompt, "--max-iterations", "$MaxIterations", "--display", "native")
  $enableAutoFailover = $AutoFailover -or -not $NoAutoFailover
  if ($enableAutoFailover -and -not ($ExtraArgs -contains "--auto-account-failover")) {
    $cmd += "--auto-account-failover"
  }
  foreach ($acc in $FailoverAccount) {
    if ($acc) { $cmd += @("--failover-account", $acc) }
  }
  if (!$Safe) {
    $hasDanger = $false
    if ($ExtraArgs) { $hasDanger = ($ExtraArgs -contains "--dangerously-bypass-approvals-and-sandbox") }
    if (!$hasDanger) { $cmd += "--dangerously-bypass-approvals-and-sandbox" }
  }
  if ($ExtraArgs) { $cmd += $ExtraArgs }
  Invoke-RalphLoop @cmd -Account $Account
}

function Write-RalphWatchLine {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory=$true)]
    [AllowEmptyString()]
    [string]$Line
  )

  $text = $Line
  $color = $null

  if ($text -match "^\[ralph-loop\] Iteration \d+") { $color = "Cyan" }
  elseif ($text -match "Completion promise matched|Max iterations reached") { $color = "Green" }
  elseif ($text -match "Paused\. Waiting for resume|Applying injected instruction") { $color = "Yellow" }
  elseif ($text -match "^\[step\]") { $color = "DarkCyan" }
  elseif ($text -match "^thinking$") { $color = "DarkGray" }
  elseif ($text -match "^tokens used$") { $color = "DarkGray" }
  elseif ($text -match "ERROR|error:|Traceback|exited with code|No assistant message detected|Missing thread id") {
    $color = "Red"
  }
  elseif ($text -match "<promise>.*</promise>") { $color = "Green" }
  elseif ($text -match "^codex$") { $color = "Magenta" }
  elseif ($text -match "^user$") { $color = "Yellow" }

  if ($null -ne $color) {
    Write-Host $text -ForegroundColor $color
  } else {
    Write-Host $text
  }
}

function Start-RalphLoopWatch {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory=$true, Position=0)]
    [string]$Prompt,
    [Alias("a")]
    [string]$Account = "",
    [int]$MaxIterations = 100,
    [switch]$Safe,
    [switch]$ShowSteps,
    [switch]$AutoFailover,
    [switch]$NoAutoFailover,
    [string[]]$FailoverAccount = @(),
    [Parameter(ValueFromRemainingArguments=$true)]
    [string[]]$ExtraArgs
  )

  $cmd = @("start", $Prompt, "--max-iterations", "$MaxIterations")

  $hasDisplay = $false
  if ($ExtraArgs) {
    for ($i = 0; $i -lt $ExtraArgs.Count; $i++) {
      if ($ExtraArgs[$i] -eq "--display") { $hasDisplay = $true; break }
    }
  }
  if (-not $hasDisplay) {
    if ($ShowSteps) { $cmd += @("--display", "json") }
    else { $cmd += @("--display", "native") }
  }
  if ($ShowSteps -and -not ($ExtraArgs -contains "--show-steps")) { $cmd += "--show-steps" }
  $enableAutoFailover = $AutoFailover -or -not $NoAutoFailover
  if ($enableAutoFailover -and -not ($ExtraArgs -contains "--auto-account-failover")) {
    $cmd += "--auto-account-failover"
  }
  foreach ($acc in $FailoverAccount) {
    if ($acc) { $cmd += @("--failover-account", $acc) }
  }

  if (!$Safe) {
    $hasDanger = $false
    if ($ExtraArgs) { $hasDanger = ($ExtraArgs -contains "--dangerously-bypass-approvals-and-sandbox") }
    if (!$hasDanger) { $cmd += "--dangerously-bypass-approvals-and-sandbox" }
  }

  if ($ExtraArgs) { $cmd += $ExtraArgs }

  if ($Account) {
    Set-RalphAccount $Account
  } elseif (!$env:CODEX_HOME) {
    Set-RalphAccount "bal"
  }

  $script = "$env:USERPROFILE\.codex\skills\ralph-loop\scripts\ralph_loop.py"
  if (!(Test-Path $script)) { throw "ralph_loop.py not found: $script" }

  $oldPyUnbuffered = $env:PYTHONUNBUFFERED
  $env:PYTHONUNBUFFERED = "1"
  try {
    & python -u $script @cmd 2>&1 | ForEach-Object {
      $line = $_
      if ($line -is [System.Management.Automation.ErrorRecord]) {
        $line = $line.ToString()
      }
      if ([string]::IsNullOrEmpty("$line")) {
        Write-Host ""
        return
      }
      Write-RalphWatchLine -Line "$line"
    }
  } finally {
    if ($null -eq $oldPyUnbuffered) {
      Remove-Item Env:PYTHONUNBUFFERED -ErrorAction SilentlyContinue
    } else {
      $env:PYTHONUNBUFFERED = $oldPyUnbuffered
    }
  }

  if ($LASTEXITCODE -ne 0) {
    return $LASTEXITCODE
  }
}

function Show-RalphLog {
  [CmdletBinding()]
  param(
    [Alias("a")]
    [string]$Account = "",
    [string]$StateFile = "",
    [string]$LogFile = "",
    [int]$Lines = 80,
    [switch]$Follow,
    [switch]$PathOnly
  )

  $codexHome = ""
  if ($Account) {
    $codexHome = "$env:USERPROFILE\.codex-$Account"
  } elseif ($env:CODEX_HOME) {
    $codexHome = $env:CODEX_HOME
  } else {
    $codexHome = "$env:USERPROFILE\.codex-bal"
  }

  if (!(Test-Path $codexHome)) { throw "Codex home not found: $codexHome" }

  $statePath = if ($StateFile) { $StateFile } else { Join-Path $codexHome "ralph-loop.local.json" }
  $logPath = $null

  $explicitLogPath = $false
  if ($LogFile) {
    $explicitLogPath = $true
    $logPath = $LogFile
  }

  if (!$logPath -and (Test-Path $statePath)) {
    try {
      $state = Get-Content -Raw $statePath | ConvertFrom-Json
      if ($state -and $state.log_file) {
        $logPath = [string]$state.log_file
      }
    } catch {
      # fallback to latest log file
    }
  }

  if ($explicitLogPath -and !(Test-Path $logPath)) {
    New-Item -ItemType File -Path $logPath -Force | Out-Null
  }

  if (!$explicitLogPath -and (!$logPath -or !(Test-Path $logPath))) {
    $latest = Get-ChildItem $codexHome -File -ErrorAction SilentlyContinue |
      Where-Object { $_.Name -like "ralph-*.log" -or $_.Name -like "ralph-loop.local*.log" } |
      Sort-Object LastWriteTime -Descending |
      Select-Object -First 1
    if ($latest) {
      $logPath = $latest.FullName
    }
  }

  if (!$logPath -or !(Test-Path $logPath)) {
    throw "No Ralph loop log file found under: $codexHome"
  }

  if ($PathOnly) {
    Write-Host $logPath
    return
  }

  Write-Host "Log file: $logPath"
  if ($Follow) {
    Get-Content -Path $logPath -Tail $Lines -Wait -Encoding UTF8
  } else {
    Get-Content -Path $logPath -Tail $Lines -Encoding UTF8
  }
}

function Start-ResonDevLoop {
  [CmdletBinding()]
  param(
    [Alias("a")]
    [string]$Account = "yiye",
    [int]$MaxIterations = 300,
    [string]$PromptOverride = ""
  )

  $repo = "C:\Users\walty\Desktop\reson"
  if (!(Test-Path $repo)) { throw "Repo path not found: $repo" }
  Set-Location $repo

  $sf = "$env:USERPROFILE\.codex-$Account\ralph-reson-dev.json"
  $lf = "$env:USERPROFILE\.codex-$Account\ralph-reson-dev.log"

  $prompt = $PromptOverride
  if (!$prompt) {
    $prompt = @'
你是本项目（C:\Users\walty\Desktop\reson）的驻场工程代理，进入“持续循环开发模式”。

【唯一状态源】
- 必须维护并使用仓库根目录文件：`LOOP_STATE.md`
- 每轮开始：先读取 `LOOP_STATE.md`
- 每轮结束：先更新 `LOOP_STATE.md` 再提交代码
- 文档与代码同一个 commit，保证可追溯

【总目标】
- 以企业级可维护标准持续交付
- 当前阶段：功能优先（Feature-first），避免继续扩基建

【硬性边界】
1. 只允许在 `C:\Users\walty\Desktop\reson` 内读写
2. 禁止破坏性命令：`git reset --hard`、`git checkout --`、大范围删除
3. 不推送远程仓库，只做本地提交
4. 不允许只给方案不落地；除非阻塞，否则必须改代码并验证
5. 保持现有架构边界与代码风格

【每轮循环协议】
1. 读取现状：
   - 最近提交
   - `LOOP_STATE.md` 的 `In Progress` 和 `Backlog`
2. 选择一个最小任务（优先级：P0 > P1 > P2）
3. 实施最小改动（只改完成该任务所需文件）
4. 验证：
   - 先跑受影响测试
   - 再跑 `python scripts/run_engineering_gate.py`
   - 必要时跑 `pytest -q`
5. 通过后本地提交（Conventional Commits，一任务一提交）
6. 更新 `LOOP_STATE.md` 的：
   - `In Progress`
   - `Decisions`（若有）
   - `Last Loop Report`
7. 每轮回复末尾必须追加：

[LOOP_REPORT]
commit: <hash / none>
next: <下一轮最小任务>
risk: <风险或阻塞；无则 none>
[/LOOP_REPORT]

【当前起始任务】
- 从 `LOOP_STATE.md` 当前 `In Progress` 开始执行
- 若为空，默认从 `P0-001` 开始

【结束条件】
- 当 `In Progress` 为空、`Backlog` 为空，且本轮验证全通过时，最后一行输出：<promise>LOOP_DONE</promise>
'@
  }

  rlsraw $prompt -a $Account -MaxIterations $MaxIterations -AutoFailover --state-file $sf --log-file $lf --completion-promise LOOP_DONE --llm-only
}

function Start-ProjectDevLoop {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory=$true, Position=0)]
    [string]$ProjectPath,
    [Parameter(Position=1)]
    [string]$Prompt = "",
    [string]$PromptFile = "",
    [Alias("a")]
    [string]$Account = "yiye",
    [int]$MaxIterations = 300,
    [string]$CompletionPromise = "LOOP_DONE",
    [string]$StateTag = "",
    [int]$HeartbeatSeconds = 20,
    [switch]$NativeConsole,
    [switch]$NoLlmOnly,
    [switch]$NoAutoFailover,
    [string[]]$FailoverAccount = @(),
    [switch]$NoWatch
  )

  if (!(Test-Path $ProjectPath)) { throw "Project path not found: $ProjectPath" }
  $resolvedProjectPath = (Resolve-Path $ProjectPath).Path
  Set-Location $resolvedProjectPath

  $resolvedPromptFile = ""
  $finalPrompt = $Prompt
  if ($PromptFile) {
    if (!(Test-Path $PromptFile)) { throw "Prompt file not found: $PromptFile" }
    $resolvedPromptFile = (Resolve-Path $PromptFile).Path
  }
  if (!$resolvedPromptFile -and !$finalPrompt.Trim()) {
    throw "Prompt is empty. Provide -Prompt or -PromptFile."
  }

  if (!$StateTag) {
    $leaf = Split-Path -Leaf $resolvedProjectPath
    $StateTag = ($leaf -replace "[^A-Za-z0-9_-]", "-").ToLower()
    if (!$StateTag) { $StateTag = "project" }
  }

  $sf = "$env:USERPROFILE\.codex-$Account\ralph-$StateTag.json"
  $lf = "$env:USERPROFILE\.codex-$Account\ralph-$StateTag.log"
  Write-Host "State file: $sf"
  Write-Host "Log file:   $lf"

  if ($HeartbeatSeconds -lt 0) { throw "-HeartbeatSeconds must be >= 0" }
  if ($NativeConsole) { $NoLlmOnly = $true }
  $watchEnabled = -not $NoWatch
  if ($NativeConsole -and $watchEnabled) {
    Write-Host "NativeConsole enabled: disabling inline log watch to avoid duplicate output."
    $watchEnabled = $false
  }
  $cmd = @("start", "--max-iterations", "$MaxIterations", "--display", "native")
  if ($resolvedPromptFile) {
    $cmd += @("--prompt-file", $resolvedPromptFile)
  } else {
    $cmd += $finalPrompt
  }
  if (!$NoAutoFailover -or ($FailoverAccount.Count -gt 0)) {
    $cmd += "--auto-account-failover"
  }
  foreach ($acc in $FailoverAccount) {
    if ($acc) { $cmd += @("--failover-account", $acc) }
  }
  $cmd += "--dangerously-bypass-approvals-and-sandbox"

  $extra = @("--state-file", $sf, "--log-file", $lf, "--completion-promise", $CompletionPromise, "--heartbeat-seconds", "$HeartbeatSeconds")
  if (!$NoLlmOnly) { $extra += "--llm-only" }
  if ($watchEnabled -or $NativeConsole) { $extra += "--detach" }
  if ($NativeConsole) { $extra += "--detach-console" }
  $cmd += $extra

  Invoke-RalphLoop @cmd -Account $Account
  if ($LASTEXITCODE -ne 0) {
    return $LASTEXITCODE
  }

  if ($watchEnabled) {
    Write-Host "Watching log (Ctrl+C only stops watch, loop keeps running)."
    Show-RalphLog -Account $Account -LogFile $lf -Follow
  }
}

function Invoke-CodexAgentTeamScript {
  [CmdletBinding()]
  param(
    [Parameter(ValueFromRemainingArguments=$true)]
    [string[]]$Args
  )

  $script = "$env:USERPROFILE\.codex\skills\ralph-loop\scripts\agent_team\codex_agent_team.py"
  if (!(Test-Path $script)) {
    $portable = Join-Path $PSScriptRoot "..\skills\ralph-loop\scripts\agent_team\codex_agent_team.py"
    if (Test-Path $portable) {
      $script = (Resolve-Path $portable).Path
    } else {
      throw "codex_agent_team.py not found: $script"
    }
  }
  python -u $script @Args
}

function Resolve-CodexAgentTeamConfigPath {
  [CmdletBinding()]
  param(
    [string]$Config = "",
    [string]$TeamRoot = ""
  )

  if ($Config) {
    if (!(Test-Path $Config)) { throw "Config not found: $Config" }
    return (Resolve-Path $Config).Path
  }

  if ($TeamRoot) {
    if (!(Test-Path $TeamRoot)) { throw "Team root not found: $TeamRoot" }
    $cfg = Join-Path (Resolve-Path $TeamRoot).Path "team_config.json"
    if (!(Test-Path $cfg)) { throw "Team config not found: $cfg" }
    return $cfg
  }

  $default = Join-Path (Get-Location).Path ".codex-agent-team\team_config.json"
  if (Test-Path $default) { return (Resolve-Path $default).Path }

  throw "Team config not found. Use -Config or -TeamRoot."
}

function Initialize-CodexAgentTeam {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory=$true, Position=0)]
    [string]$ProjectPath,
    [Parameter(Mandatory=$true)]
    [string]$Accounts,
    [string]$Commander = "",
    [string]$Reviewer = "",
    [string]$Workers = "",
    [string]$TeamRoot = "",
    [string]$TeamName = "",
    [string]$Branch = "",
    [switch]$OverwritePrompts
  )

  $cmd = @("init", "--project-path", $ProjectPath, "--accounts", $Accounts)
  if ($Commander) { $cmd += @("--commander", $Commander) }
  if ($Reviewer) { $cmd += @("--reviewer", $Reviewer) }
  if ($Workers) { $cmd += @("--workers", $Workers) }
  if ($TeamRoot) { $cmd += @("--team-root", $TeamRoot) }
  if ($TeamName) { $cmd += @("--team-name", $TeamName) }
  if ($Branch) { $cmd += @("--branch", $Branch) }
  if ($OverwritePrompts) { $cmd += "--overwrite-prompts" }
  Invoke-CodexAgentTeamScript @cmd
}

function Start-CodexAgentTeam {
  [CmdletBinding()]
  param(
    [string]$Config = "",
    [string]$TeamRoot = "",
    [int]$MaxIterations = 0,
    [int]$HeartbeatSeconds = 20,
    [string]$Only = "",
    [string]$Model = "",
    [string]$Profile = "",
    [ValidateSet("", "read-only", "workspace-write", "danger-full-access")]
    [string]$Sandbox = "",
    [switch]$LlmOnly,
    [switch]$DetachConsole,
    [switch]$Restart,
    [switch]$AutoFailover,
    [switch]$NoAutoFailover,
    [string]$FailoverAccounts = ""
  )

  $cfg = Resolve-CodexAgentTeamConfigPath -Config $Config -TeamRoot $TeamRoot
  $cmd = @(
    "start",
    "--config", $cfg,
    "--max-iterations", "$MaxIterations",
    "--heartbeat-seconds", "$HeartbeatSeconds",
    "--dangerous"
  )
  if ($Only) { $cmd += @("--only", $Only) }
  if ($Model) { $cmd += @("--model", $Model) }
  if ($Profile) { $cmd += @("--profile", $Profile) }
  if ($Sandbox) { $cmd += @("--sandbox", $Sandbox) }
  if ($LlmOnly) { $cmd += "--llm-only" }
  if ($DetachConsole) { $cmd += "--detach-console" }
  if ($Restart) { $cmd += "--restart" }
  $enableFailover = $true
  if ($NoAutoFailover) { $enableFailover = $false }
  if ($AutoFailover) { $enableFailover = $true }
  if ($enableFailover) {
    $cmd += "--auto-account-failover"
    if ($FailoverAccounts) { $cmd += @("--failover-accounts", $FailoverAccounts) }
  } else {
    $cmd += "--no-auto-account-failover"
  }
  Invoke-CodexAgentTeamScript @cmd
}

function Stop-CodexAgentTeam {
  [CmdletBinding()]
  param(
    [string]$Config = "",
    [string]$TeamRoot = "",
    [string]$Only = ""
  )

  $cfg = Resolve-CodexAgentTeamConfigPath -Config $Config -TeamRoot $TeamRoot
  $cmd = @("stop", "--config", $cfg)
  if ($Only) { $cmd += @("--only", $Only) }
  Invoke-CodexAgentTeamScript @cmd
}

function Get-CodexAgentTeamStatus {
  [CmdletBinding()]
  param(
    [string]$Config = "",
    [string]$TeamRoot = "",
    [string]$Only = ""
  )

  $cfg = Resolve-CodexAgentTeamConfigPath -Config $Config -TeamRoot $TeamRoot
  $cmd = @("status", "--config", $cfg)
  if ($Only) { $cmd += @("--only", $Only) }
  Invoke-CodexAgentTeamScript @cmd
}

function Watch-CodexAgentTeamLog {
  [CmdletBinding()]
  param(
    [string]$Config = "",
    [string]$TeamRoot = "",
    [Parameter(Mandatory=$true)]
    [string]$Agent,
    [int]$Lines = 120,
    [switch]$Follow
  )

  $cfg = Resolve-CodexAgentTeamConfigPath -Config $Config -TeamRoot $TeamRoot
  $cmd = @("watch", "--config", $cfg, "--agent", $Agent, "--lines", "$Lines")
  if ($Follow) { $cmd += "--follow" }
  Invoke-CodexAgentTeamScript @cmd
}

function Watch-CodexAgentTeamAll {
  [CmdletBinding()]
  param(
    [string]$Config = "",
    [string]$TeamRoot = "",
    [string]$Only = "",
    [int]$Lines = 60,
    [switch]$Follow
  )

  $cfg = Resolve-CodexAgentTeamConfigPath -Config $Config -TeamRoot $TeamRoot
  $cmd = @("watch-all", "--config", $cfg, "--lines", "$Lines")
  if ($Only) { $cmd += @("--only", $Only) }
  if ($Follow) { $cmd += "--follow" }
  Invoke-CodexAgentTeamScript @cmd
}

function Pause-CodexAgentTeam {
  [CmdletBinding()]
  param(
    [string]$Config = "",
    [string]$TeamRoot = "",
    [string]$Only = ""
  )

  $cfg = Resolve-CodexAgentTeamConfigPath -Config $Config -TeamRoot $TeamRoot
  $cmd = @("pause", "--config", $cfg)
  if ($Only) { $cmd += @("--only", $Only) }
  Invoke-CodexAgentTeamScript @cmd
}

function Resume-CodexAgentTeam {
  [CmdletBinding()]
  param(
    [string]$Config = "",
    [string]$TeamRoot = "",
    [string]$Only = ""
  )

  $cfg = Resolve-CodexAgentTeamConfigPath -Config $Config -TeamRoot $TeamRoot
  $cmd = @("resume", "--config", $cfg)
  if ($Only) { $cmd += @("--only", $Only) }
  Invoke-CodexAgentTeamScript @cmd
}

function Inject-CodexAgentTeam {
  [CmdletBinding()]
  param(
    [string]$Config = "",
    [string]$TeamRoot = "",
    [string]$Only = "",
    [switch]$Prepend,
    [Parameter(Mandatory=$true, Position=0, ValueFromRemainingArguments=$true)]
    [string[]]$Instruction
  )

  $cfg = Resolve-CodexAgentTeamConfigPath -Config $Config -TeamRoot $TeamRoot
  $cmd = @("inject", "--config", $cfg)
  if ($Only) { $cmd += @("--only", $Only) }
  if ($Prepend) { $cmd += "--prepend" }
  $cmd += $Instruction
  Invoke-CodexAgentTeamScript @cmd
}

function Add-CodexAgentTeamTask {
  [CmdletBinding()]
  param(
    [string]$Config = "",
    [string]$TeamRoot = "",
    [ValidateSet("P0","P1","P2")]
    [string]$Priority = "P1",
    [string]$TaskId = "",
    [Parameter(Mandatory=$true)]
    [string]$Title,
    [Parameter(Mandatory=$true)]
    [string]$Acceptance,
    [switch]$NoPush
  )

  $cfg = Resolve-CodexAgentTeamConfigPath -Config $Config -TeamRoot $TeamRoot
  $cmd = @(
    "enqueue",
    "--config", $cfg,
    "--priority", $Priority,
    "--title", $Title,
    "--acceptance", $Acceptance
  )
  if ($TaskId) { $cmd += @("--task-id", $TaskId) }
  if ($NoPush) { $cmd += "--no-push" }
  Invoke-CodexAgentTeamScript @cmd
}

function Get-CodexAgentTeamAccounts {
  [CmdletBinding()]
  param(
    [string]$Config = "",
    [string]$TeamRoot = ""
  )

  $cfg = Resolve-CodexAgentTeamConfigPath -Config $Config -TeamRoot $TeamRoot
  Invoke-CodexAgentTeamScript "accounts" "--config" $cfg
}

function Refresh-CodexAgentTeamPrompts {
  [CmdletBinding()]
  param(
    [string]$Config = "",
    [string]$TeamRoot = "",
    [string]$Only = ""
  )

  $cfg = Resolve-CodexAgentTeamConfigPath -Config $Config -TeamRoot $TeamRoot
  $cmd = @("refresh-prompts", "--config", $cfg)
  if ($Only) { $cmd += @("--only", $Only) }
  Invoke-CodexAgentTeamScript @cmd
}

function Add-CodexAgentTeamWorker {
  [CmdletBinding()]
  param(
    [string]$Config = "",
    [string]$TeamRoot = "",
    [string]$Name = "",
    [string]$Account = "",
    [ValidateSet("worker_general","worker_docs","worker_quality")]
    [string]$Role = "worker_general",
    [switch]$AllowAccountReuse,
    [switch]$NoStart,
    [int]$MaxIterations = 0,
    [switch]$LlmOnly,
    [int]$HeartbeatSeconds = 20,
    [switch]$NoAutoFailover
  )

  $cfg = Resolve-CodexAgentTeamConfigPath -Config $Config -TeamRoot $TeamRoot
  $cmd = @(
    "add-worker",
    "--config", $cfg,
    "--role", $Role,
    "--max-iterations", "$MaxIterations",
    "--heartbeat-seconds", "$HeartbeatSeconds"
  )
  if ($Name) { $cmd += @("--name", $Name) }
  if ($Account) { $cmd += @("--account", $Account) }
  if ($AllowAccountReuse) { $cmd += "--allow-account-reuse" }
  if ($NoStart) { $cmd += "--no-start" }
  if ($LlmOnly) { $cmd += "--llm-only" }
  if ($NoAutoFailover) { $cmd += "--no-auto-account-failover" }
  Invoke-CodexAgentTeamScript @cmd
}

function Remove-CodexAgentTeamWorker {
  [CmdletBinding()]
  param(
    [string]$Config = "",
    [string]$TeamRoot = "",
    [Parameter(Mandatory=$true)]
    [string]$Agent,
    [switch]$Force
  )

  $cfg = Resolve-CodexAgentTeamConfigPath -Config $Config -TeamRoot $TeamRoot
  $cmd = @("remove-agent", "--config", $cfg, "--agent", $Agent)
  if ($Force) { $cmd += "--force" }
  Invoke-CodexAgentTeamScript @cmd
}

Set-Alias rl Invoke-RalphLoopScript
Set-Alias rla Set-RalphAccount
Set-Alias rlx Invoke-RalphLoop
Set-Alias rlb Invoke-RalphLoopBal
Set-Alias rlsraw Start-RalphLoop
Set-Alias rls Start-RalphLoopWatch
Set-Alias rlwatch Start-RalphLoopWatch
Set-Alias rlw Start-RalphLoopWatch
Set-Alias rllog Show-RalphLog
Set-Alias rlreson Start-ResonDevLoop
Set-Alias rlproj Start-ProjectDevLoop
Set-Alias rlteam Invoke-CodexAgentTeamScript
Set-Alias rlteam-init Initialize-CodexAgentTeam
Set-Alias rlteam-start Start-CodexAgentTeam
Set-Alias rlteam-stop Stop-CodexAgentTeam
Set-Alias rlteam-status Get-CodexAgentTeamStatus
Set-Alias rlteam-watch Watch-CodexAgentTeamLog
Set-Alias rlteam-watchall Watch-CodexAgentTeamAll
Set-Alias rlteam-task Add-CodexAgentTeamTask
Set-Alias rlteam-accounts Get-CodexAgentTeamAccounts
Set-Alias rlteam-refresh Refresh-CodexAgentTeamPrompts
Set-Alias rlteam-add Add-CodexAgentTeamWorker
Set-Alias rlteam-rm Remove-CodexAgentTeamWorker
Set-Alias rlteam-pause Pause-CodexAgentTeam
Set-Alias rlteam-resume Resume-CodexAgentTeam
Set-Alias rlteam-inject Inject-CodexAgentTeam
# ========== End Ralph Loop Shortcuts ==========
