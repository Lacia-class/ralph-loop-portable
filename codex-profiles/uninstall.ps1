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

    if (-not (Test-Path $ProfilePath)) { return }

    $raw = Get-Content -Raw -Encoding UTF8 $ProfilePath
    if ($null -eq $raw) { $raw = "" }
    $startIndex = $raw.IndexOf($BlockStart)
    $endIndex = $raw.IndexOf($BlockEnd)
    if ($startIndex -lt 0 -or $endIndex -le $startIndex) { return }

    $endExclusive = $endIndex + $BlockEnd.Length
    $prefix = $raw.Substring(0, $startIndex).TrimEnd("`r", "`n")
    $suffix = $raw.Substring($endExclusive).TrimStart("`r", "`n")

    $newBody = ""
    if ($prefix) { $newBody += $prefix }
    if ($suffix) {
        if ($newBody) { $newBody += "`r`n`r`n" }
        $newBody += $suffix
    }
    Set-Content -Path $ProfilePath -Encoding UTF8 -Value $newBody
    Write-Host "Removed profile block from: $ProfilePath"
}

$blockStart = "# >>> codex-profiles-portable >>>"
$blockEnd = "# <<< codex-profiles-portable <<<"

$profileTargets = @(
    (Join-Path $env:USERPROFILE "Documents\WindowsPowerShell\Microsoft.PowerShell_profile.ps1"),
    (Join-Path $env:USERPROFILE "Documents\PowerShell\Microsoft.PowerShell_profile.ps1")
)

foreach ($profilePath in $profileTargets) {
    Remove-ProfileBlock -ProfilePath $profilePath -BlockStart $blockStart -BlockEnd $blockEnd
}

$sharedScript = Join-Path $env:USERPROFILE ".codex\codex-profiles\codex-multi-account.profile.ps1"
if (Test-Path $sharedScript) {
    Remove-Item -Path $sharedScript -Force
    Write-Host "Removed: $sharedScript"
}

$profilesDir = Join-Path $env:USERPROFILE ".codex-profiles"
if ($RemoveProfilesDir -and (Test-Path $profilesDir)) {
    Remove-Item -Path $profilesDir -Recurse -Force
    Write-Host "Removed: $profilesDir"
}

Write-Host ""
Write-Host "Codex multi-account uninstall complete."
