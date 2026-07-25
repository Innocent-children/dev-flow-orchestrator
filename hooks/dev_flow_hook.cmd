@echo off
setlocal DisableDelayedExpansion

if not defined PLUGIN_ROOT goto missing_root

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

>&2 echo Dev Flow hook launcher could not find Python 3.9 through 3.14 via py -3 or python.
exit /b 1

:run_py
call py -3 "%PLUGIN_ROOT%\hooks\dev_flow_hook.py" %*
exit /b %errorlevel%

:run_py_version
call py %DEV_FLOW_PY_VERSION% "%PLUGIN_ROOT%\hooks\dev_flow_hook.py" %*
exit /b %errorlevel%

:run_python
call python "%PLUGIN_ROOT%\hooks\dev_flow_hook.py" %*
exit /b %errorlevel%

:missing_root
>&2 echo Dev Flow hook launcher requires a non-empty PLUGIN_ROOT.
exit /b 1
