[CmdletBinding()]
param(
    [string]$SourceDir = "",
    [switch]$NoProfile,
    [switch]$ForceProfilesJson
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (-not $SourceDir) {
    if ($PSCommandPath) {
        $SourceDir = Split-Path -Parent $PSCommandPath
    } elseif ($PSScriptRoot) {
        $SourceDir = $PSScriptRoot
    } else {
        $SourceDir = (Get-Location).Path
    }
}

function Ensure-ParentDir {
    param([Parameter(Mandatory = $true)][string]$Path)
    $parent = Split-Path -Parent $Path
    if ($parent -and -not (Test-Path $parent)) {
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
    }
}

function Same-Path {
    param(
        [Parameter(Mandatory = $true)][string]$A,
        [Parameter(Mandatory = $true)][string]$B
    )
    try {
        $aFull = [System.IO.Path]::GetFullPath($A)
        $bFull = [System.IO.Path]::GetFullPath($B)
        return [string]::Equals($aFull, $bFull, [System.StringComparison]::OrdinalIgnoreCase)
    } catch {
        return $false
    }
}

function Copy-IfDifferent {
    param(
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$Destination
    )
    if (Same-Path -A $Source -B $Destination) {
        return
    }
    Copy-Item -Force $Source $Destination
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

function Remove-OptionalBlock {
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
    $rebuilt = ""
    if ($prefix) { $rebuilt += $prefix }
    if ($suffix) {
        if ($rebuilt) { $rebuilt += "`r`n`r`n" }
        $rebuilt += $suffix
    }
    Set-Content -Path $ProfilePath -Encoding UTF8 -Value $rebuilt
    Write-Host "Removed legacy tab-title/cd block from: $ProfilePath"
}

$resolvedSourceDir = (Resolve-Path $SourceDir).Path
$expectedProfileScript = Join-Path $resolvedSourceDir "codex-multi-account.profile.ps1"
if (-not (Test-Path $expectedProfileScript) -and $PSCommandPath) {
    $fallbackSource = Split-Path -Parent $PSCommandPath
    if (Test-Path (Join-Path $fallbackSource "codex-multi-account.profile.ps1")) {
        $resolvedSourceDir = $fallbackSource
    }
}
$sourceProfilesJson = Join-Path $resolvedSourceDir "profiles.json"
$sourceReadme = Join-Path $resolvedSourceDir "README.md"
$sourceQuickstart = Join-Path $resolvedSourceDir "QUICKSTART.md"
$sourceInstall = Join-Path $resolvedSourceDir "install.ps1"
$sourceProfileScript = Join-Path $resolvedSourceDir "codex-multi-account.profile.ps1"

if (-not (Test-Path $sourceProfileScript)) {
    $fallbackProfileScript = Join-Path $env:USERPROFILE ".codex\codex-profiles\codex-multi-account.profile.ps1"
    if (Test-Path $fallbackProfileScript) {
        $sourceProfileScript = $fallbackProfileScript
    }
}

foreach ($path in @($sourceProfilesJson, $sourceReadme, $sourceQuickstart, $sourceInstall, $sourceProfileScript)) {
    if (-not (Test-Path $path)) {
        throw "Missing required file in source dir: $path"
    }
}

$targetProfilesDir = Join-Path $env:USERPROFILE ".codex-profiles"
$targetProfilesJson = Join-Path $targetProfilesDir "profiles.json"
$targetReadme = Join-Path $targetProfilesDir "README.md"
$targetQuickstart = Join-Path $targetProfilesDir "QUICKSTART.md"
$targetInstall = Join-Path $targetProfilesDir "install.ps1"
$targetSourceProfileScript = Join-Path $targetProfilesDir "codex-multi-account.profile.ps1"

New-Item -ItemType Directory -Force -Path $targetProfilesDir | Out-Null
Copy-IfDifferent -Source $sourceReadme -Destination $targetReadme
Copy-IfDifferent -Source $sourceQuickstart -Destination $targetQuickstart
Copy-IfDifferent -Source $sourceInstall -Destination $targetInstall
Copy-IfDifferent -Source $sourceProfileScript -Destination $targetSourceProfileScript

if ($ForceProfilesJson -or -not (Test-Path $targetProfilesJson)) {
    Copy-IfDifferent -Source $sourceProfilesJson -Destination $targetProfilesJson
    Write-Host "Installed profiles.json -> $targetProfilesJson"
} else {
    Write-Host "Kept existing profiles.json: $targetProfilesJson"
}

$targetSharedProfileScript = Join-Path $env:USERPROFILE ".codex\codex-profiles\codex-multi-account.profile.ps1"
Ensure-ParentDir -Path $targetSharedProfileScript
Copy-Item -Force $sourceProfileScript $targetSharedProfileScript
Write-Host "Installed codex profile script -> $targetSharedProfileScript"

if (-not $NoProfile) {
    $blockStart = "# >>> codex-profiles-portable >>>"
    $blockEnd = "# <<< codex-profiles-portable <<<"
    $sourceLine = '. "{0}"' -f $targetSharedProfileScript.Replace('"', '`"')
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
        # Legacy cleanup: remove old tab-title block that overwrote `cd`.
        Remove-OptionalBlock `
            -ProfilePath $profilePath `
            -BlockStart "# ========== Auto Set Tab Title to Current Folder ==========" `
            -BlockEnd "# ========== End Tab Title =========="
        Ensure-ProfileBlock -ProfilePath $profilePath -BlockStart $blockStart -BlockEnd $blockEnd -BlockText $blockText
        Write-Host "Updated profile: $profilePath"
    }
}

Write-Host ""
Write-Host "Codex multi-account install complete."
Write-Host "Run: . `$PROFILE"
