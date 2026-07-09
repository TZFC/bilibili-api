@echo off
chcp 65001 > nul
echo ==================================================
echo       Bilibili 直播弹幕监听器启动工具
echo ==================================================
set /p ROOM_ID="请输入直播间 Room ID [默认: 23596840]: "
if "%ROOM_ID%"=="" set ROOM_ID=23596840

echo.
echo 正在启动监听直播间: %ROOM_ID% ...
.venv314\Scripts\python.exe scripts\livechat_listener.py --room_id=%ROOM_ID%
pause
