@echo off
setlocal enabledelayedexpansion

set PROGRAM=C:\Users\Public\Downloads\000github\ildz-compiler\source\ic
set ROOT_PROG=C:\Users\Public\Downloads\000github\ildz-compiler\source\ildz\ildzstd\test\test.ildz

set "VS_PATH="
for /f "usebackq tokens=*" %%i in (`"C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe" -latest -property installationPath`) do (
    set "VS_PATH=%%i"
)

if not defined VS_PATH (
    echo [ERROR] Visual Studio installation not found via vswhere.exe.
    echo Trying to run compiler directly assuming you are already in a Dev Prompt...
    goto compile
)

if exist "!VS_PATH!\VC\Auxiliary\Build\vcvarsall.bat" (
    call "!VS_PATH!\VC\Auxiliary\Build\vcvarsall.bat" x64 >nul
) else (
    echo [WARNING] Could not find vcvarsall.bat. Trying direct build...
)

:compile
set "BASE_FLAGS=/std:c11 /D_CRT_SECURE_NO_WARNINGS /Zi /Od /GS- /Gs999999 /MD /nologo"
set "DISABLED_WARNINGS=/wd4005 /wd4047 /wd4100 /wd4267 /wd4244"
set "COMMON_FLAGS=%LOG_FLAGS% %BASE_FLAGS% %DISABLED_WARNINGS%"
echo [INFO] Compiling %PROGRAM%.exe...
(
cl %COMMON_FLAGS% /Zc:preprocessor %PROGRAM%.c /link /NODEFAULTLIB /ENTRY:mainCRTStartup kernel32.lib user32.lib /SUBSYSTEM:CONSOLE /OUT:%PROGRAM%.exe 2>&1
) | powershell -Command "$c=0; $had_err=0; $input | %%{ if($_ -notmatch '^[a-zA-Z0-9_]*\.c$' -and $_ -notmatch '^Generating Code...$' -and $_ -notmatch '^Compiling...$'){ if($_ -match 'error' -or $_ -match 'fatal error'){ $c++; $had_err=1; Write-Host $_ -ForegroundColor Red } else { Write-Host $_ }; if($c -ge 13){ Write-Host '>>> ABORTING: TOO MANY ERRORS. <<<' -ForegroundColor Red; Stop-Process -Name cl -Force -ErrorAction SilentlyContinue; exit 1 } } }; if($had_err -eq 1){ exit 1 }"

if %errorlevel% equ 0 (
    echo   [SUCCESS] Build finished completely.
    %PROGRAM%.exe "%ROOT_PROG%" %*
) else (
    echo   [ERROR] Compilation failed. Check errors above.
)