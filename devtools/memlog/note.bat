@echo off
rem Usage: note.bat test A started   (adds a NOTE line to today's events log)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0memlog.ps1" -Note "%*"
