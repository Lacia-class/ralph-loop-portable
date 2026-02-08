[CmdletBinding()]
param(
    [switch]$RemoveProfilesDir
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Remove-ProfileBlock {
    param(
        [Parameter(Mandatory = $true)][string]$ProfilePath,
        [Parameter(Mandatory = $true)][string]$BlockStart,
        [Parameter(Mandatory = $true)][string]$BlockEnd
    )

    if (-not (Test-Path $ProfilePath)) {
        return
    }

    $raw = Get-Content -Raw -Encoding UTF8 $ProfilePath
    if ($null -eq $raw) { $raw = "" }
    $startIndex = $raw.IndexOf($BlockStart)
    $endIndex = $raw.IndexOf($BlockEnd)
    if ($startIndex -lt 0 -or $endIndex -le $startIndex) {
        return
    }

    $endExclusive = $endIndex + $BlockEnd.Length
    $prefix = $raw.Substring(0, $startIndex).TrimEnd("`r", "`n")
    $suffix = $raw.Substring($endExclusive).TrimStart("`r", "`n")
    $newBody = ""
    if ($prefix) {
        $newBody += $prefix
    }
    if ($suffix) {
        if ($newBody) {
            $newBody += "`r`n`r`n"
        }
        $newBody += $suffix
    }
    Set-Content -Path $ProfilePath -Encoding UTF8 -Value $newBody
    Write-Host "Removed profile block from: $ProfilePath"
}

$blockStart = "# >>> ralph-loop-portable >>>"
$blockEnd = "# <<< ralph-loop-portable <<<"

$profileTargets = @(
    (Join-Path $env:USERPROFILE "Documents\WindowsPowerShell\Microsoft.PowerShell_profile.ps1"),
    (Join-Path $env:USERPROFILE "Documents\PowerShell\Microsoft.PowerShell_profile.ps1")
)

foreach ($profilePath in $profileTargets) {
    Remove-ProfileBlock -ProfilePath $profilePath -BlockStart $blockStart -BlockEnd $blockEnd
}

$targetSkillDir = Join-Path $env:USERPROFILE ".codex\skills\ralph-loop"
$targetProfileScript = Join-Path $env:USERPROFILE ".codex\ralph-loop\ralph-loop.profile.ps1"

if (Test-Path $targetSkillDir) {
    Remove-Item -Path $targetSkillDir -Recurse -Force
    Write-Host "Removed: $targetSkillDir"
}
if (Test-Path $targetProfileScript) {
    Remove-Item -Path $targetProfileScript -Force
    Write-Host "Removed: $targetProfileScript"
}

$codexProfilesUninstall = Join-Path $PSScriptRoot "codex-profiles\uninstall.ps1"
if (Test-Path $codexProfilesUninstall) {
    $cpParams = @{}
    if ($RemoveProfilesDir) { $cpParams.RemoveProfilesDir = $true }
    & $codexProfilesUninstall @cpParams
}

Write-Host ""
Write-Host "Uninstall complete."
