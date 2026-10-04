@echo off
rem cxauto 图形界面启动器：双击运行
chcp 65001 >nul
set PYTHONUTF8=1
cd /d %~dp0
python gui.py
if errorlevel 1 pause
