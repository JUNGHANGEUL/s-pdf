param([switch]$SkipFreeze)
$ErrorActionPreference = 'Stop'
$spdfSource = $PSScriptRoot
$spdfWorkspace = Split-Path -Parent $spdfSource
$spdfPython = Join-Path $spdfSource '.venv\Scripts\python.exe'
$spdfBuild = Join-Path $spdfWorkspace 'tmp\spdf-build'
$spdfRelease = Join-Path $spdfWorkspace 'output\S.PDF'
New-Item -ItemType Directory -Path $spdfBuild,$spdfRelease -Force | Out-Null
& $spdfPython (Join-Path $spdfSource 'prepare_build.py')
if ($LASTEXITCODE -ne 0) { throw 'Preparing sources failed' }
if (-not $SkipFreeze) {
    $spdfSavedPath = $env:PATH
    $spdfSitePackages = Join-Path $spdfSource '.venv\Lib\site-packages'
    try {
        # Tool runtimes can put Poppler's incompatible ICU DLL on PATH. Qt needs
        # Windows' ICU API; analyze dependencies in a clean application PATH.
        $env:PATH = @((Join-Path $spdfSource '.venv\Scripts'),(Join-Path $spdfSitePackages 'PySide6'),(Join-Path $spdfSitePackages 'shiboken6'),(Join-Path $env:WINDIR 'System32'),$env:WINDIR) -join ';'
        & $spdfPython -m PyInstaller --noconfirm --clean --onedir --windowed --name S.PDF --icon (Join-Path $spdfSource 'assets\spdf.ico') --add-data ((Join-Path $spdfSource 'assets') + ';assets') --collect-binaries pymupdf --exclude-module pymupdf.layout --exclude-module onnxruntime --exclude-module pymupdf4llm --exclude-module pymupdf_layout --exclude-module pytest --exclude-module tkinter --exclude-module matplotlib --distpath (Join-Path $spdfBuild 'dist') --workpath (Join-Path $spdfBuild 'work') --specpath $spdfBuild (Join-Path $spdfSource 'main.py')
    } finally { $env:PATH = $spdfSavedPath }
    if ($LASTEXITCODE -ne 0) { throw 'Application packaging failed' }
}
$spdfCollected = Join-Path $spdfBuild 'dist\S.PDF'
if (-not (Test-Path -LiteralPath (Join-Path $spdfCollected 'S.PDF.exe'))) { throw 'Collected application is missing' }
$spdfPayload = Join-Path $spdfBuild 'native-runtime\S.PDF'
& $spdfPython (Join-Path $spdfSource 'prepare_runtime.py') $spdfCollected $spdfPayload (Join-Path $spdfBuild 'work\S.PDF\PYZ-00.pyz')
if ($LASTEXITCODE -ne 0) { throw 'Runtime preparation failed' }
$spdfCompiler = 'C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe'
$spdfCommon = @('/nologo','/target:winexe','/platform:x64','/optimize+',('/win32manifest:' + (Join-Path $spdfSource 'installer\app.manifest')),('/win32icon:' + (Join-Path $spdfSource 'assets\spdf.ico')),'/reference:System.Windows.Forms.dll','/reference:System.Drawing.dll')
& $spdfCompiler @spdfCommon ('/out:' + (Join-Path $spdfPayload 'S.PDF.exe')) (Join-Path $spdfSource 'installer\Launcher.cs') (Join-Path $spdfSource 'installer\InstallLock.cs') (Join-Path $spdfSource 'installer\BuildInfo.cs')
if ($LASTEXITCODE -ne 0) { throw 'Launcher compile failed' }
& $spdfCompiler @spdfCommon ('/out:' + (Join-Path $spdfPayload 'Uninstall.exe')) (Join-Path $spdfSource 'installer\Uninstall.cs') (Join-Path $spdfSource 'installer\InstallFiles.cs') (Join-Path $spdfSource 'installer\FileAssociations.cs')
if ($LASTEXITCODE -ne 0) { throw 'Uninstaller compile failed' }
Copy-Item -LiteralPath (Join-Path $spdfSource '사용방법.txt'),(Join-Path $spdfSource 'THIRD_PARTY_NOTICES.txt'),(Join-Path $spdfSource 'LICENSE.txt') -Destination $spdfPayload -Force
$spdfLicenseDir = Join-Path $spdfPayload 'licenses'
New-Item -ItemType Directory -Path $spdfLicenseDir -Force | Out-Null
Get-ChildItem -LiteralPath (Join-Path $spdfSource 'licenses') -File | Copy-Item -Destination $spdfLicenseDir -Force
Copy-Item -LiteralPath (Join-Path $spdfSource 'assets\Lucide-LICENSE.txt') -Destination $spdfLicenseDir -Force
Copy-Item -LiteralPath (Join-Path $spdfSource 'assets\tessdata\LICENSE.txt') -Destination (Join-Path $spdfLicenseDir 'Tesseract-tessdata-Apache-2.0.txt') -Force
& $spdfPython (Join-Path $spdfSource 'source_archive.py') (Join-Path $spdfRelease 'S.PDF_Source.zip')
if ($LASTEXITCODE -ne 0) { throw 'Source archive failed' }
Copy-Item -LiteralPath (Join-Path $spdfRelease 'S.PDF_Source.zip') -Destination $spdfPayload -Force
$spdfManifest = Get-ChildItem -LiteralPath $spdfPayload -Recurse -File | Where-Object Name -ne 'install-manifest.txt' | ForEach-Object { $_.FullName.Substring($spdfPayload.Length + 1) }
[IO.File]::WriteAllLines((Join-Path $spdfPayload 'install-manifest.txt'),[string[]]$spdfManifest,[Text.Encoding]::UTF8)
Add-Type -AssemblyName System.IO.Compression.FileSystem
$spdfZip = Join-Path $spdfBuild ('payload-' + [Guid]::NewGuid().ToString('N') + '.zip')
[IO.Compression.ZipFile]::CreateFromDirectory($spdfPayload,$spdfZip,[IO.Compression.CompressionLevel]::Optimal,$false)
$spdfSetup = Join-Path $spdfRelease 'S.PDF-Setup.exe'
& $spdfCompiler @spdfCommon '/reference:System.IO.Compression.dll' '/reference:System.IO.Compression.FileSystem.dll' '/reference:System.Web.Extensions.dll' ('/resource:' + $spdfZip + ',payload.zip') ('/out:' + $spdfSetup) (Join-Path $spdfSource 'installer\Setup.cs') (Join-Path $spdfSource 'installer\InstallFiles.cs') (Join-Path $spdfSource 'installer\FileAssociations.cs') (Join-Path $spdfSource 'installer\InstallLock.cs') (Join-Path $spdfSource 'installer\BuildInfo.cs')
if ($LASTEXITCODE -ne 0) { throw 'Installer compile failed' }
Copy-Item -LiteralPath (Join-Path $spdfSource '사용방법.txt') -Destination $spdfRelease -Force
$spdfHash = (Get-FileHash -LiteralPath $spdfSetup -Algorithm SHA256).Hash
[IO.File]::WriteAllText((Join-Path $spdfRelease 'SHA256.txt'),$spdfHash + '  S.PDF-Setup.exe' + [Environment]::NewLine,[Text.Encoding]::UTF8)
& $spdfPython (Join-Path $spdfSource 'release_manifest.py') $spdfSetup
if ($LASTEXITCODE -ne 0) { throw 'Release manifest failed' }
Get-Item -LiteralPath $spdfSetup | Select-Object FullName,Length
