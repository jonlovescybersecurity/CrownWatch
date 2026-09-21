$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "CrownWatch updater" -ForegroundColor Cyan

if (!(Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host "Git is not installed or is not in PATH." -ForegroundColor Red
    exit 1
}

if (!(Test-Path ".git")) {
    Write-Host "This CrownWatch folder is not connected to GitHub yet." -ForegroundColor Yellow
    Write-Host "Run .\connect-github.ps1 first."
    exit 1
}

Write-Host "Checking for updates..." -ForegroundColor DarkGray
git pull --ff-only
if ($LASTEXITCODE -ne 0) {
    Write-Host "Git update failed. CrownWatch was not modified." -ForegroundColor Red
    exit $LASTEXITCODE
}

Write-Host "Starting CrownWatch..." -ForegroundColor Green
python app.py
