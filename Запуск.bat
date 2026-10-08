@echo off
chcp 65001 >nul
title Sapphira
cd /d "%~dp0"
python -m bootstrap.main
if errorlevel 1 (
    echo.
    echo   Ошибка запуска. Проверь, что Python установлен.
    pause
)