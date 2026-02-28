# update-portproxy.ps1
# Updates the Windows port proxy to point to the current WSL2 IP address.
# Run as Administrator after WSL restarts (the WSL2 IP can change on reboot).
#
# Usage: Right-click -> Run with PowerShell (as Admin)
#   or:  powershell -ExecutionPolicy Bypass -File update-portproxy.ps1

$Ports = @(8080, 8001)

# Get the current WSL2 IP
$WslIp = (wsl hostname -I).Trim().Split(" ")[0]

if (-not $WslIp) {
    Write-Host "ERROR: Could not determine WSL2 IP address. Is WSL running?" -ForegroundColor Red
    exit 1
}

Write-Host "Current WSL2 IP: $WslIp" -ForegroundColor Cyan

foreach ($Port in $Ports) {
    # Remove existing port proxy rule (ignore errors if it doesn't exist)
    netsh interface portproxy delete v4tov4 listenport=$Port listenaddress=0.0.0.0 2>$null

    # Add updated port proxy rule
    netsh interface portproxy add v4tov4 listenport=$Port listenaddress=0.0.0.0 connectport=$Port connectaddress=$WslIp

    if ($LASTEXITCODE -eq 0) {
        Write-Host "OK: Port $Port forwarded to WSL2 at $WslIp" -ForegroundColor Green
    } else {
        Write-Host "FAIL: Could not update port proxy for port $Port" -ForegroundColor Red
    }
}

# Show current rules
Write-Host "`nCurrent port proxy rules:" -ForegroundColor Yellow
netsh interface portproxy show all
