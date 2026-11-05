$ErrorActionPreference='Stop'
$run=Join-Path $PSScriptRoot ('build\lab-'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $run | Out-Null
$fw='C:\Windows\Microsoft.NET\Framework64\v4.0.30319'
& "$fw\csc.exe" /nologo /platform:x64 /target:exe /main:UnlockLab "/out:$run\UnlockLab.exe" /reference:System.ServiceProcess.dll "/reference:$fw\WPF\UIAutomationClient.dll" "/reference:$fw\WPF\UIAutomationTypes.dll" "/reference:$fw\WPF\WindowsBase.dll" "$PSScriptRoot\windows\AlexUnlock.cs" "$PSScriptRoot\tests\UnlockLab.cs"
if($LASTEXITCODE -ne 0) { throw 'Compilation failed.' }
& "$run\UnlockLab.exe" | Tee-Object -FilePath "$PSScriptRoot\build\windows-lab-result.txt"
exit $LASTEXITCODE
