@echo off
echo ================================================
echo  Van Sales V4 ERP - Clean Install
echo ================================================
echo.
echo [1/5] Checking Python...
python --version 2>nul || (echo ERROR: Python not found. Install from python.org && pause && exit)

echo [2/5] Removing old venv...
if exist venv rmdir /s /q venv

echo [3/5] Creating virtual environment...
python -m venv venv

echo [4/5] Installing packages (takes 1-2 mins)...
call venv\Scripts\activate.bat
pip install Flask Flask-SQLAlchemy Flask-Login Flask-WTF WTForms Werkzeug SQLAlchemy reportlab pandas openpyxl Pillow python-dotenv requests qrcode email-validator --quiet

echo [5/5] Starting Van Sales V4...
echo.
echo ================================================
echo  Open browser: http://127.0.0.1:5000
echo  Login: admin / admin123
echo  Press Ctrl+C to stop
echo ================================================
echo.
python run.py
pause
