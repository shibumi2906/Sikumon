[CmdletBinding()]
param(
    [string]$Python = ".build-venv\Scripts\python.exe",
    [string]$FfmpegDirectory = "C:\ffmpeg\bin",
    [string]$InnoCompiler = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$PythonPath = (Resolve-Path (Join-Path $ProjectRoot $Python)).Path
$MediaRoot = (Resolve-Path $FfmpegDirectory).Path
$VendorRoot = Join-Path $PSScriptRoot "vendor\ffmpeg"
$GeneratedRoot = Join-Path $PSScriptRoot "generated"
$VersionInfo = Join-Path $GeneratedRoot "version_info.txt"

foreach ($Name in @("ffmpeg.exe", "ffprobe.exe")) {
    $Source = Join-Path $MediaRoot $Name
    if (-not (Test-Path -LiteralPath $Source -PathType Leaf)) {
        throw "Required media tool is missing: $Source"
    }
}

if (-not $InnoCompiler) {
    $Candidates = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 7\ISCC.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"),
        "C:\Program Files\Inno Setup 7\ISCC.exe",
        "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
    )
    $InnoCompiler = $Candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
}
if (-not $InnoCompiler -or -not (Test-Path -LiteralPath $InnoCompiler -PathType Leaf)) {
    throw "Inno Setup compiler was not found. Pass -InnoCompiler with the ISCC.exe path."
}

$CleanTargets = @(
    (Join-Path $ProjectRoot "build"),
    (Join-Path $ProjectRoot "dist"),
    $VendorRoot,
    $GeneratedRoot
)
foreach ($Target in $CleanTargets) {
    if (Test-Path -LiteralPath $Target) {
        Remove-Item -LiteralPath $Target -Recurse -Force
    }
}

New-Item -ItemType Directory -Path $VendorRoot -Force | Out-Null
New-Item -ItemType Directory -Path $GeneratedRoot -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $MediaRoot "ffmpeg.exe") -Destination $VendorRoot
Copy-Item -LiteralPath (Join-Path $MediaRoot "ffprobe.exe") -Destination $VendorRoot

$FfmpegVersion = (& (Join-Path $VendorRoot "ffmpeg.exe") -version | Select-Object -First 1)
$FfprobeVersion = (& (Join-Path $VendorRoot "ffprobe.exe") -version | Select-Object -First 1)
Write-Host $FfmpegVersion
Write-Host $FfprobeVersion

$Version = (& $PythonPath (Join-Path $PSScriptRoot "generate_version_info.py") `
    --project-root $ProjectRoot --output $VersionInfo | Select-Object -Last 1).Trim()
if (-not $Version) {
    throw "Application version generation failed."
}

$OriginalPath = $env:PATH
# PyInstaller resolves native dependencies through PATH. Restrict it to Windows so tools
# bundled with an IDE/agent (Poppler, another Qt, libheif, etc.) cannot contaminate dist.
$env:PATH = "C:\Windows\System32;C:\Windows"
Push-Location $ProjectRoot
try {
    & $PythonPath -m PyInstaller --clean --noconfirm `
        --workpath (Join-Path $ProjectRoot "build\pyinstaller") `
        --distpath (Join-Path $ProjectRoot "dist") `
        (Join-Path $PSScriptRoot "Sikumon.spec")
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }

    & $InnoCompiler "/DAppVersion=$Version" (Join-Path $PSScriptRoot "Sikumon.iss")
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed with exit code $LASTEXITCODE" }
}
finally {
    Pop-Location
    $env:PATH = $OriginalPath
}

Write-Host "Built Sikumon $Version"
Write-Host (Join-Path $ProjectRoot "dist\Sikumon\Sikumon.exe")
Write-Host (Join-Path $ProjectRoot "dist\SikumonSetup.exe")
