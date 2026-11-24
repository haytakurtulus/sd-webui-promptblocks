@echo off
rem Double-click to start the PromptBlocks memory / activity logger. Close this window to stop it.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0memlog.ps1"
pause
