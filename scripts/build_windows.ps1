param(
    [string]$Python = ".\.venv\Scripts\python.exe"
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Push-Location $projectRoot
try {
    $pythonPath = Join-Path $projectRoot $Python
    if (-not (Test-Path -LiteralPath $pythonPath)) {
        throw "Python environment not found at $pythonPath. Create .venv and install requirements.txt first."
    }
    if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
        throw "Node.js/npm is required only to rebuild the frontend. Install Node.js on the build machine, then rerun this script."
    }

    if (-not (Test-Path -LiteralPath (Join-Path $projectRoot "node_modules"))) {
        npm ci
        if ($LASTEXITCODE -ne 0) { throw "npm ci failed; see the output above." }
    } else {
        Write-Output "Using the existing frontend dependency install to avoid replacing node_modules while a dev server may be running."
    }
    npm run build
    if ($LASTEXITCODE -ne 0) { throw "The frontend build failed; see the output above." }

    & $pythonPath -m pip install -r requirements-packaging.txt
    if ($LASTEXITCODE -ne 0) { throw "Installing the pinned packaging dependencies failed." }

    $releaseDir = Join-Path $projectRoot "releases\GridShift-Windows-x64"
    $distDir = Join-Path $projectRoot "build\gridshift-pyinstaller-dist"
    $workDir = Join-Path $projectRoot "build\gridshift-pyinstaller-work"
    New-Item -ItemType Directory -Force -Path $releaseDir | Out-Null
    New-Item -ItemType Directory -Force -Path (Split-Path $distDir -Parent) | Out-Null
    & $pythonPath -m PyInstaller --noconfirm --clean --distpath $distDir --workpath $workDir packaging\GridShift.spec
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed; see the output above." }

    $appOutput = Join-Path $distDir "GridShift"
    if (-not (Test-Path -LiteralPath (Join-Path $appOutput "GridShift.exe"))) {
        throw "PyInstaller completed without producing GridShift\GridShift.exe."
    }
    Copy-Item -Path (Join-Path $distDir "GridShift\*") -Destination $releaseDir -Recurse -Force
    Copy-Item -LiteralPath "packaging\README-Portable.txt" -Destination (Join-Path $releaseDir "README-Run.txt") -Force
    $zipPath = Join-Path $projectRoot "releases\GridShift-Windows-x64.zip"
    Compress-Archive -Path $releaseDir -DestinationPath $zipPath -Force

    Write-Output "Windows x64 executable: $releaseDir\GridShift.exe"
    Write-Output "Portable transfer archive: $zipPath"
} finally {
    Pop-Location
}
