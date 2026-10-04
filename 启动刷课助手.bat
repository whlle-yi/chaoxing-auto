@echo off
rem cxauto 图形界面启动器：双击运行（无控制台黑窗口，进度全在界面里）
cd /d %~dp0
start "" pythonw gui.py
