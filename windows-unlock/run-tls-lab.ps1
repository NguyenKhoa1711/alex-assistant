param([switch]$OfflineOnly)
$ErrorActionPreference='Stop'
$link=Join-Path $env:TEMP "alex-tls-tests-$PID"
try {
    New-Item -ItemType Junction -Path $link -Target $PSScriptRoot | Out-Null
    $jdk=(Get-ChildItem -LiteralPath "$link\toolchain\jdk" -Directory | Select-Object -First 1).FullName
    & "$jdk\bin\javac.exe" -encoding UTF-8 -d "$link\build\test-classes" "$link\app\src\main\java\vn\alex\phone\PinnedTls.java" "$link\tests\TlsLab.java" "$link\tests\CertificateLab.java"
    if($LASTEXITCODE -ne 0) { throw 'Java test compilation failed.' }
    $testArgs=@("$link\tests\tls_lab.py",'--java',"$jdk\bin\java.exe",'--classes',"$link\build\test-classes")
    if($OfflineOnly) { $testArgs+='--offline-only' }
    & 'D:\HỌC TẬP\dự án trợ lý ảo\trợ lý ảo-local\outputs\Bionic-pet\.venv\Scripts\python.exe' @testArgs
    if($LASTEXITCODE -ne 0) { throw 'TLS test failed.' }
} finally {
    $item=Get-Item -LiteralPath $link -Force -ErrorAction SilentlyContinue
    if($item -and $item.LinkType -eq 'Junction' -and [IO.Path]::GetFullPath([string]$item.Target).TrimEnd('\') -eq [IO.Path]::GetFullPath($PSScriptRoot).TrimEnd('\')) {
        [IO.Directory]::Delete($link,$false)
    }
}
