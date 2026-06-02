@echo off
cd /d "%~dp0"
echo.
echo ================================================
echo   Quick Reply - Copy message then press Enter
echo ================================================
echo.
echo 1. In WeChat, select the message text and Ctrl+C
echo 2. Come back here and press Enter
echo.
pause
py wechat_bot.py --clip
pause
