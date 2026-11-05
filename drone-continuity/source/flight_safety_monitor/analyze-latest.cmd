@echo off
setlocal
set "PYTHON_EXE=C:\Users\Daddy Nate\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
"%PYTHON_EXE%" "%~dp0flight_guard.py" analyze --log "%~dp0..\outputs\dataflash-80.bin"
pause
