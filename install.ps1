# HTB Helper bootstrap for Windows HTB lab VMs.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

function Have-Cmd($name) {
    return [bool](Get-Command $name -ErrorAction SilentlyContinue)
}

if (-not (Have-Cmd python)) {
    Write-Host "[*] Python not found. Trying winget..."
    if (Have-Cmd winget) {
        winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
    } else {
        Write-Host "[-] Install Python 3.9+ from python.org and re-run."
        exit 1
    }
}

if (-not (Have-Cmd nmap)) {
    Write-Host "[!] nmap is not on PATH. On Windows HTB labs it is often already installed."
    Write-Host "    If missing: winget install -e --id Insecure.Nmap"
}

if (-not (Test-Path (Join-Path $Root "config.json")) -and (Test-Path (Join-Path $Root "config.example.json"))) {
    Copy-Item (Join-Path $Root "config.example.json") (Join-Path $Root "config.json")
}

$launcher = Join-Path $env:USERPROFILE "htb.cmd"
@"
@echo off
cd /d "$Root"
python htb_app.py %*
"@ | Set-Content -Path $launcher -Encoding ASCII
Write-Host "[+] Launcher: $launcher"

$startDir = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
New-Item -ItemType Directory -Force -Path $startDir | Out-Null
$ws = New-Object -ComObject WScript.Shell
$lnk = $ws.CreateShortcut((Join-Path $startDir "HTB Helper.lnk"))
$lnk.TargetPath = "python"
$lnk.Arguments = "`"$Root\htb_app.py`" --gui-only"
$lnk.WorkingDirectory = $Root
$lnk.Hotkey = "Ctrl+Alt+H"
$lnk.WindowStyle = 1
$lnk.Save()
Write-Host "[+] Start Menu shortcut with hotkey Ctrl+Alt+H"

Write-Host ""
Write-Host "Run:"
Write-Host "  cd $Root"
Write-Host "  .\htb.cmd"
Write-Host "  .\htb.cmd --gui-only"
