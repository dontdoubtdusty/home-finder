# Builds "Bebe's Home Search.exe" into the project folder (next to config.yaml).
#   powershell -ExecutionPolicy Bypass -File desktop\build.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

py -m pip install -q pyinstaller -r requirements.txt
py -m PyInstaller --noconfirm --clean --distpath "$root\build\dist" --workpath "$root\build\work" "$root\desktop\bebes_home_search.spec"
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

Copy-Item "$root\build\dist\Bebe's Home Search.exe" "$root\Bebe's Home Search.exe" -Force
Write-Host "Built: $root\Bebe's Home Search.exe"
