Write-Host "CrownWatch API setup" -ForegroundColor Cyan
$token = Read-Host "Paste your Supercell Clash Royale developer API token"
if ([string]::IsNullOrWhiteSpace($token)) { exit }
[Environment]::SetEnvironmentVariable("CLASH_ROYALE_TOKEN", $token, "User")
$env:CLASH_ROYALE_TOKEN = $token
Write-Host "Saved. Restart CrownWatch with: python app.py" -ForegroundColor Green
