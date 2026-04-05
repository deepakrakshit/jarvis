$ErrorActionPreference = "Stop"

$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$python = Join-Path $repo "venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    throw "Python executable not found at $python"
}

Write-Host "Running controller compile checks..."
& $python -m py_compile `
    "$repo\services\actions\file_controller.py" `
    "$repo\services\system\cmd_control.py" `
    "$repo\tests\stress\test_file_controller.py" `
    "$repo\tests\stress\test_cmd_control.py"

Write-Host "Running stress tests..."
& $python -m unittest discover -s "$repo\tests\stress" -p "test_file_controller.py"
& $python -m unittest discover -s "$repo\tests\stress" -p "test_cmd_control.py"

Write-Host "Controller stress suite passed."
