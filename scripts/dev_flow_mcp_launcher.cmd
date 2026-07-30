@echo off
setlocal DisableDelayedExpansion

call py -3 -c "import sys;sys.exit(0 if (3, 9) <= sys.version_info[:2] < (3, 15) else 1)" >nul 2>nul
if not errorlevel 1 goto run_py

for %%V in (3.14 3.13 3.12 3.11 3.10 3.9) do (
  call py -%%V -c "import sys;sys.exit(0 if sys.version_info[:2] == tuple(map(int, '%%V'.split('.'))) else 1)" >nul 2>nul
  if not errorlevel 1 (
    set "DEV_FLOW_PY_VERSION=-%%V"
    goto run_py_version
  )
)

call python -c "import sys;sys.exit(0 if (3, 9) <= sys.version_info[:2] < (3, 15) else 1)" >nul 2>nul
if not errorlevel 1 goto run_python

>&2 echo dev-flow-orchestrator: Python 3.9-3.14 was not found via py -3 or python.
exit /b 9009

:run_py
call py -3 "%~dp0dev_flow_mcp.py" %*
exit /b %errorlevel%

:run_py_version
call py %DEV_FLOW_PY_VERSION% "%~dp0dev_flow_mcp.py" %*
exit /b %errorlevel%

:run_python
call python "%~dp0dev_flow_mcp.py" %*
exit /b %errorlevel%
