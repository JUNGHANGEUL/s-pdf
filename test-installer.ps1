$ErrorActionPreference = 'Stop'
$spdfSource = $PSScriptRoot
$spdfWorkspace = Split-Path -Parent $spdfSource
$spdfTest = Join-Path $spdfWorkspace ('tmp\spdf-installer-test-' + [Guid]::NewGuid().ToString('N'))
$spdfFixture = Join-Path $spdfTest 'payload'
New-Item -ItemType Directory -Path $spdfFixture -Force | Out-Null
[IO.File]::WriteAllText((Join-Path $spdfFixture 'app.dat'),'new version')
[IO.File]::WriteAllText((Join-Path $spdfFixture 'other.dat'),'other file')
[IO.File]::WriteAllText((Join-Path $spdfFixture 'install-manifest.txt'),"app.dat`nother.dat`n")
Add-Type -AssemblyName System.IO.Compression.FileSystem
$spdfZip = Join-Path $spdfTest 'payload.zip'
[IO.Compression.ZipFile]::CreateFromDirectory($spdfFixture,$spdfZip)
& (Join-Path $spdfSource '.venv\Scripts\python.exe') (Join-Path $spdfSource 'prepare_build.py')
if ($LASTEXITCODE -ne 0) { throw 'Preparing installer sources failed' }
$spdfCompiler = 'C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe'
$spdfExe = Join-Path $spdfTest 'InstallerTests.exe'
$spdfSources = @('Setup.cs','InstallFiles.cs','FileAssociations.cs','InstallLock.cs','BuildInfo.cs') | ForEach-Object { Join-Path $spdfSource ('installer\' + $_) }
& $spdfCompiler /nologo /target:exe /platform:x64 /main:InstallerTests /reference:System.Windows.Forms.dll /reference:System.Drawing.dll /reference:System.Web.Extensions.dll /reference:System.IO.Compression.dll /reference:System.IO.Compression.FileSystem.dll ('/win32icon:' + (Join-Path $spdfSource 'assets\spdf.ico')) ('/resource:' + $spdfZip + ',payload.zip') ('/out:' + $spdfExe) @spdfSources (Join-Path $spdfSource 'tests\InstallerTests.cs')
if ($LASTEXITCODE -ne 0) { throw 'Installer test compile failed' }
& $spdfExe $spdfTest
if ($LASTEXITCODE -ne 0) { throw 'Installer tests failed' }
$spdfRelease = Join-Path $spdfWorkspace 'output\S.PDF'
New-Item -ItemType Directory -Path $spdfRelease -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $spdfTest 'installer.png') -Destination (Join-Path $spdfRelease 'S.PDF_설치화면.png') -Force
