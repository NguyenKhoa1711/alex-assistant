$ErrorActionPreference='Stop'
$framework='C:\Windows\Microsoft.NET\Framework64\v4.0.30319'
& "$framework\csc.exe" /nologo /platform:x64 /target:exe "/out:$PSScriptRoot\AlexUnlock.exe" /reference:System.ServiceProcess.dll /reference:Microsoft.CSharp.dll "/reference:$framework\WPF\UIAutomationClient.dll" "/reference:$framework\WPF\UIAutomationTypes.dll" "/reference:$framework\WPF\WindowsBase.dll" "$PSScriptRoot\AlexUnlock.cs"
if($LASTEXITCODE -ne 0) { throw 'Compilation failed.' }
& "$PSScriptRoot\AlexUnlock.exe" --self-test
if($LASTEXITCODE -ne 0) { throw 'Self-test failed.' }
