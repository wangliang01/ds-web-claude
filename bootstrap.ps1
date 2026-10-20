# ds-web for Claude Code - remote bootstrap (no git required).
#   irm https://raw.githubusercontent.com/wangliang01/ds-web-claude/main/bootstrap.ps1 | iex
$ErrorActionPreference = "Stop"

$Repo   = "wangliang01/ds-web-claude"
$Branch = "main"
$ZipUrl = "https://codeload.github.com/$Repo/zip/refs/heads/$Branch"

$tmp = Join-Path $env:TEMP ("ds-web-claude-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $tmp | Out-Null
$zip = Join-Path $tmp "src.zip"

Write-Host "downloading $ZipUrl"
Invoke-WebRequest -Uri $ZipUrl -OutFile $zip -UseBasicParsing
Expand-Archive -Path $zip -DestinationPath $tmp -Force

$root = Get-ChildItem $tmp -Directory |
        Where-Object { Test-Path (Join-Path $_.FullName "install.ps1") } |
        Select-Object -First 1
if (-not $root) { throw "install.ps1 not found in downloaded archive" }

& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root.FullName "install.ps1")

Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue