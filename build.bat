@echo off
setlocal
echo ============================================
echo   COM-IP Bridge - Build ^& Package Script
echo ============================================
echo.

:: Configuration
set PUBLISH_DIR=publish
set INSTALLER_DIR=installer
set PROJECT=src\ComIpBridge.csproj

:: Step 1: Clean
echo [1/4] Cleaning previous build...
if exist "%PUBLISH_DIR%" rd /s /q "%PUBLISH_DIR%"
if exist "%INSTALLER_DIR%\Output" rd /s /q "%INSTALLER_DIR%\Output"
echo Done.
echo.

:: Step 2: Restore
echo [2/4] Restoring NuGet packages...
dotnet restore %PROJECT%
if errorlevel 1 (
    echo ERROR: dotnet restore failed!
    goto :error
)
echo Done.
echo.

:: Step 3: Publish (self-contained single file)
echo [3/4] Publishing self-contained application...
dotnet publish %PROJECT% -c Release -r win-x64 --self-contained true -p:PublishSingleFile=true -p:IncludeNativeLibrariesForSelfExtract=true -o "%PUBLISH_DIR%"
if errorlevel 1 (
    echo ERROR: dotnet publish failed!
    goto :error
)
echo Done.
echo.

:: Step 4: Create Installer (if Inno Setup is installed)
echo [4/4] Creating installer...
where iscc >nul 2>nul
if errorlevel 1 (
    :: Try common install paths
    if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" (
        "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" "%INSTALLER_DIR%\setup.iss"
    ) else if exist "C:\Program Files\Inno Setup 6\ISCC.exe" (
        "C:\Program Files\Inno Setup 6\ISCC.exe" "%INSTALLER_DIR%\setup.iss"
    ) else (
        echo WARNING: Inno Setup not found. Skipping installer creation.
        echo Download from: https://jrsoftware.org/isdl.php
        echo.
        echo Build output is in: %PUBLISH_DIR%\
        echo You can run ComIpBridge.exe directly from there.
        goto :done
    )
) else (
    iscc "%INSTALLER_DIR%\setup.iss"
)

if errorlevel 1 (
    echo ERROR: Installer creation failed!
    goto :error
)
echo Done.
echo.

:done
echo ============================================
echo   Build complete!
echo ============================================
echo.
echo   Portable:  %PUBLISH_DIR%\ComIpBridge.exe
if exist "%INSTALLER_DIR%\Output\*.exe" (
    echo   Installer: %INSTALLER_DIR%\Output\ComIpBridge_Setup_v1.0.0.exe
)
echo.
goto :eof

:error
echo.
echo Build failed with errors.
exit /b 1
