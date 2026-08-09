@echo off
rem dev-flow-orchestrator managed MCP launcher
rem The verifier launches dev_flow_orchestrator.mcp only after receipt validation.
set "PYTHONDONTWRITEBYTECODE=1"
"__DEV_FLOW_RUNTIME_PYTHON__" -B -I "__DEV_FLOW_RUNTIME_VERIFIER__" launch-mcp --runtime-dir "__DEV_FLOW_RUNTIME_DIR__" --launcher "%~f0" --release-id "__DEV_FLOW_RELEASE_ID__" -- %*
exit /b %ERRORLEVEL%
