# ds-web for Claude Code - one-shot installer (new machine)
# Usage: right-click > Run with PowerShell, or:
#   powershell -ExecutionPolicy Bypass -File install.ps1
$ErrorActionPreference = "Stop"

$PluginRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ClaudeDir  = Join-Path $env:USERPROFILE ".claude"
$Port       = 15722
$Upstream   = "http://127.0.0.1:15721"

function Say($m) { Write-Host $m }

# --- 1. locate python -------------------------------------------------------
$py = $null
foreach ($c in @("C:\Program Files\Python311\python.exe")) {
  if (Test-Path $c) { $py = $c; break }
}
if (-not $py) {
  $cmd = Get-Command python.exe -ErrorAction SilentlyContinue
  if ($cmd) { $py = $cmd.Source }
}
if (-not $py) { throw "Python 3 not found. Install Python 3.11+ and re-run." }
Say "python: $py"

$pyw = Join-Path (Split-Path -Parent $py) "pythonw.exe"
if (-not (Test-Path $pyw)) { $pyw = $py }

# --- 2. install proxy -------------------------------------------------------
New-Item -ItemType Directory -Force -Path $ClaudeDir | Out-Null
$proxySrc = Join-Path $PluginRoot "proxy\ds-web-proxy.py"
$proxyDst = Join-Path $ClaudeDir "ds-web-proxy.py"
Copy-Item $proxySrc $proxyDst -Force
Say "proxy -> $proxyDst"

# --- 3. settings.json: point Claude Code at the proxy ----------------------
# NOTE: never name a variable `$env` here - it is a PowerShell automatic variable.
$settingsPath = Join-Path $ClaudeDir "settings.json"
if (Test-Path $settingsPath) {
  $settings = Get-Content $settingsPath -Raw | ConvertFrom-Json
} else {
  $settings = [pscustomobject]@{}
}
if (-not ($settings.PSObject.Properties.Name -contains "env")) {
  $settings | Add-Member -NotePropertyName "env" -NotePropertyValue ([pscustomobject]@{}) -Force
}
$settingsEnv = $settings.env
if (-not $settingsEnv) {
  $settingsEnv = [pscustomobject]@{}
  $settings.env = $settingsEnv
}
$pairs = [ordered]@{
  ANTHROPIC_AUTH_TOKEN = "PROXY_MANAGED"
  ANTHROPIC_BASE_URL   = "http://127.0.0.1:$Port"
}
foreach ($k in $pairs.Keys) {
  if ($settingsEnv.PSObject.Properties.Name -contains $k) {
    $settingsEnv.$k = $pairs[$k]
  } else {
    $settingsEnv | Add-Member -NotePropertyName $k -NotePropertyValue $pairs[$k]
  }
}
$settings | ConvertTo-Json -Depth 32 | Set-Content $settingsPath -Encoding UTF8
Say "settings.json -> ANTHROPIC_BASE_URL = http://127.0.0.1:$Port"

# --- 4. autostart at login --------------------------------------------------
$startup = [Environment]::GetFolderPath("Startup")
$autoCmd = Join-Path $startup "ds-web-proxy.cmd"
@"
@echo off
rem Autostart the ds-web repair proxy (port $Port) at login.
set "DSWEB_UPSTREAM=$Upstream"
set "DSWEB_PORT=$Port"
start "" /b "$pyw" "%USERPROFILE%\.claude\ds-web-proxy.py"
"@ | Set-Content $autoCmd -Encoding ASCII
Say "autostart -> $autoCmd"

# --- 5. start it now (skip if already listening) ----------------------------
$env:DSWEB_UPSTREAM = $Upstream
$env:DSWEB_PORT = "$Port"
$already = $false
try { $null = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/" -TimeoutSec 2 -UseBasicParsing; $already = $true } catch { }
if ($already) {
  Say "proxy: already listening on $Port, not starting a second copy"
} else {
  Start-Process -FilePath $pyw -ArgumentList "`"$proxyDst`"" -WindowStyle Hidden
  Start-Sleep -Seconds 2
}
try {
  $r = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/" -TimeoutSec 5 -UseBasicParsing
  Say "proxy health: $($r.Content)"
} catch {
  Say "WARN: proxy not answering on $Port yet - check $ClaudeDir\ds-web-proxy.py manually"
}

# --- 6. plugin: stage repo to a persistent path, then register ---------------
# The marketplace source must outlive this script (bootstrap runs from a temp
# dir it deletes), so always register from ~\.claude\ds-web-plugin.
$PersistRoot = Join-Path $ClaudeDir "ds-web-plugin"
if ($PersistRoot.TrimEnd("\") -ne $PluginRoot.TrimEnd("\")) {
  New-Item -ItemType Directory -Force -Path $PersistRoot | Out-Null
  $rc = Start-Process -FilePath "robocopy.exe" -Wait -PassThru -WindowStyle Hidden `
        -ArgumentList @("`"$PluginRoot`"", "`"$PersistRoot`"", "/E", "/XD", ".git", "/NFL", "/NDL", "/NJH", "/NJS", "/NP")
  if ($rc.ExitCode -ge 8) { throw "robocopy failed staging plugin (exit $($rc.ExitCode))" }
}
Say "plugin staged -> $PersistRoot"

$claude = Get-Command claude -ErrorAction SilentlyContinue
if (-not $claude) {
  Say "WARN: claude CLI not found on PATH; install Claude Code, then run:"
  Say "  claude plugin marketplace add `"$PersistRoot`""
  Say "  claude plugin install ds-web@ds-web-local"
  return
}
$market = "ds-web-local"
& claude plugin marketplace add $PersistRoot 2>&1 | Out-Null
& claude plugin install "ds-web@$market" 2>&1 | Out-Null
Say "plugin: ds-web@$market installed (if it failed, run: claude plugin install ds-web@$market)"

Say ""
Say "Done. Restart Claude Code so it picks up ANTHROPIC_BASE_URL."
Say "Verify:  claude -p `"用 Bash 工具跑 echo OK 并原样报告`""