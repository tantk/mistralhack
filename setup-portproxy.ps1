# Run this script in PowerShell as Administrator
# Sets up port forwarding from Windows host to WSL2 for the Voxtral server

$WSL_IP = "172.17.157.143"
$PORT = 8080

Write-Host "Setting up port forwarding: Windows:$PORT -> WSL2($WSL_IP):$PORT"

# Add port forward
netsh interface portproxy add v4tov4 listenport=$PORT listenaddress=0.0.0.0 connectport=$PORT connectaddress=$WSL_IP

# Open Windows firewall for the port
netsh advfirewall firewall add rule name="Voxtral STT" dir=in action=allow protocol=tcp localport=$PORT

# Verify
Write-Host "`nPort proxy rules:"
netsh interface portproxy show all

Write-Host "`nDone! LAN machines can now access the Voxtral server at http://<YOUR_WINDOWS_IP>:$PORT"
