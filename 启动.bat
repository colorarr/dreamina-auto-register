@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul 2>nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

cd /d "%~dp0" || (
    echo [ERROR] Failed to enter project root.
    pause
    exit /b 1
)

title Dreamina Auto Register

set "ROOT=%CD%"
set "BACKEND_DIR=%ROOT%\backend"
set "FRONTEND_DIR=%ROOT%\frontend"
REM jimeng_service removed, using jimeng-free-api-all separately
set "LOG_DIR=%BACKEND_DIR%\logs\startup"
set "CHECK_ONLY=0"

if /i "%~1"=="--check" set "CHECK_ONLY=1"

echo.
echo ========================================
echo   Dreamina Auto Register - v2.2.0
echo ========================================
echo.
echo [INFO] Project root: %ROOT%
if "%CHECK_ONLY%"=="1" echo [INFO] Check mode enabled. Services will not be started.
echo.

if not exist "%BACKEND_DIR%\data" mkdir "%BACKEND_DIR%\data" >nul 2>nul
if not exist "%BACKEND_DIR%\data\screenshots" mkdir "%BACKEND_DIR%\data\screenshots" >nul 2>nul
if not exist "%BACKEND_DIR%\data\browser_states" mkdir "%BACKEND_DIR%\data\browser_states" >nul 2>nul
if not exist "%BACKEND_DIR%\logs" mkdir "%BACKEND_DIR%\logs" >nul 2>nul
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%" >nul 2>nul

echo [CLEAN] Stopping old services...
call :kill_port 8005 Backend
call :kill_port 5175 Frontend
REM JimengAPI is now started separately
ping 127.0.0.1 -n 2 >nul 2>&1
echo [CLEAN] Done.
echo.

echo [CHECK] Verifying runtime commands...
call :detect_python || goto :fail
call :detect_node || goto :fail

echo [CHECK] Python launcher: %PYTHON_CMD%
call %PYTHON_CMD% --version || goto :fail
echo [CHECK] Node executable: node
node --version || goto :fail
echo [CHECK] NPM executable: %NPM_CMD%
call "%NPM_CMD%" --version || goto :fail
echo.

if not exist "%BACKEND_DIR%\.env" (
    echo [CONFIG] Creating default config...
    copy "%BACKEND_DIR%\.env.example" "%BACKEND_DIR%\.env" >nul
    if errorlevel 1 (
        echo [ERROR] Failed to create config file.
        goto :fail
    )
    echo       Config created. You can adjust settings in the web dashboard.
)


echo [1/4] Preparing Python environment...
if not exist "%BACKEND_DIR%\.venv\Scripts\python.exe" (
    echo       Creating virtual environment...
    call %PYTHON_CMD% -m venv "%BACKEND_DIR%\.venv" || goto :fail
)

set "VENV_PYTHON=%BACKEND_DIR%\.venv\Scripts\python.exe"
set "PATCHRIGHT_EXE=%BACKEND_DIR%\.venv\Scripts\patchright.exe"

if not exist "%VENV_PYTHON%" (
    echo [ERROR] Virtual environment python.exe not found.
    goto :fail
)

REM Use marker file to skip repeated pip install
set "PIP_MARKER=%BACKEND_DIR%\.venv\.deps-installed"
set "NEED_PIP=0"
if not exist "%PIP_MARKER%" set "NEED_PIP=1"
if "%NEED_PIP%"=="0" (
    for %%A in ("%BACKEND_DIR%\requirements.txt") do set "REQ_DATE=%%~tA"
    for %%A in ("%PIP_MARKER%") do set "MARKER_DATE=%%~tA"
    if "!REQ_DATE!" neq "!MARKER_DATE!" set "NEED_PIP=1"
)
if "%NEED_PIP%"=="1" (
    echo       Installing Python dependencies...
    "%VENV_PYTHON%" -m pip install --disable-pip-version-check -q -r "%BACKEND_DIR%\requirements.txt" -i https://pypi.tuna.tsinghua.edu.cn/simple || goto :fail
    copy /y "%BACKEND_DIR%\requirements.txt" "%PIP_MARKER%" >nul 2>nul
) else (
    echo       Python dependencies ........ cached
)

if not exist "%PATCHRIGHT_EXE%" (
    echo [ERROR] patchright.exe not found after dependency installation.
    goto :fail
)

if not exist "%BACKEND_DIR%\.venv\.patchright-ready" (
    echo       Installing Patchright browser...
    call "%PATCHRIGHT_EXE%" install chromium || goto :fail
    > "%BACKEND_DIR%\.venv\.patchright-ready" echo ready
)

echo       Python environment ........ OK
echo.

echo [2/3] Checking external Jimeng API...
echo       [INFO] Start jimeng-free-api-all separately before using
echo       [INFO] Set JIMENG_API_URL in backend\.env if needed
echo.

