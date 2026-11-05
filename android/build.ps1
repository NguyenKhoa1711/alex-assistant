param(
    [string]$JdkRoot,
    [string]$BuildTools,
    [string]$AndroidJar,
    [string]$SigningKey,
    [string]$ApplicationId='vn.alex.phone.refresh',
    [string]$AppLabel='Alex 1.8.2',
    [string]$OutputName='Alex-moi-v1.8.2-fix-mic-23.apk'
)
$ErrorActionPreference='Stop'
if(-not(Test-Path -LiteralPath $SigningKey -PathType Leaf)){throw 'Missing signing key; this build never generates/replaces signing keys.'}
foreach($file in @("$JdkRoot\bin\javac.exe","$BuildTools\aapt2.exe","$BuildTools\d8.bat","$BuildTools\apksigner.bat",$AndroidJar)){
    if(-not(Test-Path -LiteralPath $file -PathType Leaf)){throw "Missing build dependency: $file"}
}
if($ApplicationId -notmatch '^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$' -or $OutputName -notmatch '^[a-zA-Z0-9._-]+\.apk$'){throw 'Invalid package or output name'}
$buildRoot=Join-Path ([IO.Path]::GetTempPath()) ('alex-apk-'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $buildRoot -Force | Out-Null
try {
    # Real ASCII copy: javac and batch SDK tools can fail on Vietnamese paths.
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'app') -Destination (Join-Path $buildRoot 'app') -Recurse
    Copy-Item -LiteralPath $AndroidJar -Destination (Join-Path $buildRoot 'android.jar')
    Copy-Item -LiteralPath $SigningKey -Destination (Join-Path $buildRoot 'signing.keystore')
    Copy-Item -LiteralPath "$BuildTools\lib\d8.jar" -Destination "$buildRoot\d8.jar"
    Copy-Item -LiteralPath "$BuildTools\lib\apksigner.jar" -Destination "$buildRoot\apksigner.jar"
    New-Item -ItemType Directory -Path "$buildRoot\generated","$buildRoot\classes","$buildRoot\dex" | Out-Null
    [xml]$manifest=Get-Content -LiteralPath "$buildRoot\app\src\main\AndroidManifest.xml" -Raw -Encoding UTF8
    $ns='http://schemas.android.com/apk/res/android'
    $original=$manifest.manifest.package
    $manager=[Xml.XmlNamespaceManager]::new($manifest.NameTable)
    $manager.AddNamespace('android',$ns)
    foreach($node in $manifest.SelectNodes('//*[@android:name]',$manager)){
        $name=$node.GetAttribute('name',$ns)
        if($name.StartsWith('.')){[void]$node.SetAttribute('name',$ns,$original+$name)}
    }
    $manifest.manifest.SetAttribute('package',$ApplicationId)
    [void]$manifest.manifest.application.SetAttribute('label',$ns,$AppLabel)
    $manifest.Save("$buildRoot\manifest.xml")
    $env:JAVA_HOME=$JdkRoot
    & "$BuildTools\aapt2.exe" compile --dir "$buildRoot\app\src\main\res" -o "$buildRoot\compiled-res.zip"
    if($LASTEXITCODE){throw 'Resource compile failed'}
    & "$BuildTools\aapt2.exe" link -o "$buildRoot\resources.apk" --manifest "$buildRoot\manifest.xml" -I "$buildRoot\android.jar" --min-sdk-version 28 --target-sdk-version 35 --custom-package vn.alex.phone "$buildRoot\compiled-res.zip" --java "$buildRoot\generated"
    if($LASTEXITCODE){throw 'Resource link failed'}
    $sources=Get-ChildItem -LiteralPath "$buildRoot\app\src\main\java","$buildRoot\generated" -Recurse -Filter '*.java' | ForEach-Object FullName
    & "$JdkRoot\bin\javac.exe" -encoding UTF-8 --release 8 -classpath "$buildRoot\android.jar;$buildRoot\app\libs\core-3.5.4.jar" -d "$buildRoot\classes" $sources
    if($LASTEXITCODE){throw 'Java compilation failed'}
    $classes=Get-ChildItem -LiteralPath "$buildRoot\classes" -Recurse -Filter '*.class' | ForEach-Object FullName
    & "$JdkRoot\bin\java.exe" -cp "$buildRoot\d8.jar" com.android.tools.r8.D8 --lib "$buildRoot\android.jar" --min-api 28 --output "$buildRoot\dex" $classes "$buildRoot\app\libs\core-3.5.4.jar"
    if($LASTEXITCODE){throw 'DEX compilation failed'}
    Copy-Item -LiteralPath "$buildRoot\resources.apk" -Destination "$buildRoot\unsigned.apk"
    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zip=[IO.Compression.ZipFile]::Open("$buildRoot\unsigned.apk",[IO.Compression.ZipArchiveMode]::Update)
    try {[IO.Compression.ZipFileExtensions]::CreateEntryFromFile($zip,"$buildRoot\dex\classes.dex",'classes.dex') | Out-Null} finally {$zip.Dispose()}
    & "$BuildTools\zipalign.exe" -f 4 "$buildRoot\unsigned.apk" "$buildRoot\aligned.apk"
    if($LASTEXITCODE){throw 'APK alignment failed'}
    & "$JdkRoot\bin\java.exe" -jar "$buildRoot\apksigner.jar" sign --ks "$buildRoot\signing.keystore" --ks-key-alias androiddebugkey --ks-pass pass:android --key-pass pass:android --out "$buildRoot\signed.apk" "$buildRoot\aligned.apk"
    if($LASTEXITCODE){throw 'APK signing failed'}
    & "$JdkRoot\bin\java.exe" -jar "$buildRoot\apksigner.jar" verify --verbose --print-certs "$buildRoot\signed.apk"
    if($LASTEXITCODE){throw 'Signature verification failed'}
    New-Item -ItemType Directory -Path (Join-Path $PSScriptRoot 'dist') -Force | Out-Null
    Copy-Item -LiteralPath "$buildRoot\signed.apk" -Destination (Join-Path $PSScriptRoot "dist\$OutputName") -Force
    Write-Output (Join-Path $PSScriptRoot "dist\$OutputName")
} finally {
    $resolved=[IO.Path]::GetFullPath($buildRoot)
    $temp=[IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\')+'\'
    if($resolved.StartsWith($temp,[StringComparison]::OrdinalIgnoreCase) -and (Split-Path -Leaf $resolved) -match '^alex-apk-[a-f0-9]{32}$'){
        Remove-Item -LiteralPath $resolved -Recurse -Force
    }
}
