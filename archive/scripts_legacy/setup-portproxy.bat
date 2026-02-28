@echo off
echo Setting up port forwarding for Voxtral STT Server...
echo.

REM Add port forward: Windows host 8080 -> WSL2 172.17.157.143:8080
netsh interface portproxy add v4tov4 listenport=8080 listenaddress=0.0.0.0 connectport=8080 connectaddress=172.17.157.143
if %errorlevel% equ 0 (
    echo [OK] Port proxy rule added successfully
) else (
    echo [FAIL] Failed to add port proxy rule
)

echo.

REM Open Windows firewall for port 8080
netsh advfirewall firewall add rule name="Voxtral STT" dir=in action=allow protocol=tcp localport=8080
if %errorlevel% equ 0 (
    echo [OK] Firewall rule added successfully
) else (
    echo [FAIL] Failed to add firewall rule
)

echo.
echo Verifying port proxy:
netsh interface portproxy show all

echo.
echo Done! LAN machines can now reach Voxtral at http://<YOUR_WINDOWS_IP>:8080
pause
