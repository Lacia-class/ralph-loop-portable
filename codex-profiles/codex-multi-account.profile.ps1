# ========== Codex Multi-Account Launcher ==========
function codexp {
  [CmdletBinding()]
  param(
    [string]$Name,
    [switch]$List,
    [switch]$NewWindow,
    [switch]$All
  )

  $profilesPath = "$env:USERPROFILE\.codex-profiles\profiles.json"
  if (!(Test-Path $profilesPath)) { throw "Profiles file not found: $profilesPath" }

  $profiles = Get-Content $profilesPath -Raw | ConvertFrom-Json

  # Compatibility: allow `cdx list` in addition to `cdx -List`.
  if ($Name -and -not $List -and -not $NewWindow -and -not $All) {
    $nameNorm = $Name.Trim().ToLowerInvariant()
    if ($nameNorm -eq "list") {
      $List = $true
      $Name = ""
    }
  }
  
  # Shared resources from main .codex folder
  $mainCodexHome = "$env:USERPROFILE\.codex"
  $sharedFolders = @("skills")
  $sharedFiles = @("config.toml", "AGENTS.md")

  # -List: show all account names
  if ($List) {
    $profiles | ForEach-Object { $_.name }
    return
  }

  # Helper function to setup shared resources (junction for folders, hardlink for files)
  function Setup-SharedLinks($targetDir) {
    New-Item -ItemType Directory -Force $targetDir | Out-Null
    
    # Junction for folders (no admin needed)
    foreach ($folder in $sharedFolders) {
      $source = Join-Path $mainCodexHome $folder
      $target = Join-Path $targetDir $folder
      
      if ((Test-Path $source) -and !(Test-Path $target)) {
        cmd /c mklink /J "$target" "$source" | Out-Null
      }
    }
    
    # Hardlink for files (no admin needed)
    foreach ($file in $sharedFiles) {
      $source = Join-Path $mainCodexHome $file
      $target = Join-Path $targetDir $file
      
      if ((Test-Path $source) -and !(Test-Path $target)) {
        cmd /c mklink /H "$target" "$source" | Out-Null
      }
    }
  }

  # -All: launch all accounts in new windows
  if ($All) {
    foreach ($p in $profiles) {
      $codexHome = [Environment]::ExpandEnvironmentVariables($p.home)
      Setup-SharedLinks $codexHome
      $cmd = '$env:CODEX_HOME="{0}"; codex --dangerously-bypass-approvals-and-sandbox {1}' -f $codexHome, ($args -join ' ')
      Start-Process pwsh -ArgumentList @('-NoExit', '-Command', $cmd)
      Write-Host "Launched: $($p.name)"
    }
    return
  }

  # Select profile
  $p = $null
  if (-not $Name) {
    # Numeric menu
    for ($i=0; $i -lt $profiles.Count; $i++) {
      "{0,2}. {1}" -f $i, $profiles[$i].name
    }
    $choice = Read-Host "Choose a profile number"
    if ($choice -notmatch '^\d+$' -or [int]$choice -ge $profiles.Count) { throw "Invalid choice." }
    $p = $profiles[[int]$choice]
  } else {
    # Fuzzy match
    $matched = $profiles | Where-Object { $_.name -like "*$Name*" }
    if ($matched.Count -eq 0) { throw "Profile '$Name' not found. Use: codexp -List" }
    if ($matched.Count -gt 1) {
      "Multiple matches:"
      $matched | ForEach-Object { " - " + $_.name }
      throw "Be more specific."
    }
    $p = $matched | Select-Object -First 1
  }

  $codexHome = [Environment]::ExpandEnvironmentVariables($p.home)
  Setup-SharedLinks $codexHome

  # Pass remaining args to codex
  $rest = $args

  if ($NewWindow) {
    $cmd = '$env:CODEX_HOME="{0}"; codex --dangerously-bypass-approvals-and-sandbox {1}' -f $codexHome, ($rest -join ' ')
    Start-Process pwsh -ArgumentList @('-NoExit', '-Command', $cmd)
  } else {
    $env:CODEX_HOME = $codexHome
    codex --dangerously-bypass-approvals-and-sandbox @rest
  }
}

Set-Alias cdx codexp
# ========== End Codex Launcher ==========

# ========== Add New Codex Account ==========
function Add-CodexAccount {
  param([Parameter(Mandatory=$true)][string]$AccountName)
  
  $profilesPath = "$env:USERPROFILE\.codex-profiles\profiles.json"
  $profiles = Get-Content $profilesPath -Raw | ConvertFrom-Json
  
  # Check if account already exists
  if ($profiles | Where-Object { $_.name -eq $AccountName }) {
    Write-Host "Account '$AccountName' already exists!" -ForegroundColor Yellow
    return
  }
  
  # Add new account
  $newAccount = @{
    name = $AccountName
    home = "%USERPROFILE%\.codex-$AccountName"
  }
  
  $profiles = @($profiles) + $newAccount
  $profiles | ConvertTo-Json | Out-File -FilePath $profilesPath -Encoding UTF8
  
  Write-Host "Account '$AccountName' added! Use: cdx $AccountName" -ForegroundColor Green
}

Set-Alias addcdx Add-CodexAccount
# ========== End Add Account ==========
