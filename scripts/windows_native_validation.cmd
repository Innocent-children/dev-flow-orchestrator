@echo off
setlocal DisableDelayedExpansion

py -3 -c "import sys;sys.exit(0 if (3, 9) <= sys.version_info[:2] < (3, 15) else 1)" >nul 2>nul
if not errorlevel 1 goto run_py

for %%V in (3.14 3.13 3.12 3.11 3.10 3.9) do (
  py -%%V -c "import sys;sys.exit(0 if sys.version_info[:2] == tuple(map(int, '%%V'.split('.'))) else 1)" >nul 2>nul
  if not errorlevel 1 (
    set "DEV_FLOW_PY_VERSION=-%%V"
    goto run_py_version
  )
)

python -c "import sys;sys.exit(0 if (3, 9) <= sys.version_info[:2] < (3, 15) else 1)" >nul 2>nul
if not errorlevel 1 goto run_python

>&2 echo dev-flow-orchestrator: Python 3.9-3.14 was not found via py -3 or python.
exit /b 9009

:run_py
py -3 "%~dp0windows_native_validation.py" %*
exit /b %errorlevel%

:run_py_version
py %DEV_FLOW_PY_VERSION% "%~dp0windows_native_validation.py" %*
exit /b %errorlevel%

:run_python
python "%~dp0windows_native_validation.py" %*
exit /b %errorlevel%
