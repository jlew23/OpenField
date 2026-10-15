@echo off
echo === [OPENFIELD WINDOWS KILLSWITCH] ===

echo [-] Terminating any Windows processes on port 8770...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :8770') do (
    echo [-] Killing PID: %%a
    taskkill /F /PID %%a 2>nul
)

echo [-] Running WSL Killswitch...
wsl -e bash -c "cd /mnt/d/Users/Luda/Downloads/Genjustsu-Open-Source-Workflow-main/Genjustsu-Open-Source-Workflow-main && ./killswitch.sh"

echo.
echo [✓] Killswitch complete. You can now launch start.sh!
pause
