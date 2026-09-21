Write-Host "CrownWatch -> Git-ready data migration" -ForegroundColor Cyan
$old = Read-Host "Paste the full path to your existing crownwatch.db FILE"
if (!(Test-Path $old -PathType Leaf)) {
    Write-Host "That is not a valid database file." -ForegroundColor Red
    exit 1
}
$dataDir = Join-Path $PSScriptRoot "data"
New-Item -ItemType Directory -Force -Path $dataDir | Out-Null
$dest = Join-Path $dataDir "crownwatch.db"
Copy-Item $old $dest -Force
Write-Host "History copied to data\crownwatch.db" -ForegroundColor Green
Write-Host "This database is ignored by Git, so updates will not overwrite it." -ForegroundColor Green