echo [3/3] Preparing Frontend...
if exist "%FRONTEND_DIR%\node_modules\.package-lock.json" (
    echo       Frontend .................. cached
) else (
    pushd "%FRONTEND_DIR%" || goto :fail
    call "%NPM_CMD%" install --no-audit --no-fund --loglevel error || (
        popd
        goto :fail
    )
    popd
    echo       Frontend .................. OK
)
echo.

if "%CHECK_ONLY%"=="1" (
    echo [CHECK] Validation completed. No services were started.
    echo.
    echo Press any key to exit.
    pause >nul
    exit /b 0
)

set "BACKEND_LOG=%LOG_DIR%\backend.log"
set "FRONTEND_LOG=%LOG_DIR%\frontend.log"

type nul > "%BACKEND_LOG%"
type nul > "%FRONTEND_LOG%"

set "RUNNER_SUFFIX=%RANDOM%%RANDOM%%RANDOM%"
set "BACKEND_RUNNER=%TEMP%\dreamina_start_backend_%RUNNER_SUFFIX%.bat"
set "FRONTEND_RUNNER=%TEMP%\dreamina_start_frontend_%RUNNER_SUFFIX%.bat"

echo [INFO] Starting services in parallel...

REM JimengAPI started separately

(
    echo @echo off
    echo chcp 65001 ^>nul 2^>nul
    echo set "PYTHONUTF8=1"
    echo set "PYTHONIOENCODING=utf-8"
    echo cd /d "%BACKEND_DIR%"
    echo "%VENV_PYTHON%" -m uvicorn app.main:app --host 0.0.0.0 --port 8005 --loop asyncio ^>^> "%BACKEND_LOG%" 2^>^&1
) > "%BACKEND_RUNNER%"


(
    echo @echo off
    echo chcp 65001 ^>nul 2^>nul
    echo set "PYTHONUTF8=1"
    echo set "PYTHONIOENCODING=utf-8"
    echo cd /d "%FRONTEND_DIR%"
    echo call "%NPM_CMD%" run dev ^>^> "%FRONTEND_LOG%" 2^>^&1
) > "%FRONTEND_RUNNER%"


REM === Parallel start: launch Backend + Frontend (background) ===
start "" /b cmd /c ""%BACKEND_RUNNER%""
start "" /b cmd /c ""%FRONTEND_RUNNER%""

echo       All services launched, waiting for ports...

REM === Fast parallel port wait using PowerShell TCP check ===
REM JimengAPI port check skipped
call :fast_wait 8005 90 Backend || goto :startup_fail
call :fast_wait 5175 90 Frontend || goto :startup_fail

echo.
echo ========================================
echo   All services started successfully.
echo.
echo   Dashboard:  http://localhost:5175
echo   Backend:    http://localhost:8005
echo   API Docs:   http://localhost:8005/docs
echo   Jimeng API: (Start jimeng-free-api-all separately)
echo.
echo   Logs:
echo     %BACKEND_LOG%
echo     %FRONTEND_LOG%
echo ========================================
echo.

echo   Checking service availability...
echo.
REM Wait for backend API ready (max 30s)
set "API_READY=0"
for /L %%i in (1,1,30) do (
    if "!API_READY!"=="0" (
        curl -s -o nul -w "" http://localhost:8005/api/health >nul 2>nul && set "API_READY=1"
        if "!API_READY!"=="0" ping 127.0.0.1 -n 2 >nul 2>&1
    )
)
if "!API_READY!"=="0" (
        echo   [WARN] Backend API not ready after 30s
)
REM Wait for frontend HTTP ready (max 10s)
set "HTTP_READY=0"
for /L %%i in (1,1,10) do (
    if "!HTTP_READY!"=="0" (
        curl -s -o nul -w "" http://localhost:5175 >nul 2>nul && set "HTTP_READY=1"
        if "!HTTP_READY!"=="0" ping 127.0.0.1 -n 2 >nul 2>&1
    )
)
start "" http://localhost:5175

echo.
echo Press any key to stop all services and exit.
pause >nul
goto :cleanup

:startup_fail
echo.
echo [ERROR] One or more services failed to start.
echo [ERROR] Check the log files below:
echo         %JIMENG_LOG%
echo         %BACKEND_LOG%
echo         %FRONTEND_LOG%
echo.
pause
goto :cleanup

:cleanup
echo.
echo [STOP] Stopping services...
call :kill_port 8005 Backend
call :kill_port 5175 Frontend
REM JimengAPI cleanup skipped
del "%BACKEND_RUNNER%" >nul 2>nul
del "%BACKEND_RUNNER%.vbs" >nul 2>nul
del "%FRONTEND_RUNNER%.vbs" >nul 2>nul
del "%FRONTEND_RUNNER%" >nul 2>nul
echo [STOP] Done.
echo.
echo Press any key to exit.
pause >nul
exit /b 0

