# HiveMind GitHub Push Script
# Run this in PowerShell (right-click → Run with PowerShell)
# It will open a GitHub login prompt if you haven't authenticated yet

$ErrorActionPreference = "Stop"

$repoPath = "C:\Users\Administrator\WorkBuddy\2026-07-01-13-51-12\HiveMind_repo"

Write-Host "======================================" -ForegroundColor Cyan
Write-Host "  HiveMind v0.1 → GitHub Push" -ForegroundColor Cyan
Write-Host "======================================" -ForegroundColor Cyan
Write-Host ""

# Set credential helper to Windows Credential Manager
git config --global credential.helper manager

# Navigate to repo
Set-Location $repoPath

# Check status
Write-Host "Current branch:" -ForegroundColor Yellow
git branch --show-current

Write-Host "Commits ahead of origin:" -ForegroundColor Yellow
git log origin/main..HEAD --oneline

Write-Host ""
Write-Host "Pushing to https://github.com/kazei0147-prog/HiveMind ..." -ForegroundColor Green
Write-Host "(If prompted, enter your GitHub credentials in the popup window)" -ForegroundColor Yellow
Write-Host ""

git push origin main

Write-Host ""
if ($LASTEXITCODE -eq 0) {
    Write-Host "Push SUCCESS! Check your repo at:" -ForegroundColor Green
    Write-Host "https://github.com/kazei0147-prog/HiveMind" -ForegroundColor Green
} else {
    Write-Host "Push FAILED. Error code: $LASTEXITCODE" -ForegroundColor Red
    Write-Host "Try manually: cd $repoPath && git push origin main" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Press any key to exit..."
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
