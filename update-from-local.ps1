[CmdletBinding()]
param(
    [string]$RepoRoot = "",
    [string]$LocalSkillDir = "$env:USERPROFILE\.codex\skills\ralph-loop",
    [string]$LocalProfile = "$env:USERPROFILE\Documents\WindowsPowerShell\Microsoft.PowerShell_profile.ps1",
    [string]$LocalCodexProfilesDir = "$env:USERPROFILE\.codex-profiles"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (-not $RepoRoot) {
    if ($PSCommandPath) {
        $RepoRoot = Split-Path -Parent $PSCommandPath
    } elseif ($PSScriptRoot) {
        $RepoRoot = $PSScriptRoot
    } else {
        $RepoRoot = (Get-Location).Path
    }
}

$resolvedRepoRoot = (Resolve-Path $RepoRoot).Path
$expectedRootFile = Join-Path $resolvedRepoRoot "skills\ralph-loop\scripts\ralph_loop.py"
if (-not (Test-Path $expectedRootFile) -and $PSCommandPath) {
    $fallbackRoot = Split-Path -Parent $PSCommandPath
    if (Test-Path (Join-Path $fallbackRoot "skills\ralph-loop\scripts\ralph_loop.py")) {
        $resolvedRepoRoot = $fallbackRoot
    }
}
$targetSkillDir = Join-Path $resolvedRepoRoot "skills\ralph-loop"
$targetRalphProfile = Join-Path $resolvedRepoRoot "profile\ralph-loop.profile.ps1"
$targetCodexProfilesDir = Join-Path $resolvedRepoRoot "codex-profiles"
$targetCodexProfileScript = Join-Path $targetCodexProfilesDir "codex-multi-account.profile.ps1"

if (-not (Test-Path $LocalSkillDir)) {
    throw "Local skill folder not found: $LocalSkillDir"
}
if (-not (Test-Path $LocalProfile)) {
    throw "Local profile not found: $LocalProfile"
}
if (-not (Test-Path $LocalCodexProfilesDir)) {
    throw "Local codex-profiles folder not found: $LocalCodexProfilesDir"
}

# Sync skill
if (Test-Path $targetSkillDir) {
    Remove-Item -Path $targetSkillDir -Recurse -Force
}
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $targetSkillDir) | Out-Null
Copy-Item -Path $LocalSkillDir -Destination (Split-Path -Parent $targetSkillDir) -Recurse -Force
Write-Host "Synced skill from local: $LocalSkillDir"

# Remove Python cache artifacts from portable package
Get-ChildItem -Path $targetSkillDir -Directory -Recurse -Filter "__pycache__" -ErrorAction SilentlyContinue |
    ForEach-Object { Remove-Item -Path $_.FullName -Recurse -Force -ErrorAction SilentlyContinue }
Get-ChildItem -Path $targetSkillDir -File -Recurse -Include *.pyc,*.pyo -ErrorAction SilentlyContinue |
    ForEach-Object { Remove-Item -Path $_.FullName -Force -ErrorAction SilentlyContinue }
Write-Host "Cleaned Python cache artifacts under portable skill folder."

# Extract Ralph block from local profile
$profileRaw = Get-Content -Raw -Encoding UTF8 $LocalProfile
$ralphStart = "# ========== Ralph Loop Shortcuts =========="
$ralphEnd = "# ========== End Ralph Loop Shortcuts =========="
$rStartIndex = $profileRaw.IndexOf($ralphStart)
$rEndIndex = $profileRaw.IndexOf($ralphEnd)
if ($rStartIndex -lt 0 -or $rEndIndex -le $rStartIndex) {
    throw "Could not find Ralph block markers in profile: $LocalProfile"
}
$rEndExclusive = $rEndIndex + $ralphEnd.Length
$ralphBlock = $profileRaw.Substring($rStartIndex, $rEndExclusive - $rStartIndex)
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $targetRalphProfile) | Out-Null
Set-Content -Path $targetRalphProfile -Encoding UTF8 -Value $ralphBlock
Write-Host "Synced Ralph profile block from local profile."

# Extract Codex multi-account block from local profile (without tab-title/cd override block)
$codexStart = "# ========== Codex Multi-Account Launcher =========="
$addAccountEnd = "# ========== End Add Account =========="
$cStartIndex = $profileRaw.IndexOf($codexStart)
$cEndIndex = $profileRaw.IndexOf($addAccountEnd)
if ($cStartIndex -lt 0 -or $cEndIndex -le $cStartIndex) {
    throw "Could not find Codex multi-account block markers in profile: $LocalProfile"
}
$cEndExclusive = $cEndIndex + $addAccountEnd.Length
$codexBlock = $profileRaw.Substring($cStartIndex, $cEndExclusive - $cStartIndex)
New-Item -ItemType Directory -Force -Path $targetCodexProfilesDir | Out-Null
Set-Content -Path $targetCodexProfileScript -Encoding UTF8 -Value $codexBlock
Write-Host "Synced Codex multi-account profile block from local profile."

# Sync codex-profiles files
foreach ($name in @("profiles.json", "README.md", "QUICKSTART.md")) {
    $src = Join-Path $LocalCodexProfilesDir $name
    if (Test-Path $src) {
        Copy-Item -Path $src -Destination (Join-Path $targetCodexProfilesDir $name) -Force
        Write-Host "Synced $name from local .codex-profiles"
    }
}

$skillScript = Join-Path $targetSkillDir "scripts\ralph_loop.py"
python -m py_compile $skillScript
Write-Host "Validated python syntax: $skillScript"

Write-Host ""
Write-Host "Update complete. Review changes and commit to GitHub."
