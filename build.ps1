# COM-IP Bridge - PowerShell Build & Package Script
# Usage: .\build.ps1 [-SkipInstaller] [-Configuration Release]

param(
    [switch]$SkipInstaller,
    [string]$Configuration = "Release",
    [string]$Runtime = "win-x64"
)

$ErrorActionPreference = "Stop"

Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  COM-IP Bridge - Build & Package Script" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

$PublishDir = "publish"
$InstallerDir = "installer"
$Project = "src\ComIpBridge.csproj"

# Step 1: Clean
Write-Host "[1/4] Cleaning previous build..." -ForegroundColor Yellow
if (Test-Path $PublishDir) { Remove-Item $PublishDir -Recurse -Force }
if (Test-Path "$InstallerDir\Output") { Remove-Item "$InstallerDir\Output" -Recurse -Force }
Write-Host "Done." -ForegroundColor Green

# Step 2: Restore
Write-Host "[2/4] Restoring NuGet packages..." -ForegroundColor Yellow
dotnet restore $Project
if ($LASTEXITCODE -ne 0) { throw "dotnet restore failed" }
Write-Host "Done." -ForegroundColor Green

# Step 3: Publish
Write-Host "[3/4] Publishing self-contained application ($Runtime)..." -ForegroundColor Yellow
dotnet publish $Project `
    -c $Configuration `
    -r $Runtime `
    --self-contained true `
    -p:PublishSingleFile=true `
    -p:IncludeNativeLibrariesForSelfExtract=true `
    -o $PublishDir
if ($LASTEXITCODE -ne 0) { throw "dotnet publish failed" }
Write-Host "Done." -ForegroundColor Green

# Step 4: Create Installer
if (-not $SkipInstaller) {
    Write-Host "[4/4] Creating installer..." -ForegroundColor Yellow

    $iscc = $null
    if (Get-Command "iscc" -ErrorAction SilentlyContinue) {
        $iscc = "iscc"
    } elseif (Test-Path "C:\Program Files (x86)\Inno Setup 6\ISCC.exe") {
        $iscc = "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
    } elseif (Test-Path "C:\Program Files\Inno Setup 6\ISCC.exe") {
        $iscc = "C:\Program Files\Inno Setup 6\ISCC.exe"
    }

    if ($iscc) {
        & $iscc "$InstallerDir\setup.iss"
        if ($LASTEXITCODE -ne 0) { throw "Installer creation failed" }
        Write-Host "Done." -ForegroundColor Green
    } else {
        Write-Host "WARNING: Inno Setup not found. Skipping installer." -ForegroundColor DarkYellow
        Write-Host "Download from: https://jrsoftware.org/isdl.php" -ForegroundColor DarkYellow
    }
} else {
    Write-Host "[4/4] Skipping installer (--SkipInstaller)" -ForegroundColor DarkYellow
}

# Summary
Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  Build complete!" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Portable:  $PublishDir\ComIpBridge.exe" -ForegroundColor White

$installerExe = Get-ChildItem "$InstallerDir\Output\*.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
if ($installerExe) {
    Write-Host "  Installer: $($installerExe.FullName)" -ForegroundColor White
}
Write-Host ""
