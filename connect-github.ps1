$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "" 
Write-Host "CrownWatch GitHub setup" -ForegroundColor Cyan
Write-Host "Create an EMPTY GitHub repository first (no README, .gitignore, or license)."
Write-Host "Then paste its HTTPS URL below, e.g. https://github.com/USERNAME/CrownWatch.git"
Write-Host ""
$remote = Read-Host "GitHub repository URL"
if ([string]::IsNullOrWhiteSpace($remote)) {
    Write-Host "No URL entered." -ForegroundColor Yellow
    exit 1
}

if (!(Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host "Git is not installed or is not in PATH." -ForegroundColor Red
    Write-Host "Install Git for Windows, reopen PowerShell, and run this script again."
    exit 1
}

if (!(Test-Path ".git")) {
    git init
}

git branch -M main

$hasRemote = git remote 2>$null | Select-String -SimpleMatch "origin"
if ($hasRemote) {
    git remote set-url origin $remote
} else {
    git remote add origin $remote
}

# Protect local persistent data before the first commit.
git add .
git status --short

$hasHead = $true
try { git rev-parse --verify HEAD *> $null } catch { $hasHead = $false }
if (!$hasHead) {
    git commit -m "CrownWatch V1.1 git-ready baseline"
} else {
    $changes = git status --porcelain
    if ($changes) {
        git commit -m "Prepare CrownWatch Git update workflow"
    }
}

git push -u origin main
Write-Host ""
Write-Host "Connected. Future CrownWatch updates can now come through Git." -ForegroundColor Green
Write-Host "Use .\update-and-run.ps1 from now on." -ForegroundColor Green
