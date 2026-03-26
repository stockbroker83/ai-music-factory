@echo off
chcp 65001 >nul 2>&1
cd /d "C:\Users\csu\projects\ai-music-factory"
set PYTHONIOENCODING=utf-8

:: ffmpeg PATH 추가
set PATH=%LOCALAPPDATA%\Microsoft\WinGet\Links;%PATH%

echo.
echo   ========================================
echo     AI Music Factory Dashboard
echo   ========================================
echo.

:: Python 확인
python --version >nul 2>&1
if errorlevel 1 (
    echo   [오류] Python이 설치되어 있지 않습니다.
    pause
    exit /b 1
)

:: .env 확인
if not exist ".env" (
    echo   [경고] .env 파일이 없습니다. .env.example을 복사합니다...
    copy .env.example .env >nul
    echo   .env 파일을 열어서 API 키를 입력해주세요!
    notepad .env
    pause
    exit /b 1
)

:: 의존성 자동 설치 (flask 없으면)
python -c "import flask" >nul 2>&1
if errorlevel 1 (
    echo   패키지 설치 중...
    pip install -r requirements.txt
    echo.
)

echo   서버 시작 중... http://localhost:5000
echo   (종료하려면 이 창을 닫으세요)
echo.
python app.py
pause
