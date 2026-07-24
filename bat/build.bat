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
set "BASE_FLAGS=/std:c11 /D_CRT_SECURE_NO_WARNINGS /Zi /Od /W4 /nologo"
set "DISABLED_WARNINGS=/wd4005 /wd4047 /wd4057 /wd4100 /wd4267 /wd4244 /wd4459"
set "COMMON_FLAGS=%LOG_FLAGS% %BASE_FLAGS% %DISABLED_WARNINGS%"
echo [INFO] Compiling %PROGRAM%.exe

cl %COMMON_FLAGS% /Zc:preprocessor %PROGRAM%.c /link /SUBSYSTEM:CONSOLE /OUT:%PROGRAM%.exe kernel32.lib user32.lib dbghelp.lib > build.log 2>&1
set "BUILD_STATUS=%errorlevel%"

powershell -NoProfile -Command "$c=0; Get-Content build.log | ForEach-Object { $line = $_ -replace '^[A-Za-z]:\\.*\\source\\', ''; if($line -notmatch '^[a-zA-Z0-9_]*\.c$' -and $line -notmatch '^Generating Code...$' -and $line -notmatch '^Compiling...$'){ if($line -match 'error' -or $line -match 'fatal error'){ $c++; Write-Host $line -ForegroundColor Red } else { Write-Host $line }; if($c -ge 13){ Write-Host '>>> ABORTING: TOO MANY ERRORS. <<<' -ForegroundColor Red; break } } }"

if exist build.log del build.log

if %BUILD_STATUS% equ 0 (
    echo    [SUCCESS] Build finished completely.
    "%PROGRAM%.exe" "%ROOT_PROG%" %*
) else (
    echo    [ERROR] Compilation failed.
    exit /b %BUILD_STATUS%
)