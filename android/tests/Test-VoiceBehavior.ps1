param([string]$JdkRoot)
$ErrorActionPreference='Stop'
$temp=Join-Path ([IO.Path]::GetTempPath()) ('alex-voice-tests-'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $temp,(Join-Path $temp 'classes') -Force | Out-Null
try {
    foreach($name in @('VoiceGesture.java')){
        Copy-Item -LiteralPath (Join-Path $PSScriptRoot "..\app\src\main\java\vn\alex\phone\$name") -Destination (Join-Path $temp $name)
    }
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'VoiceBehaviorLab.java') -Destination $temp
    & "$JdkRoot\bin\javac.exe" --release 8 -encoding UTF-8 -d "$temp\classes" "$temp\VoiceGesture.java" "$temp\VoiceBehaviorLab.java"
    if($LASTEXITCODE){throw 'Voice test compilation failed'}
    & "$JdkRoot\bin\java.exe" -cp "$temp\classes" vn.alex.phone.VoiceBehaviorLab
    if($LASTEXITCODE){throw 'Voice behavior tests failed'}
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot '..\app\src\main\java\vn\alex\phone\VoiceCapture.java'),(Join-Path $PSScriptRoot 'VoiceCaptureLab.java') -Destination $temp
    $stubs=Get-ChildItem -LiteralPath (Join-Path $PSScriptRoot 'android-stubs') -Filter '*.java' -Recurse -File
    foreach($stub in $stubs){Copy-Item -LiteralPath $stub.FullName -Destination $temp}
    $sources=@($stubs | ForEach-Object { Join-Path $temp $_.Name })
    & "$JdkRoot\bin\javac.exe" --release 8 -encoding UTF-8 -d "$temp\classes" @sources "$temp\VoiceCapture.java" "$temp\VoiceCaptureLab.java"
    if($LASTEXITCODE){throw 'Capture test compilation failed'}
    & "$JdkRoot\bin\java.exe" -cp "$temp\classes" vn.alex.phone.VoiceCaptureLab
    if($LASTEXITCODE){throw 'Capture tests failed'}
} finally {
    $resolved=[IO.Path]::GetFullPath($temp)
    $root=[IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\')+'\'
    if($resolved.StartsWith($root,[StringComparison]::OrdinalIgnoreCase) -and (Split-Path -Leaf $resolved) -match '^alex-voice-tests-[a-f0-9]{32}$'){
        Remove-Item -LiteralPath $resolved -Recurse -Force
    }
}
