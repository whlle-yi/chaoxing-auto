@echo off
rem cxauto 图形界面启动器：双击运行
cd /d %~dp0
python gui.py
if errorlevel 1 pause
