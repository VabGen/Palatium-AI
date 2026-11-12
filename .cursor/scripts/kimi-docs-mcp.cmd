@echo off
setlocal EnableExtensions

rem Cursor MCP spawn often has no Node on PATH (nvm4w / nvm-windows).
rem Prepend known locations, then run the official filesystem MCP on .cursor/references.

if exist "C:\nvm4w\nodejs\npx.cmd" set "PATH=C:\nvm4w\nodejs;%PATH%"
if exist "%ProgramFiles%\nodejs\npx.cmd" set "PATH=%ProgramFiles%\nodejs;%PATH%"
if exist "%LOCALAPPDATA%\Programs\node\npx.cmd" set "PATH=%LOCALAPPDATA%\Programs\node;%PATH%"

where npx.cmd >nul 2>&1
if errorlevel 1 (
  echo kimi-docs: npx not found. Install Node or add it to PATH for the Cursor process. 1>&2
  exit /b 1
)

set "REF_DIR=%~dp0..\references"
for %%I in ("%REF_DIR%") do set "REF_DIR=%%~fI"

npx.cmd -y @modelcontextprotocol/server-filesystem "%REF_DIR%"
exit /b %ERRORLEVEL%
