@echo off

:: BatchGotAdmin
:-------------------------------------
rem  --> Check for permissions
>nul 2>&1 "%SYSTEMROOT%\system32\cacls.exe" "%SYSTEMROOT%\system32\config\system"

rem --> If error flag set, we do not have admin.
if '%errorlevel%' neq '0' (
    echo Requesting administrative privileges...
    goto UACPrompt
) else ( goto gotAdmin )

:UACPrompt
    echo Set UAC = CreateObject^("Shell.Application"^) > "%temp%\getadmin.vbs"
    set params = %*:"=""
    echo UAC.ShellExecute "cmd.exe", "/c %~s0 %params%", "", "runas", 1 >> "%temp%\getadmin.vbs"

    "%temp%\getadmin.vbs"
    del "%temp%\getadmin.vbs"
    exit /B

:gotAdmin
    pushd "%CD%"
    cd /D "%~dp0"
:--------------------------------------

set message="Cursor pack succesfully deleted."
set exitCode=0

reg DELETE "HKCU\Control Panel\Cursors\Schemes" /v "Unobtrusive" /f

if '%errorlevel%' neq '0' (
    set exitCode=%errorlevel%
    goto messageBox
)

rmdir /Q /S %SYSTEMROOT%\Cursors\Unobtrusive

if '%errorlevel%' neq '0' (
    set exitCode=%errorlevel%
)

:messageBox
    echo x=msgbox(%message%, 0+64, "Cursor") > %tmp%\tmp.vbs
    wscript %tmp%\tmp.vbs
    del %tmp%\tmp.vbs

exit %exitCode%
