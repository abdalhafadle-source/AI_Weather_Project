@echo off
rem Defence demo: send ONE test "clean" command (pump 1 minute). Then press RESET on the ESP32.
ssh -i "%USERPROFILE%\.ssh\hilla_vps" root@64.226.106.240 "sudo -u hilla /home/hilla/venv/bin/python /home/hilla/app/deploy/demo_clean.py"
pause
