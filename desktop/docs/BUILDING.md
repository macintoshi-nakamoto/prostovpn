# Building Nexa VPN

The fork is pinned to upstream commit `e38a233904d9db148f620fdd30fd56a770b457e8`. Always initialize its submodules before configuring:

```bash
git submodule update --init --recursive
```

The upstream CI baseline used Qt 6.10.x, CMake 3.25+, Conan 2.28.0 and platform toolchains listed below. Use clean builders and pin the exact dependency versions for releases.

`docs/upstream-deploy-reference.yml` preserves the large inherited workflow as an adaptation reference only. It is deliberately outside `.github/workflows`: its Apple jobs need Nexa provisioning values, its macOS Network Extension job references a missing script, and its Android job expects a custom runner. The only active workflow currently performs static product/resource validation.

## Common configuration

The default application version is `0.1.0.0`. Product settings are defined in `cmake/NexaBranding.cmake` and can be overridden with CMake cache arguments:

```text
-DNEXA_HOMEPAGE_URL=https://your-project.example
-DNEXA_SOURCE_URL=https://github.com/your-org/nexa-vpn
-DNEXA_UPSTREAM_URL=https://github.com/amnezia-vpn/amnezia-client
-DNEXA_ENABLE_UPSTREAM_UPDATES=OFF
```

Keep `NEXA_ENABLE_UPSTREAM_UPDATES=OFF` unless the update code has been changed to a Nexa-owned, signed manifest with package signature/hash verification.

## Windows

Reference environment:

- Windows 10/11 x64;
- Visual Studio 2022 C++ Build Tools;
- Qt 6.10.1 MSVC 2022 x64 with Remote Objects, 5Compat, Image Formats and Shader Tools;
- CMake 3.25+, Python 3 and Conan 2.28.0;
- Qt Installer Framework 4.7 for the `.exe` installer;
- .NET 8 and WiX 4.0.6 for MSI.

From a developer command prompt:

```bat
deploy\build.bat --installer all
```

Public builds also need an Authenticode certificate. The packaging scripts read `SIGNTOOL_SUBJECT_NAME`; import the certificate into the build user's certificate store and verify every executable/MSI with `signtool verify`.

## Linux

The upstream builder uses Ubuntu 22.04, Qt 6.10.1, Ninja and Conan 2.28.0. In addition to normal compiler/build packages it installs `libxkbcommon-x11-0` and `libsecret-1-dev`.

```bash
./deploy/build.sh --generator Ninja --installer all
```

The result is a Qt Installer Framework `.run` package. A public project should additionally produce distro-native signed packages where appropriate.

## Android

Reference environment:

- Linux or macOS host with both desktop Qt and Qt 6.10.3 for Android;
- JDK 17;
- Android SDK/API 36 and build-tools 36.0.0;
- an NDK version matching the selected Qt build;
- four supported ABIs configured by the upstream build scripts;
- Conan 2.28.0.

Unsigned development build:

```bash
./deploy/build.sh -t android --aab
```

Release build:

```bash
export QT_ANDROID_KEYSTORE_PATH=/secure/path/nexa-upload.keystore
export QT_ANDROID_KEYSTORE_ALIAS=nexa-upload
export QT_ANDROID_KEYSTORE_STORE_PASS='set-in-secret-store'
./deploy/build.sh -t android --sign --aab
```

Use one permanent upload key, protect it offline and enable Play App Signing. Do not reuse upstream keys. The application ID is `com.nexavpn.client`.

## iOS and macOS Network Extension

Apple builds require macOS, Xcode, the matching Qt host/iOS packages and a paid Apple Developer team with Packet Tunnel Network Extension capability. Create separate identifiers and profiles for:

- app: `com.nexavpn.client`;
- packet tunnel: `com.nexavpn.client.network-extension`;
- app group: `group.com.nexavpn.client`.

The `group.*` identifier is shared by the macOS app, extension and any entitled helper. Register it with Apple and include the same value in every applicable provisioning profile; do not prepend the Team ID in only one target.

Provide these CMake cache values when configuring a signed build:

```text
BUILD_OSX_APP_IDENTIFIER
BUILD_OSX_GROUP_IDENTIFIER
BUILD_IOS_APP_IDENTIFIER
BUILD_IOS_GROUP_IDENTIFIER
BUILD_VPN_DEVELOPMENT_TEAM
BUILD_IOS_APP_PROFILE
BUILD_IOS_APP_PROFILE_DEBUG
BUILD_IOS_EXTENSION_PROFILE
BUILD_IOS_EXTENSION_PROFILE_DEBUG
BUILD_MACOS_APP_PROFILE
BUILD_MACOS_APP_PROFILE_DEBUG
BUILD_MACOS_EXTENSION_PROFILE
BUILD_MACOS_EXTENSION_PROFILE_DEBUG
```

The upstream iOS entry command is:

```bash
./deploy/build.sh -t ios
```

It compiles the app but does not by itself create/export an App Store `.ipa`. Add an explicit Xcode archive/export pipeline, then validate on physical devices. The inherited macOS Network Extension workflow is not release-ready and must be repaired before use.

## Classic macOS

The upstream classic target builds a universal `arm64;x86_64` application on macOS with Qt 6.10.1. Distribution outside the Mac App Store requires Developer ID Application and Installer identities plus notarization credentials.

```bash
./deploy/build.sh --generator Ninja --installer all
```

## Optional service endpoints

The build still recognizes inherited variables such as `PROD_AGW_PUBLIC_KEY`, `PROD_S3_ENDPOINT`, `FALLBACK_S3_ENDPOINT`, `DEV_AGW_ENDPOINT`, `FREE_V2_ENDPOINT` and `PREM_V1_ENDPOINT`. These values are compiled into the binary and are not secrets. Nexa has no managed-service backend in this repository, so leave those flows disabled unless you implement and document your own service.

## Required validation

Run the repository checks first:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify-branding.ps1
```

For every target, then test install/upgrade/uninstall, connect/disconnect/reconnect, DNS and route leaks, kill switch, split tunnel, suspend/resume, network changes and imports of WireGuard, AmneziaWG, OpenVPN and Xray profiles. Signing verification is part of the test, not an optional packaging step.
