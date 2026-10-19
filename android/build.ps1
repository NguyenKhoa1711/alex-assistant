param([string]$AsciiRoot = '', [string]$AndroidJar = '')

$ErrorActionPreference = 'Stop'
$createdLink = $false
if (-not $AsciiRoot) {
    $AsciiRoot = Join-Path $env:TEMP "alex-android-build-$PID"
    New-Item -ItemType Junction -Path $AsciiRoot -Target $PSScriptRoot | Out-Null
    $createdLink = $true
}
try {
    $root = (Resolve-Path -LiteralPath $AsciiRoot).Path
    if (-not (Test-Path -LiteralPath "$root\app\src\main\AndroidManifest.xml")) {
        throw 'Đường dẫn ASCII không trỏ tới dự án Alex Android.'
    }
    $jdk = (Get-ChildItem -LiteralPath "$root\toolchain\jdk" -Directory | Select-Object -First 1).FullName
    $sdk = "$root\toolchain\sdk"
    $buildTools = "$sdk\build-tools\35.0.0"
    if (-not $AndroidJar) { $AndroidJar = "$sdk\platforms\android-35\android.jar" }
    $zxingJar = "$root\app\libs\core-3.5.4.jar"
    $env:JAVA_HOME = $jdk
    $env:ANDROID_HOME = $sdk
    New-Item -ItemType Directory -Force -Path "$root\build\classes", "$root\build\dex", "$root\dist" | Out-Null

    New-Item -ItemType Directory -Force -Path "$root\build\generated" | Out-Null
    & "$buildTools\aapt2.exe" compile --dir "$root\app\src\main\res" -o "$root\build\compiled-res.zip"
    if ($LASTEXITCODE -ne 0) { throw 'aapt2 compile thất bại.' }
    & "$buildTools\aapt2.exe" link -o "$root\build\resources.apk" --manifest "$root\app\src\main\AndroidManifest.xml" -I $androidJar --min-sdk-version 28 --target-sdk-version 35 "$root\build\compiled-res.zip" --java "$root\build\generated"
    if ($LASTEXITCODE -ne 0) { throw 'aapt2 link thất bại.' }
    $sources = Get-ChildItem -LiteralPath "$root\app\src\main\java" -Recurse -Filter '*.java' | ForEach-Object FullName
    & "$jdk\bin\javac.exe" -encoding UTF-8 --release 8 -classpath "$androidJar;$zxingJar" -d "$root\build\classes" $sources "$root\build\generated\vn\alex\phone\R.java"
    if ($LASTEXITCODE -ne 0) { throw 'javac biên dịch thất bại.' }
    $classes = Get-ChildItem -LiteralPath "$root\build\classes" -Recurse -Filter '*.class' | ForEach-Object FullName
    & "$buildTools\d8.bat" --lib $androidJar --min-api 28 --output "$root\build\dex" $classes $zxingJar
    if ($LASTEXITCODE -ne 0) { throw 'D8 biên dịch thất bại.' }

    $pack = @'
import pathlib,sys,zipfile
resources,dex,output=map(pathlib.Path,sys.argv[1:])
with zipfile.ZipFile(resources) as source,zipfile.ZipFile(output,'w') as target:
    for item in source.infolist():
        target.writestr(item,source.read(item.filename))
    target.write(dex,'classes.dex',compress_type=zipfile.ZIP_DEFLATED)
'@
    & py -3 -c $pack "$root\build\resources.apk" "$root\build\dex\classes.dex" "$root\build\unsigned.apk"
    if ($LASTEXITCODE -ne 0) { throw 'Không ghép được classes.dex.' }
    & "$buildTools\zipalign.exe" -f 4 "$root\build\unsigned.apk" "$root\build\aligned.apk"
    if ($LASTEXITCODE -ne 0) { throw 'zipalign thất bại.' }
    $key = "$root\dist\alex-debug.keystore"
    if (-not (Test-Path -LiteralPath $key)) {
        if (Get-ChildItem -LiteralPath "$root\dist" -Filter 'Alex-Android*.apk' -File | Select-Object -First 1) {
            throw 'Thiếu khóa ký APK cũ. Không tạo khóa mới vì bản cập nhật sẽ không cài đè được và làm mất dữ liệu ghép nối.'
        }
        & "$jdk\bin\keytool.exe" -genkeypair -keystore $key -storepass android -keypass android -alias androiddebugkey -dname 'CN=Alex Android Debug,O=Alex,C=VN' -keyalg RSA -keysize 3072 -validity 3650
        if ($LASTEXITCODE -ne 0) { throw 'Không tạo được khóa ký APK.' }
    }
    & "$buildTools\apksigner.bat" sign --ks $key --ks-key-alias androiddebugkey --ks-pass pass:android --key-pass pass:android --out "$root\dist\Alex-Android.apk" "$root\build\aligned.apk"
    if ($LASTEXITCODE -ne 0) { throw 'Không ký được APK.' }
    & "$buildTools\apksigner.bat" verify --verbose "$root\dist\Alex-Android.apk"
    if ($LASTEXITCODE -ne 0) { throw 'APK không xác thực được chữ ký.' }
    Write-Output "APK: $PSScriptRoot\dist\Alex-Android.apk"
} finally {
    if ($createdLink) {
        $link = Get-Item -LiteralPath $AsciiRoot -Force -ErrorAction SilentlyContinue
        if ($link -and $link.LinkType -eq 'Junction' -and
            [IO.Path]::GetFullPath([string]$link.Target).TrimEnd('\') -eq
            [IO.Path]::GetFullPath($PSScriptRoot).TrimEnd('\')) {
            [IO.Directory]::Delete($AsciiRoot, $false)
        }
    }
}
