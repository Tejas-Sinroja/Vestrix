@echo off
rem Double-click to start vestrix and open it in your browser.
rem Optional: drag a project folder onto this file to open that folder directly.
cd /d "%~dp0"
python -m vestrix ui %*
if errorlevel 1 pause