:fail
echo.
echo [ERROR] start.bat failed.
echo Press any key to exit.
pause >nul
exit /b 1

:detect_python
where python >nul 2>nul
if not errorlevel 1 (
    set "PYTHON_CMD=python"
    exit /b 0
)

where py >nul 2>nul
if not errorlevel 1 (
    set "PYTHON_CMD=py -3"
    exit /b 0
)

REM Check default install location
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
    set "PYTHON_CMD=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    exit /b 0
)

echo [INFO] Python not found. Downloading Python 3.12.1...
echo        URL: https://www.python.org/ftp/python/3.12.1/python-3.12.1-amd64.exe
powershell -NoProfile -Command "Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.12.1/python-3.12.1-amd64.exe' -OutFile 'python_installer.exe'"
if not exist "python_installer.exe" (
    echo [ERROR] Download failed.
    exit /b 1
)
echo [INFO] Installing Python 3.12.1 silently...
python_installer.exe /quiet InstallAllUsers=0 PrependPath=1 Include_test=0 Include_pip=1
if exist python_installer.exe del python_installer.exe
set "PYTHON_CMD=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not exist "!PYTHON_CMD!" (
    echo [ERROR] Auto-install failed. Please install Python 3.12+ manually.
    exit /b 1
)
echo [OK] Python 3.12 installed successfully.
exit /b 0

:detect_node
where node >nul 2>nul
if errorlevel 1 goto :install_node

set "NPM_CMD="
for /f "delims=" %%p in ('where npm.cmd 2^>nul') do (
    if not defined NPM_CMD set "NPM_CMD=%%p"
)
if not defined NPM_CMD goto :install_node
exit /b 0

:install_node
echo [INFO] Node.js not found. Downloading Node.js 20.11.1 LTS...
echo        URL: https://nodejs.org/dist/v20.11.1/node-v20.11.1-x64.msi
powershell -NoProfile -Command "Invoke-WebRequest -Uri 'https://nodejs.org/dist/v20.11.1/node-v20.11.1-x64.msi' -OutFile 'node_installer.msi'"
if not exist "node_installer.msi" (
    echo [ERROR] Download failed.
    exit /b 1
)
echo [INFO] Installing Node.js 20.11.1 silently...
msiexec /i node_installer.msi /quiet /norestart
if exist node_installer.msi del node_installer.msi
REM Refresh PATH
set "PATH=%PATH%;%ProgramFiles%\nodejs"
where node >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Auto-install failed. Please install Node.js 20+ manually.
    exit /b 1
)
set "NPM_CMD="
for /f "delims=" %%p in ('where npm.cmd 2^>nul') do (
    if not defined NPM_CMD set "NPM_CMD=%%p"
)
echo [OK] Node.js 20 installed successfully.
exit /b 0

:kill_port
set "TARGET_PORT=%~1"
set "TARGET_NAME=%~2"
set "TARGET_FOUND=0"
for /f "skip=4 tokens=1,2,3,4,5" %%a in ('netstat -ano -p tcp 2^>nul') do (
    set "LOCAL_ADDR=%%b"
    set "PORT_MATCH=0"
    echo(!LOCAL_ADDR!| findstr /R /C:":!TARGET_PORT!$" >nul 2>nul && set "PORT_MATCH=1"
    if "!PORT_MATCH!"=="1" (
        set "TARGET_FOUND=1"
        echo       Stopping !TARGET_NAME! PID %%e on port !TARGET_PORT!
        taskkill /PID %%e /F >nul 2>nul
    )
)
if "!TARGET_FOUND!"=="0" echo       No running !TARGET_NAME! found on port !TARGET_PORT!
exit /b 0

REM === Fast port check using PowerShell TCP connect ===
:fast_wait
set "FW_PORT=%~1"
set "FW_TIMEOUT=%~2"
set "FW_NAME=%~3"
set "FW_COUNT=0"

:fw_loop
set /a FW_COUNT+=1
if !FW_COUNT! gtr !FW_TIMEOUT! goto :fw_timeout

powershell -NoProfile -Command "try{$c=New-Object System.Net.Sockets.TcpClient;$c.Connect('127.0.0.1',%FW_PORT%);$c.Close();exit 0}catch{exit 1}" >nul 2>nul
if not errorlevel 1 goto :fw_found

ping 127.0.0.1 -n 2 >nul 2>&1
goto :fw_loop

:fw_found
echo       !FW_NAME! listening on port !FW_PORT!  [!FW_COUNT!s]
exit /b 0

:fw_timeout
echo [ERROR] !FW_NAME! did not open port !FW_PORT! within !FW_TIMEOUT!s
exit /b 1