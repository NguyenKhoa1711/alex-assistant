param([string]$ProjectRoot, [string]$AndroidJar)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path -LiteralPath $ProjectRoot).Path
$jdkName = (Get-ChildItem -LiteralPath "$root\toolchain\jdk" -Directory | Select-Object -First 1).Name
$jdk = "$root\toolchain\jdk\$jdkName"
$bt = "$root\toolchain\sdk\build-tools\35.0.0"
$env:JAVA_HOME = $jdk
$out = "$root\build\tests"
New-Item -ItemType Directory -Path "$out\classes","$out\dex" -Force | Out-Null
& "$jdk\bin\javac.exe" --release 8 -encoding UTF-8 -classpath "$AndroidJar;$root\build\classes" -d "$out\classes" "$root\tests\AlertPolicyTests.java" "$root\tests\QuietPolicyTests.java" "$root\tests\AlertDeviceTests.java"
if ($LASTEXITCODE -ne 0) { throw 'Test compilation failed' }
& "$jdk\bin\java.exe" -cp "$out\classes;$root\build\classes" vn.alex.phone.AlertPolicyTests
if ($LASTEXITCODE -ne 0) { throw 'Policy tests failed' }
& "$bt\aapt2.exe" link --manifest "$root\tests\AndroidManifest.xml" -I $AndroidJar --min-sdk-version 28 --target-sdk-version 35 -o "$out\resources.apk"
if ($LASTEXITCODE -ne 0) { throw 'Test resources failed' }
$classes = Get-ChildItem -LiteralPath "$out\classes" -Recurse -Filter '*.class' | ForEach-Object FullName
& "$bt\d8.bat" --lib $AndroidJar --classpath "$root\build\classes" --min-api 28 --output "$out\dex" $classes
if ($LASTEXITCODE -ne 0) { throw 'Test dex failed' }
$pack = @'
import sys,zipfile
resources,dex,out=sys.argv[1:]
with zipfile.ZipFile(resources) as source,zipfile.ZipFile(out,'w') as target:
    for item in source.infolist(): target.writestr(item,source.read(item.filename))
    target.write(dex,'classes.dex',compress_type=zipfile.ZIP_DEFLATED)
'@
& py -3 -c $pack "$out\resources.apk" "$out\dex\classes.dex" "$out\unsigned.apk"
if ($LASTEXITCODE -ne 0) { throw 'Test pack failed' }
& "$bt\zipalign.exe" -f 4 "$out\unsigned.apk" "$out\aligned.apk"
if ($LASTEXITCODE -ne 0) { throw 'Test alignment failed' }
& "$bt\apksigner.bat" sign --ks "$root\dist\alex-debug.keystore" --ks-key-alias androiddebugkey --ks-pass pass:android --key-pass pass:android --out "$out\tests.apk" "$out\aligned.apk"
if ($LASTEXITCODE -ne 0) { throw 'Test signing failed' }
Write-Output "TEST APK: $out\tests.apk"
