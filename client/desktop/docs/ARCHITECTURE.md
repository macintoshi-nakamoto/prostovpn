# Nexa VPN architecture

Nexa VPN keeps the upstream Qt/QML architecture and changes product identity at platform boundaries. This minimizes protocol regressions and preserves existing profile/server compatibility.

## Main data path

```text
Qt/QML UI
  -> controllers and repositories
  -> VpnConnection / protocol adapter
  -> platform tunnel implementation
  -> encrypted transport to the selected server
```

The desktop client delegates privileged networking operations to `NexaVPN-service` through Qt Remote Objects. Android uses platform `VpnService` implementations. iOS and the Network Extension macOS target use `NEPacketTunnelProvider`.

## Platform layers

| Layer | Windows/Linux/macOS classic | Android | iOS/macOS Network Extension |
| --- | --- | --- | --- |
| UI and configuration | Qt/QML + C++ | Qt/QML + C++ | Qt/QML + C++ |
| Privileged tunnel boundary | Separate local service | Android `VpnService` | Apple packet-tunnel extension |
| Protocol engines | OpenVPN, AWG/WireGuard, Xray and platform helpers | Kotlin/JNI protocol services | AWG Apple, OpenVPNAdapter, Xray/HEV |
| Routes/DNS/firewall | Platform daemon code | Android VPN builder | Network Extension settings |

## Self-hosted deployment

The installer controller connects to a user-provided VPS over SSH, checks the host, uploads/executes installation scripts and starts protocol-specific Docker containers. Server scripts live in `client/server_scripts`; container discovery and compatibility mappings live under `client/core/utils/containers`.

Nexa currently keeps `/opt/amnezia`, Docker names such as `amnezia-awg` and the `amnezia-dns-net` network. They are protocol/deployment compatibility identifiers, not visible Nexa branding. Renaming them requires dual discovery, migration and rollback support.

## Protocol matrix

| Protocol/transport | Role in the client | Notes |
| --- | --- | --- |
| AmneziaWG / AWG2 | Obfuscated WireGuard-compatible tunnel | Preserve AWG fields and wire semantics; `AmneziaWG` is the technical name |
| WireGuard | Standard WireGuard tunnel | Standard native configuration import/export |
| OpenVPN | TLS-based VPN tunnel | Current server defaults use modern AEAD/TLS settings |
| Xray VLESS + REALITY | Censorship-resistant proxy transport | Routed through local SOCKS/tun integration |
| SSXray | Shadowsocks implemented through Xray | Distinct from the legacy direct Shadowsocks backend |
| IKEv2/IPsec | Native IPsec tunnel | Client factory is currently Windows-only |

Legacy Cloak and direct Shadowsocks values remain in some schemas for backward compatibility but are not treated as functioning current transports.

## Compatibility boundary

Do not rename without a versioned migration:

- the `amnezia` C++ namespace and names of upstream/third-party libraries;
- `AmneziaWG` protocol labels and AWG parameter keys;
- `.vpn`, `vpn://` and existing JSON keys;
- protocol/container enum values;
- current server paths, networks and container IDs.

Nexa-owned identity includes:

- product/display name `NexaVPN` / `Nexa VPN`;
- Android application ID `com.nexavpn.client`;
- Apple app ID `com.nexavpn.client`, extension ID `com.nexavpn.client.network-extension` and app group `group.com.nexavpn.client`;
- desktop executable, service, settings, IPC, installer and icon names.

## Backend boundary

Self-hosted operation does not require Nexa to operate a VPN gateway. Amnezia subscription/store entry points are hidden and upstream update checks are disabled. If a future Nexa-managed service is added, use separate endpoints, policies, signing keys and store records; do not silently route a rebranded client through Amnezia infrastructure.
