@echo off
rem Start QuickTrim so phones on the same Wi-Fi can use it.
cd /d "%~dp0"
python -m streamlit run app.py --server.address 0.0.0.0
pause
