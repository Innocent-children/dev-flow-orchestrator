@echo off
setlocal DisableDelayedExpansion

if "%~1"=="" (
  >&2 echo dev-flow-orchestrator: a Python handler path is required.
  exit /b 64
)

set "DEV_FLOW_HANDLER=%~1"
shift
if not exist "%DEV_FLOW_HANDLER%" (
  >&2 echo dev-flow-orchestrator: Python handler does not exist: %DEV_FLOW_HANDLER%
  exit /b 66
)

if defined DEV_FLOW_PYTHON (
  if exist "%DEV_FLOW_PYTHON%" (
    "%DEV_FLOW_PYTHON%" -c "import struct,sys;sys.exit(0 if (3,9) <= sys.version_info[:2] < (3,15) and struct.calcsize('P') == 8 else 1)" >nul 2>nul
    if not errorlevel 1 (
      "%DEV_FLOW_PYTHON%" -X utf8 -I -S %*
      exit /b
    )
  )
)

where py.exe >nul 2>nul
if not errorlevel 1 (
  py.exe -3 -c "import struct,sys;sys.exit(0 if (3,9) <= sys.version_info[:2] < (3,15) and struct.calcsize('P') == 8 else 1)" >nul 2>nul
  if not errorlevel 1 (
    py.exe -3 -X utf8 -I -S %*
    exit /b
  )
)

for %%P in (python.exe python3.exe) do (
  where %%P >nul 2>nul
  if not errorlevel 1 (
    %%P -c "import struct,sys;sys.exit(0 if (3,9) <= sys.version_info[:2] < (3,15) and struct.calcsize('P') == 8 else 1)" >nul 2>nul
    if not errorlevel 1 (
      %%P -X utf8 -I -S %*
      exit /b
    )
  )
)

>&2 echo dev-flow-orchestrator: supported 64-bit Python 3.9-3.14 was not found; set DEV_FLOW_PYTHON to a verified interpreter.
exit /b 127
