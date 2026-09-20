# Build ModBridge on Windows (PowerShell).
#   powershell -ExecutionPolicy Bypass -File packaging/build_windows.ps1
$ErrorActionPreference = "Stop"
$ROOT = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $ROOT
pip install --upgrade pip
pip install -r requirements.txt pyinstaller
pyinstaller --noconfirm --clean --onefile --windowed --name ModBridge `
  --icon assets/icon.ico `
  --add-data "modrinth_app/locales;modrinth_app/locales" `
  --add-data "assets;assets" `
  main.py
Write-Host ("Done: " + $ROOT + "\dist\ModBridge.exe")
