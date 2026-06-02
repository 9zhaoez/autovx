@echo off
cd /d "%~dp0"
echo.
echo ================================================
echo   autovx AI
echo ================================================
echo.
py wechat_bot.py 2>&1
echo.
echo.
echo Program stopped.
pause
