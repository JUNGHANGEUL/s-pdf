$ErrorActionPreference = 'Stop'
$spdfWorkspace = Split-Path -Parent $PSScriptRoot
$spdfRelease = Join-Path $spdfWorkspace 'output\S.PDF'
$spdfTest = Join-Path $spdfWorkspace ('tmp\spdf-release-check-' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $spdfTest -Force | Out-Null
function Invoke-SPDFExecutable {
    param([string]$Executable,[string[]]$Arguments)
    $spdfInfo = [Diagnostics.ProcessStartInfo]::new()
    $spdfInfo.FileName = $Executable
    $spdfInfo.UseShellExecute = $false
    $spdfInfo.CreateNoWindow = $true
    $spdfInfo.RedirectStandardError = $true
    $spdfInfo.RedirectStandardOutput = $true
    foreach ($spdfArgument in $Arguments) { $spdfInfo.ArgumentList.Add($spdfArgument) }
    $spdfProcess = [Diagnostics.Process]::Start($spdfInfo)
    $spdfOutput = $spdfProcess.StandardOutput.ReadToEndAsync()
    $spdfErrors = $spdfProcess.StandardError.ReadToEndAsync()
    if (-not $spdfProcess.WaitForExit(60000)) {
        $spdfProcess.Kill($true)
        $spdfProcess.WaitForExit()
        $spdfTimedOutError = $spdfErrors.GetAwaiter().GetResult()
        if ($spdfTimedOutError) { Write-Output $spdfTimedOutError }
        throw 'Release verification timed out'
    }
    $spdfStdout = $spdfOutput.GetAwaiter().GetResult()
    $spdfStderr = $spdfErrors.GetAwaiter().GetResult()
    if ($spdfStdout) { Write-Output $spdfStdout }
    if ($spdfProcess.ExitCode -ne 0) {
        if ($spdfStderr) { Write-Output $spdfStderr }
        throw ('Release executable returned ' + $spdfProcess.ExitCode)
    }
}
$spdfSetup = Join-Path $spdfRelease 'S.PDF-Setup.exe'
$spdfExtract = Join-Path $spdfTest '프로그램 [설치 파일 검증]'
Invoke-SPDFExecutable -Executable $spdfSetup -Arguments @('/extract',$spdfExtract)
$spdfPayload = Join-Path $spdfWorkspace 'tmp\spdf-build\native-runtime\S.PDF'
$spdfFiles = Get-ChildItem -LiteralPath $spdfPayload -Recurse -File
foreach ($spdfFile in $spdfFiles) {
    $spdfRelative = $spdfFile.FullName.Substring($spdfPayload.Length + 1)
    $spdfExtractedFile = Join-Path $spdfExtract $spdfRelative
    if ((Get-FileHash -LiteralPath $spdfFile.FullName -Algorithm SHA256).Hash -ne (Get-FileHash -LiteralPath $spdfExtractedFile -Algorithm SHA256).Hash) {
        throw ('Installer payload differs: ' + $spdfRelative)
    }
}
'PASS: installer extracted ' + $spdfFiles.Count + ' files with matching SHA256 hashes.'
$spdfSample = (Get-ChildItem -LiteralPath $spdfWorkspace -Filter *.pdf -File | Select-Object -First 1).FullName
$spdfUiRoot = Join-Path $spdfTest '화면과 기능 검증'
$spdfTestArguments = @('--self-test','--test-root',$spdfUiRoot)
if ($spdfSample) { $spdfTestArguments += @('--sample',$spdfSample) }
Invoke-SPDFExecutable -Executable (Join-Path $spdfExtract 'S.PDF.exe') -Arguments $spdfTestArguments
$spdfResult = Get-Content -LiteralPath (Join-Path $spdfUiRoot 'result.json') -Raw | ConvertFrom-Json
if (-not $spdfResult.ok) { throw $spdfResult.error }
$spdfResult.checks | ForEach-Object { 'PASS: ' + $_ }
if ($spdfSample) { Copy-Item -LiteralPath (Join-Path $spdfUiRoot '06_실제문서_캡처화면.png') -Destination (Join-Path $spdfRelease 'S.PDF_실행화면.png') -Force }
Copy-Item -LiteralPath (Join-Path $spdfUiRoot 'result.json') -Destination (Join-Path $spdfRelease '검증결과.json') -Force
$spdfHash = (Get-FileHash -LiteralPath $spdfSetup -Algorithm SHA256).Hash
if (-not (Get-Content -LiteralPath (Join-Path $spdfRelease 'SHA256.txt') -Raw).Contains($spdfHash)) { throw 'Installer checksum file differs' }
'PASS: final installer checksum.'
$spdfTest
