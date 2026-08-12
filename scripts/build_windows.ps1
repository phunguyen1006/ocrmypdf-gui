[CmdletBinding()]
param(
    [ValidateSet("onedir", "onefile")]
    [string]$Mode = "onedir",
    [string]$DistPath = "dist",
    [string]$WorkPath = "build"
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

# Some managed Windows workspaces mark generated folders read-only after a
# tool finishes. Clear that flag before PyInstaller performs its clean pass.
$generatedRoots = @($WorkPath, $DistPath) | ForEach-Object {
    if ([System.IO.Path]::IsPathRooted($_)) { $_ } else { Join-Path $projectRoot $_ }
} | Select-Object -Unique
foreach ($generatedRoot in $generatedRoots) {
    if (Test-Path -LiteralPath $generatedRoot) {
        Get-ChildItem -LiteralPath $generatedRoot -Force -Recurse -ErrorAction SilentlyContinue | ForEach-Object {
            try {
                $_.Attributes = $_.Attributes -band (-bnot [System.IO.FileAttributes]::ReadOnly)
            } catch {
                # PyInstaller will report the concrete path if it cannot clean it.
            }
        }
        try {
            $generatedItem = Get-Item -LiteralPath $generatedRoot
            $generatedItem.Attributes = $generatedItem.Attributes -band (-bnot [System.IO.FileAttributes]::ReadOnly)
        } catch {
            # Keep the build path usable when an old generated item is locked.
        }
    }
}

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "Python was not found in PATH. Install Python 3.10+ first."
}

$pyinstaller = python -c "import PyInstaller; print('ok')"
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller is not installed. Run: python -m pip install pyinstaller"
}

$args = @(
    "-m", "PyInstaller",
    "--noconfirm",
    "--clean",
    "--windowed",
    "--name", "OCRmyPDF-GUI",
    "--distpath", $DistPath,
    "--workpath", $WorkPath,
    "--paths", $projectRoot,
    "--icon", (Join-Path $projectRoot "assets\ocrmypdf-gui.ico"),
    "--add-data", "$projectRoot\assets;assets",
    "--add-data", "$projectRoot\app\data;app\data",
    "--hidden-import", "app.core.ocr_progress_plugin",
    "--collect-all", "ocrmypdf",
    "--collect-all", "pikepdf",
    "--collect-all", "pypdfium2",
    "--collect-all", "lingua",
    "app\main.py"
)

if ($Mode -eq "onefile") {
    $args = @("-m", "PyInstaller", "--noconfirm", "--clean", "--windowed", "--onefile", "--name", "OCRmyPDF-GUI", "--distpath", $DistPath, "--workpath", $WorkPath, "--paths", $projectRoot, "--icon", (Join-Path $projectRoot "assets\ocrmypdf-gui.ico"), "--add-data", "$projectRoot\assets;assets", "--add-data", "$projectRoot\app\data;app\data", "--hidden-import", "app.core.ocr_progress_plugin", "--collect-all", "ocrmypdf", "--collect-all", "pikepdf", "--collect-all", "pypdfium2", "--collect-all", "lingua", "app\main.py")
}

python @args
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller build failed."
}

Write-Host "Build completed: $projectRoot\$DistPath\OCRmyPDF-GUI"
