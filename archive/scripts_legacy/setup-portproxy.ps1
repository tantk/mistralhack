# Run this script in PowerShell as Administrator
# Sets up port forwarding from Windows host to WSL2 for Voxtral + GPU services

$WSL_IP = "172.17.157.143"

# Port 8080: Voxtral transcription server
Write-Host "Setting up port forwarding: Windows:8080 -> WSL2($WSL_IP):8080"
netsh interface portproxy add v4tov4 listenport=8080 listenaddress=0.0.0.0 connectport=8080 connectaddress=$WSL_IP
netsh advfirewall firewall add rule name="Voxtral STT" dir=in action=allow protocol=tcp localport=8080

# Port 8001: GPU diarization + embedding service
Write-Host "Setting up port forwarding: Windows:8001 -> WSL2($WSL_IP):8001"
netsh interface portproxy add v4tov4 listenport=8001 listenaddress=0.0.0.0 connectport=8001 connectaddress=$WSL_IP
netsh advfirewall firewall add rule name="GPU Diarization" dir=in action=allow protocol=tcp localport=8001

# Verify
Write-Host "`nPort proxy rules:"
netsh interface portproxy show all

Write-Host "`nDone! LAN machines can access:"
Write-Host "  Voxtral:      http://<YOUR_WINDOWS_IP>:8080"
Write-Host "  Diarization:  http://<YOUR_WINDOWS_IP>:8001"
