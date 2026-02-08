[CmdletBinding()]
param(
    [string]$RepoRoot = "",
    [switch]$NoRalphSkill,
    [switch]$NoRalphProfile,
    [switch]$NoCodexProfiles,
    [switch]$NoCodexProfile,
    [switch]$ForceProfilesJson
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

function Ensure-ParentDir {
    param([Parameter(Mandatory = $true)][string]$Path)
    $parent = Split-Path -Parent $Path
    if ($parent -and -not (Test-Path $parent)) {
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
    }
}

function Ensure-ProfileBlock {
    param(
        [Parameter(Mandatory = $true)][string]$ProfilePath,
        [Parameter(Mandatory = $true)][string]$BlockStart,
        [Parameter(Mandatory = $true)][string]$BlockEnd,
        [Parameter(Mandatory = $true)][string]$BlockText
    )

    Ensure-ParentDir -Path $ProfilePath
    if (-not (Test-Path $ProfilePath)) {
        New-Item -ItemType File -Path $ProfilePath -Force | Out-Null
    }

    $raw = Get-Content -Raw -Encoding UTF8 $ProfilePath
    if ($null -eq $raw) { $raw = "" }
    $startIndex = $raw.IndexOf($BlockStart)
    $endIndex = $raw.IndexOf($BlockEnd)

    if ($startIndex -ge 0 -and $endIndex -gt $startIndex) {
        $endExclusive = $endIndex + $BlockEnd.Length
        $prefix = $raw.Substring(0, $startIndex).TrimEnd("`r", "`n")
        $suffix = $raw.Substring($endExclusive).TrimStart("`r", "`n")
        $rebuilt = ""
        if ($prefix) { $rebuilt += $prefix + "`r`n`r`n" }
        $rebuilt += $BlockText.TrimEnd("`r", "`n")
        if ($suffix) { $rebuilt += "`r`n`r`n" + $suffix }
        Set-Content -Path $ProfilePath -Encoding UTF8 -Value $rebuilt
        return
    }

    if ($raw -and -not $raw.EndsWith("`n")) { $raw += "`r`n" }
    $newBody = $raw
    if ($newBody -and -not $newBody.EndsWith("`n`n")) { $newBody += "`r`n" }
    $newBody += $BlockText.TrimEnd("`r", "`n") + "`r`n"
    Set-Content -Path $ProfilePath -Encoding UTF8 -Value $newBody
}

$resolvedRepoRoot = (Resolve-Path $RepoRoot).Path
$expectedCodexInstaller = Join-Path $resolvedRepoRoot "codex-profiles\install.ps1"
if (-not (Test-Path $expectedCodexInstaller) -and $PSCommandPath) {
    $fallbackRoot = Split-Path -Parent $PSCommandPath
    if (Test-Path (Join-Path $fallbackRoot "codex-profiles\install.ps1")) {
        $resolvedRepoRoot = $fallbackRoot
    }
}

# ---- Install Ralph Loop skill and shortcuts ----
$sourceSkillDir = Join-Path $resolvedRepoRoot "skills\ralph-loop"
$sourceRalphProfile = Join-Path $resolvedRepoRoot "profile\ralph-loop.profile.ps1"
$targetSkillDir = Join-Path $env:USERPROFILE ".codex\skills\ralph-loop"
$targetRalphProfile = Join-Path $env:USERPROFILE ".codex\ralph-loop\ralph-loop.profile.ps1"

if ((-not $NoRalphSkill) -or (-not $NoRalphProfile)) {
    if (-not (Test-Path $sourceSkillDir)) {
        throw "Missing source skill folder: $sourceSkillDir"
    }
    if (-not (Test-Path $sourceRalphProfile)) {
        throw "Missing source profile script: $sourceRalphProfile"
    }
}

if (-not $NoRalphSkill) {
    Ensure-ParentDir -Path $targetSkillDir
    if (Test-Path $targetSkillDir) {
        Remove-Item -Path $targetSkillDir -Recurse -Force
    }
    Copy-Item -Path $sourceSkillDir -Destination (Split-Path -Parent $targetSkillDir) -Recurse -Force
    Write-Host "Installed Ralph skill -> $targetSkillDir"
}

if (-not $NoRalphProfile) {
    Ensure-ParentDir -Path $targetRalphProfile
    Copy-Item -Path $sourceRalphProfile -Destination $targetRalphProfile -Force

    $blockStart = "# >>> ralph-loop-portable >>>"
    $blockEnd = "# <<< ralph-loop-portable <<<"
    $sourceLine = '. "{0}"' -f $targetRalphProfile.Replace('"', '`"')
    $blockText = @(
        $blockStart
        $sourceLine
        $blockEnd
    ) -join "`r`n"

    $profileTargets = @(
        (Join-Path $env:USERPROFILE "Documents\WindowsPowerShell\Microsoft.PowerShell_profile.ps1"),
        (Join-Path $env:USERPROFILE "Documents\PowerShell\Microsoft.PowerShell_profile.ps1")
    )

    foreach ($profilePath in $profileTargets) {
        Ensure-ProfileBlock -ProfilePath $profilePath -BlockStart $blockStart -BlockEnd $blockEnd -BlockText $blockText
        Write-Host "Updated profile (Ralph block): $profilePath"
    }
}

# ---- Install Codex multi-account module ----
if (-not $NoCodexProfiles) {
    $codexProfilesInstall = Join-Path $resolvedRepoRoot "codex-profiles\install.ps1"
    if (-not (Test-Path $codexProfilesInstall)) {
        throw "Missing codex-profiles installer: $codexProfilesInstall"
    }

    $cpParams = @{
        SourceDir = (Join-Path $resolvedRepoRoot "codex-profiles")
    }
    if ($NoCodexProfile) { $cpParams.NoProfile = $true }
    if ($ForceProfilesJson) { $cpParams.ForceProfilesJson = $true }

    & $codexProfilesInstall @cpParams
}

Write-Host ""
Write-Host "Install complete."
Write-Host "Run: . `$PROFILE"
