@echo off
echo ==================================================
echo       Bilibili Livechat Listener Launcher
echo ==================================================
set /p ROOM_ID="Please enter Bilibili Room ID [default: 23596840]: "
if "%ROOM_ID%"=="" set ROOM_ID=23596840

echo.
echo Starting listener for room: %ROOM_ID% ...
.venv313\Scripts\python.exe scripts\livechat_listener.py --room_id=%ROOM_ID%
echo.
echo Listener process exited with code %ERRORLEVEL%
pause
