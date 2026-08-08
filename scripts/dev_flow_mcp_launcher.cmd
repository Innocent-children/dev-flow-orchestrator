@echo off
rem dev-flow-orchestrator managed MCP launcher
"__DEV_FLOW_RUNTIME_PYTHON__" -I -m dev_flow_orchestrator.mcp %*
exit /b %ERRORLEVEL%
