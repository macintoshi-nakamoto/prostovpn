# Nexa VPN

<p align="center">
  <img src="branding/nexa-master-icon.png" alt="Nexa VPN icon" width="160">
</p>

Nexa VPN is a GPL-3.0 cross-platform VPN client focused on self-hosted servers. It is a clearly attributed derivative of [Amnezia VPN](https://github.com/amnezia-vpn/amnezia-client), pinned to upstream commit [`e38a233904d9db148f620fdd30fd56a770b457e8`](https://github.com/amnezia-vpn/amnezia-client/commit/e38a233904d9db148f620fdd30fd56a770b457e8).

This repository is currently a source-stage fork, not a published VPN service and not a set of audited release binaries. The product identity, application IDs, installer names and artwork have been changed to Nexa VPN. Upstream commercial-service entry points and automatic updates are disabled by default until Nexa has its own backend and signed update channel.

[Русская версия](README_RU.md)

## What is included

- One Qt/QML interface for Windows, Linux, macOS, Android and iOS.
- Automatic deployment of a personal VPN server over SSH and Docker.
- AmneziaWG/AWG2, WireGuard, OpenVPN, Xray VLESS + REALITY and SSXray transports.
- IKEv2/IPsec client support on Windows.
- Split tunnelling, kill switch, DNS controls, profile import/export and QR import.
- Original Nexa VPN artwork and platform-specific application icons.

`AmneziaWG` is retained as the protocol's technical compatibility name. Existing `.vpn` profiles, `vpn://` links, serialized keys and deployed `amnezia-*` containers remain compatible. Legacy Cloak and direct Shadowsocks entries found in upstream documentation are not presented as supported transports in this fork.

## Platform status

| Platform | Source target | Release requirement |
| --- | --- | --- |
| Windows 10/11 | Desktop client + privileged service | Visual Studio/Qt toolchain and Authenticode certificate for public releases |
| Linux | Desktop client + privileged service | Qt/Conan build environment; package per distribution |
| Android 9+ | Native `VpnService` backends | JDK 17, Android SDK/NDK, Qt for Android and a permanent signing key |
| macOS | Classic desktop or Network Extension target | macOS/Xcode, Developer ID, provisioning and notarization |
| iPhone/iPad | Network Extension target | Apple Developer team, app/extension profiles and Network Extension entitlement |

The exact upstream commit has passed upstream CI for Windows, Linux, classic macOS, Android and iOS compilation. Nexa's modified tree still needs clean builds, signing and device-level VPN tests on every target before distribution. See [Building](docs/BUILDING.md).

## Get the source

```bash
git clone --recurse-submodules <your-nexa-repository-url>
cd nexa-vpn
git submodule update --init --recursive
```

The upstream remote in this working tree is intentionally named `upstream`. Before distributing binaries, set your own public source and homepage URLs:

```bash
cmake -S . -B deploy/build \
  -DNEXA_SOURCE_URL=https://github.com/your-org/nexa-vpn \
  -DNEXA_HOMEPAGE_URL=https://your-project.example
```

Platform-specific dependencies and commands are documented in [docs/BUILDING.md](docs/BUILDING.md). Architecture and compatibility boundaries are documented in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and [docs/UPSTREAM.md](docs/UPSTREAM.md).

## Security status

Do not treat the current source snapshot as an audited production VPN. Automatic upstream updates are off, but inherited high-priority work remains around SSH host verification, encrypted backup export, secret storage, privileged IPC and the server-image supply chain. Read [docs/SECURITY.md](docs/SECURITY.md) before running it against sensitive infrastructure.

## Licensing and attribution

Nexa VPN is distributed under GPL-3.0 because it derives from Amnezia VPN. Keep [LICENSE](LICENSE), [NOTICE](NOTICE), source availability and all applicable third-party notices with every distribution. The names `AmneziaWG`, third-party library names and legacy configuration identifiers do not imply endorsement by the Amnezia project.

Before a public store release, complete [the release checklist](docs/RELEASE_CHECKLIST.md), including a trademark/name clearance: another Android application already uses the public name “Nexa VPN”.
