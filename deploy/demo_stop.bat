@echo off
rem End the defence demo now (the AI command is served again).
rem hilla-vps is a short name defined in %USERPROFILE%\.ssh\config (Host / HostName / User / IdentityFile).
ssh hilla-vps "sudo -u hilla /home/hilla/venv/bin/python /home/hilla/app/deploy/demo_clean.py --stop"
pause
