@echo off
rem End the defence demo now (the AI command is served again).
ssh -i "%USERPROFILE%\.ssh\hilla_vps" root@64.226.106.240 "sudo -u hilla /home/hilla/venv/bin/python /home/hilla/app/deploy/demo_clean.py --stop"
pause
