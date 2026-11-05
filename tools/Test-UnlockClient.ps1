param([Parameter(Mandatory=$true)][string]$JdkRoot,[string]$SourceRoot,[string]$ReportPath)
$ErrorActionPreference='Stop'
if(-not $SourceRoot){$SourceRoot=Split-Path -Parent $PSScriptRoot}
$src=Join-Path $SourceRoot 'android\app\src\main\java\vn\alex\phone'
$lab=Join-Path $SourceRoot 'android\tests\UnlockClientLab.java'
if(-not (Test-Path -LiteralPath (Join-Path $JdkRoot 'bin\javac.exe'))){throw 'JdkRoot must contain bin\javac.exe'}
$tempRoot=[IO.Path]::GetFullPath([IO.Path]::GetTempPath())
$testRoot=Join-Path $tempRoot ('alex-client-test-'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $testRoot -ErrorAction Stop | Out-Null
try{
    foreach($name in @('PrivateAddress.java','PinnedTls.java','UnlockAttempt.java','UnlockTransport.java')){
        Copy-Item -LiteralPath (Join-Path $src $name) -Destination (Join-Path $testRoot $name)
    }
    Copy-Item -LiteralPath $lab -Destination (Join-Path $testRoot 'UnlockClientLab.java')
    $classes=Join-Path $testRoot 'classes'
    New-Item -ItemType Directory -Path $classes | Out-Null
    $files=Get-ChildItem -LiteralPath $testRoot -Filter '*.java' -File | ForEach-Object FullName
    & (Join-Path $JdkRoot 'bin\javac.exe') -encoding UTF-8 --release 8 -d $classes $files
    if($LASTEXITCODE -ne 0){throw 'Java test compilation failed'}
    $output=& (Join-Path $JdkRoot 'bin\java.exe') -cp $classes vn.alex.phone.UnlockClientLab
    $exit=$LASTEXITCODE
    if($ReportPath){$output | Set-Content -LiteralPath $ReportPath -Encoding utf8}
    $output
    if($exit -ne 0){throw 'Java client tests failed'}
}finally{
    $resolved=[IO.Path]::GetFullPath($testRoot)
    if($resolved.StartsWith($tempRoot,[StringComparison]::OrdinalIgnoreCase) -and
        (Split-Path -Leaf $resolved) -match '^alex-client-test-[a-f0-9]{32}$'){
        Remove-Item -LiteralPath $resolved -Recurse -Force
    }
}
