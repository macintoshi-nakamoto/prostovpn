[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$script:checkCount = 0

function Resolve-RepoPath {
    param([Parameter(Mandatory)][string]$RelativePath)
    return Join-Path $repoRoot ($RelativePath -replace '/', [IO.Path]::DirectorySeparatorChar)
}

function Assert-True {
    param(
        [Parameter(Mandatory)][bool]$Condition,
        [Parameter(Mandatory)][string]$Message
    )
    $script:checkCount++
    if (-not $Condition) {
        throw "Brand verification failed: $Message"
    }
}

function Get-RepoText {
    param([Parameter(Mandatory)][string]$RelativePath)
    $path = Resolve-RepoPath $RelativePath
    Assert-True (Test-Path -LiteralPath $path -PathType Leaf) "missing file: $RelativePath"
    return [IO.File]::ReadAllText($path)
}

function Assert-Contains {
    param(
        [Parameter(Mandatory)][string]$RelativePath,
        [Parameter(Mandatory)][string]$Needle
    )
    $content = Get-RepoText $RelativePath
    Assert-True ($content.Contains($Needle)) "$RelativePath does not contain '$Needle'"
}

function Assert-NotContains {
    param(
        [Parameter(Mandatory)][string]$RelativePath,
        [Parameter(Mandatory)][string]$Needle
    )
    $content = Get-RepoText $RelativePath
    Assert-True (-not $content.Contains($Needle)) "$RelativePath still contains legacy identity '$Needle'"
}

$requiredFiles = @(
    'LICENSE',
    'NOTICE',
    'README.md',
    'README_RU.md',
    'cmake/NexaBranding.cmake',
    'branding/nexa-master-icon.png',
    'client/images/nexaBigLogo.png',
    'client/images/NexaVPN.png',
    'client/images/icon.png',
    'client/images/app.ico',
    'client/images/app.icns',
    'client/images/controls/nexa.svg',
    'client/android/res/drawable/ic_nexa_round.xml',
    'client/ios/app/NexaVPNLaunchScreen.storyboard',
    'client/ios/networkextension/NexaVPNNetworkExtension.entitlements',
    'client/macos/networkextension/NexaVPNNetworkExtension.entitlements',
    'client/platforms/windows/nexavpn.rc.in',
    'service/server/nexavpn-service.rc.in',
    'deploy/data/linux/NexaVPN.desktop',
    'deploy/data/linux/NexaVPN.service',
    'deploy/data/linux/NexaVPN.png',
    'deploy/data/macos/NexaVPN.plist',
    'deploy/data/macos/pf/nexa.conf',
    'deploy/data/pf-templates/nexa.400.allowPIA.conf.in'
)

foreach ($relativePath in $requiredFiles) {
    Assert-True (Test-Path -LiteralPath (Resolve-RepoPath $relativePath) -PathType Leaf) "missing required file: $relativePath"
}

$removedLegacyFiles = @(
    'client/images/AmneziaVPN.png',
    'client/images/amneziaBigLogo.png',
    'client/images/controls/amnezia.svg',
    'client/android/res/drawable/ic_amnezia_round.xml',
    'client/ios/app/AmneziaVPNLaunchScreen.storyboard',
    'client/ios/networkextension/AmneziaVPNNetworkExtension.entitlements',
    'client/macos/networkextension/AmneziaVPNNetworkExtension.entitlements',
    'client/platforms/windows/amneziavpn.rc.in',
    'service/server/amneziavpn-service.rc.in',
    'deploy/data/macos/pf/amn.conf',
    'deploy/data/pf-templates/amn.400.allowPIA.conf.in'
)

foreach ($relativePath in $removedLegacyFiles) {
    Assert-True (-not (Test-Path -LiteralPath (Resolve-RepoPath $relativePath))) "legacy branded file still exists: $relativePath"
}

$legacyPfResources = @(Get-ChildItem -LiteralPath (Resolve-RepoPath 'deploy/data/macos/pf') -Filter 'amn*')
Assert-True ($legacyPfResources.Count -eq 0) 'legacy Amnezia PF resource names still exist'

Assert-Contains 'cmake/NexaBranding.cmake' 'set(NEXA_DISPLAY_NAME "Nexa VPN"'
Assert-Contains 'cmake/NexaBranding.cmake' 'set(NEXA_ORGANIZATION_NAME "NexaVPN"'
Assert-Contains 'cmake/NexaBranding.cmake' 'NEXA_ENABLE_UPSTREAM_UPDATES'
Assert-Contains 'cmake/NexaBranding.cmake' 'OFF'
Assert-Contains 'client/android/build.gradle.kts' 'applicationId = "com.nexavpn.client"'
Assert-Contains 'client/android/build.gradle.kts' 'namespace = "com.nexavpn.client"'
Assert-Contains 'client/android/AndroidManifest.xml' 'com.nexavpn.client.IMPORT_CONFIG'
Assert-Contains 'client/ios/app/main.entitlements' '$(GROUP_ID_IOS)'
Assert-Contains 'client/ios/networkextension/NexaVPNNetworkExtension.entitlements' '$(GROUP_ID_IOS)'
Assert-Contains 'client/macos/app/app.entitlements' '$(GROUP_ID_MACOS)'
Assert-Contains 'client/macos/networkextension/NexaVPNNetworkExtension.entitlements' '$(GROUP_ID_MACOS)'
Assert-Contains 'client/macos/app/daemon.entitlements' '$(GROUP_ID_MACOS)'
Assert-NotContains 'client/macos/app/daemon.entitlements' '$(DEVELOPMENT_TEAM).$(GROUP_ID_MACOS)'
Assert-Contains 'client/ios/networkextension/CMakeLists.txt' '${BUILD_IOS_APP_IDENTIFIER}.network-extension'
Assert-Contains 'client/cmake/macos.cmake' 'MACOSX_BUNDLE_GUI_IDENTIFIER "${BUILD_OSX_APP_IDENTIFIER}"'
Assert-Contains 'client/cmake/macos_ne.cmake' 'MACOSX_BUNDLE_GUI_IDENTIFIER "${BUILD_OSX_APP_IDENTIFIER}"'
Assert-Contains 'client/macos/networkextension/CMakeLists.txt' '${BUILD_OSX_APP_IDENTIFIER}.network-extension'
Assert-Contains 'client/amneziaApplication.cpp' '#if NEXA_ENABLE_UPSTREAM_UPDATES'
Assert-Contains 'client/core/controllers/updateController.cpp' '#if !NEXA_ENABLE_UPSTREAM_UPDATES'
Assert-Contains 'client/ui/qml/Pages2/PageSettingsAbout.qml' 'SettingsController.getSourceUrl()'
Assert-Contains 'client/ui/qml/Pages2/PageSettingsAbout.qml' 'SettingsController.getUpstreamUrl()'
Assert-Contains 'client/core/utils/containers/containerUtils.cpp' 'AmneziaWG'
Assert-Contains 'client/android/AndroidManifest.xml' 'android:scheme="vpn"'
Assert-Contains 'README.md' 'e38a233904d9db148f620fdd30fd56a770b457e8'
Assert-Contains 'NOTICE' 'Amnezia VPN'
Assert-Contains 'deploy/data/linux/post_uninstall.sh' 'ORG_NAME=NexaVPN'
Assert-Contains 'deploy/data/windows/post_uninstall.cmd' '%AppData%\NexaVPN'
Assert-Contains 'cmake/CPack.cmake' 'CPACK_RESOURCE_FILE_LICENSE     ${CMAKE_SOURCE_DIR}/LICENSE'
Assert-NotContains 'cmake/CPack.cmake' 'deploy/data/LICENSE.txt'
Assert-Contains 'deploy/deploy_s3.sh' 'EXPECTED_SHA256SUMS'
Assert-NotContains 'deploy/deploy_s3.sh' '--ignore-missing'
Assert-NotContains 'client/ui/controllers/marketplaceUpdateController.cpp' 'id1600529900'
Assert-Contains 'client/platforms/ios/Log.swift' 'object(forInfoDictionaryKey: key)'
Assert-Contains 'client/macos/app/Info.plist.in' '<key>com.wireguard.macos.app_group_id</key>'
Assert-NotContains 'client/macos/networkextension/Info.plist.in' '${BUILD_VPN_DEVELOPMENT_TEAM}.${BUILD_OSX_GROUP_IDENTIFIER}'
Assert-Contains 'CMakeLists.txt' 'set(NEXA_PF_RULE_IDENTITY "group { nexavpn }")'
Assert-Contains 'client/platforms/macos/daemon/macosfirewall.cpp' '#define BRAND_IDENTIFIER "nexa"'
Assert-Contains 'client/platforms/macos/daemon/wireguardutilsmacos.cpp' '/var/run/nexavpn-amneziawg'
Assert-Contains 'deploy/data/macos/NexaVPN.plist' '<string>nexavpn</string>'
Assert-Contains 'deploy/data/macos/NexaVPN.plist' '<string>15959</string>'
Assert-NotContains 'deploy/data/macos/NexaVPN.plist' '<string>5959</string>'

$identityFiles = @(
    'CMakeLists.txt',
    'version.h.in',
    'client/android/build.gradle',
    'client/android/build.gradle.kts',
    'client/android/AndroidManifest.xml',
    'client/ios/app/Info.plist.in',
    'client/ios/app/main.entitlements',
    'client/ios/networkextension/CMakeLists.txt',
    'client/ios/networkextension/NexaVPNNetworkExtension.entitlements',
    'client/macos/app/Info.plist.in',
    'client/macos/app/app.entitlements',
    'client/macos/networkextension/CMakeLists.txt',
    'client/macos/networkextension/NexaVPNNetworkExtension.entitlements',
    'cmake/CPack.cmake',
    'deploy/data/linux/NexaVPN.desktop',
    'deploy/data/linux/NexaVPN.service',
    'deploy/data/macos/NexaVPN.plist'
)

$legacyIdentityTokens = @(
    'org.amnezia.AmneziaVPN',
    'group.org.amnezia.AmneziaVPN',
    'org.amnezia.amneziaVPN.NE',
    'org.amnezia.vpn'
)

foreach ($relativePath in $identityFiles) {
    foreach ($token in $legacyIdentityTokens) {
        Assert-NotContains $relativePath $token
    }
}

function Assert-FileMagic {
    param(
        [Parameter(Mandatory)][string]$RelativePath,
        [Parameter(Mandatory)][byte[]]$Expected
    )
    $bytes = [IO.File]::ReadAllBytes((Resolve-RepoPath $RelativePath))
    Assert-True ($bytes.Length -ge $Expected.Length) "$RelativePath is unexpectedly short"
    for ($index = 0; $index -lt $Expected.Length; $index++) {
        Assert-True ($bytes[$index] -eq $Expected[$index]) "$RelativePath has invalid file signature"
    }
}

Assert-FileMagic 'branding/nexa-master-icon.png' ([byte[]](0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a))
Assert-FileMagic 'client/images/app.ico' ([byte[]](0x00, 0x00, 0x01, 0x00))
Assert-FileMagic 'client/images/app.icns' ([byte[]](0x69, 0x63, 0x6e, 0x73))

$xmlFiles = @(
    'client/android/AndroidManifest.xml',
    'client/android/res/drawable/ic_nexa_round.xml',
    'client/android/res/drawable/ic_launcher_monochrome.xml',
    'client/images/images.qrc'
)
$xmlFiles += Get-ChildItem -LiteralPath (Resolve-RepoPath 'client/translations') -Filter '*.ts' | ForEach-Object {
    $_.FullName.Substring($repoRoot.Length + 1)
}

foreach ($relativePath in $xmlFiles) {
    try {
        $null = [xml](Get-RepoText $relativePath)
        $script:checkCount++
    }
    catch {
        throw "Brand verification failed: invalid XML in ${relativePath}: $($_.Exception.Message)"
    }
}

$catalogFiles = Get-ChildItem -LiteralPath (Resolve-RepoPath 'client') -Recurse -Filter 'Contents.json'
foreach ($catalog in $catalogFiles) {
    try {
        $catalogData = [IO.File]::ReadAllText($catalog.FullName) | ConvertFrom-Json
        $script:checkCount++
        if ($catalogData.PSObject.Properties.Name -contains 'images') {
            foreach ($entry in @($catalogData.images)) {
                $hasFilename = ($null -ne $entry) -and
                    ($entry.PSObject.Properties.Name -contains 'filename') -and
                    (-not [string]::IsNullOrWhiteSpace($entry.filename))
                if ($hasFilename) {
                    $assetPath = Join-Path $catalog.DirectoryName $entry.filename
                    Assert-True (Test-Path -LiteralPath $assetPath -PathType Leaf) "Apple asset catalog is missing: $assetPath"
                }
            }
        }
    }
    catch {
        $relativePath = $catalog.FullName.Substring($repoRoot.Length + 1)
        throw "Brand verification failed: invalid JSON in ${relativePath}: $($_.Exception.Message)"
    }
}

[xml]$resourceXml = Get-RepoText 'client/images/images.qrc'
$resourceRoot = Split-Path (Resolve-RepoPath 'client/images/images.qrc') -Parent
foreach ($node in $resourceXml.SelectNodes('//file')) {
    $assetPath = Join-Path $resourceRoot $node.InnerText
    Assert-True (Test-Path -LiteralPath $assetPath -PathType Leaf) "Qt resource is missing: $($node.InnerText)"
}

Write-Host "Nexa VPN branding verification passed ($script:checkCount checks)."
