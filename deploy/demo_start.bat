@echo off
rem Defence demo: send ONE test "clean" command (pump 1 minute). Then press RESET on the ESP32.
rem hilla-vps is a short name defined in %USERPROFILE%\.ssh\config (Host / HostName / User / IdentityFile).
ssh hilla-vps "sudo -u hilla /home/hilla/venv/bin/python /home/hilla/app/deploy/demo_clean.py"
pause
