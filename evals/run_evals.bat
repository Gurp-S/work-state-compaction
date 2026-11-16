@echo off
setlocal
chcp 65001 >nul 2>&1
title WSC / CSM one-click evaluation launcher

REM ============================================================
REM  WSC / CSM one-click evaluation launcher
REM  Double-click to run. Edit config.json first (API key etc.).
REM  All paths are resolved relative to this .bat file location.
REM ============================================================

set "HERE=%~dp0"
cd /d "%HERE%"

REM ---- Locate python ----
set "PY_EXE="
if exist "%HERE%config.json" (
  for /f "usebackq tokens=*" %%v in (`powershell -NoProfile -Command "try{(Get-Content -Raw '%HERE%config.json' | ConvertFrom-Json).python.venv_python}catch{''}"`) do set "PY_EXE=%%v"
)
if not defined PY_EXE set "PY_EXE=python"
echo Using python: %PY_EXE%

REM ---- Clean injected PYTHONPATH (WorkBuddy shim breaks child processes) ----
set "PYTHONPATH="
set "PYTHONIOENCODING=utf-8"

echo.
echo ============================================================
echo   WSC / CSM one-click evaluation
echo   root: %HERE%
echo ============================================================
echo   [1] Run ALL suites (locomo + bench22 + pair)
echo   [2] LoCoMo-Plus only
echo   [3] Companion memory Bench 2.2 only
echo   [4] WSC vs DSH native compaction only
echo   [5] DEMO - print per-question format from existing results (no API)
echo   [0] Exit
echo ============================================================
set /p "CHOICE=Select [0-5]: "

if "%CHOICE%"=="1" goto RUN_ALL
if "%CHOICE%"=="2" goto RUN_LOCOMO
if "%CHOICE%"=="3" goto RUN_BENCH22
if "%CHOICE%"=="4" goto RUN_PAIR
if "%CHOICE%"=="5" goto RUN_DEMO
if "%CHOICE%"=="0" goto END
echo Invalid selection.
goto END

:RUN_ALL
echo.
echo >>> Running ALL evaluation suites...
"%PY_EXE%" "%HERE%eval_driver.py"
goto DONE

:RUN_LOCOMO
echo.
echo >>> Running LoCoMo-Plus...
"%PY_EXE%" "%HERE%eval_driver.py" --only locomo
goto DONE

:RUN_BENCH22
echo.
echo >>> Running companion Bench 2.2...
"%PY_EXE%" "%HERE%eval_driver.py" --only bench22
goto DONE

:RUN_PAIR
echo.
echo >>> Running WSC vs DSH native compaction...
"%PY_EXE%" "%HERE%eval_driver.py" --only pair
goto DONE

:RUN_DEMO
echo.
echo >>> DEMO mode (no API calls)...
"%PY_EXE%" "%HERE%eval_driver.py" --demo
goto DONE

:DONE
echo.
echo ============================================================
echo   Finished. Per-question results and scores are printed above.
echo   Machine-readable summary: %HERE%run_results\summary.json
echo ============================================================

:END
echo.
pause
endlocal
