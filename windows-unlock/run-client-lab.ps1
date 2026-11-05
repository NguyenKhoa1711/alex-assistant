$ErrorActionPreference='Stop'
$link=Join-Path $env:TEMP "alex-client-tests-$PID"
try {
    New-Item -ItemType Junction -Path $link -Target $PSScriptRoot | Out-Null
    $jdk=(Get-ChildItem -LiteralPath "$link\toolchain\jdk" -Directory | Select-Object -First 1).FullName
    $src="$link\app\src\main\java\vn\alex\phone"
    & "$jdk\bin\javac.exe" -encoding UTF-8 -d "$link\build\client-test-classes" "$src\PrivateAddress.java" "$src\PinnedTls.java" "$src\UnlockAttempt.java" "$src\UnlockTransport.java" "$link\tests\UnlockClientLab.java"
    if($LASTEXITCODE -ne 0) { throw 'Client test compilation failed.' }
    & "$jdk\bin\java.exe" -cp "$link\build\client-test-classes" vn.alex.phone.UnlockClientLab | Tee-Object -FilePath "$PSScriptRoot\build\client-lab-result.txt"
    if($LASTEXITCODE -ne 0) { throw 'Client tests failed.' }
} finally {
    $item=Get-Item -LiteralPath $link -Force -ErrorAction SilentlyContinue
    if($item -and $item.LinkType -eq 'Junction' -and [IO.Path]::GetFullPath([string]$item.Target).TrimEnd('\') -eq [IO.Path]::GetFullPath($PSScriptRoot).TrimEnd('\')) {
        [IO.Directory]::Delete($link,$false)
    }
}
