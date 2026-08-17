$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
uv run --extra inference --with pyinstaller pyinstaller --noconfirm --clean asr_workbench.spec
Compress-Archive -Path "dist\ASR-Workbench.exe" -DestinationPath "dist\ASR-Workbench-windows.zip" -Force
