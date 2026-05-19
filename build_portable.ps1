$ErrorActionPreference = "Stop"

$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$DistDir = Join-Path $ProjectDir "dist\FarmBot"

Set-Location $ProjectDir

python -m pip install -r requirements.txt

python -m PyInstaller `
    --noconfirm `
    --onedir `
    --windowed `
    --name FarmBot `
    main_farm_loop.py

if (Test-Path (Join-Path $ProjectDir "templates")) {
    Copy-Item `
        -Path (Join-Path $ProjectDir "templates") `
        -Destination $DistDir `
        -Recurse `
        -Force
}

if (Test-Path (Join-Path $ProjectDir "farm_config.json")) {
    Copy-Item `
        -Path (Join-Path $ProjectDir "farm_config.json") `
        -Destination $DistDir `
        -Force
}

if (Test-Path (Join-Path $ProjectDir "adb")) {
    Copy-Item `
        -Path (Join-Path $ProjectDir "adb") `
        -Destination $DistDir `
        -Recurse `
        -Force
}

Write-Host "Portable build ready: $DistDir"
Write-Host "Put adb.exe, AdbWinApi.dll, and AdbWinUsbApi.dll in $DistDir\adb if they are not there yet."
