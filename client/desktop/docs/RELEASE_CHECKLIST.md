# Public release checklist

The source fork is not a releasable VPN product until every applicable item is complete.

## Identity and legal

- [ ] Clear the product name and trademark in every target country. Google Play already lists an unrelated app named “Nexa VPN”, package `com.nexa.net`.
- [ ] Publish a Nexa-owned source repository and set `NEXA_SOURCE_URL`/`NEXA_HOMEPAGE_URL`.
- [ ] Preserve GPL-3.0 source availability, `LICENSE`, `NOTICE`, commit history and per-file notices.
- [ ] Produce a platform-specific SBOM and complete third-party notice bundle.
- [ ] Review unknown/prebuilt binary provenance and Wintun redistribution terms.
- [ ] Obtain legal review for GPL-3.0 distribution through the Apple App Store.
- [ ] Publish privacy, support, vulnerability disclosure and data-retention policies.

## Security

- [ ] Close every release-blocking item in `docs/SECURITY.md`.
- [ ] Run an independent source and privilege-boundary audit.
- [ ] Pin dependencies, base images and downloads by immutable version/digest and verify checksums.
- [ ] Sign server images and publish their SBOM/provenance attestations.
- [ ] Implement a signed update manifest before enabling any updater.
- [ ] Perform DNS/IPv6/WebRTC leak, kill-switch and hostile-network testing.

## Build and signing

- [ ] Reproduce clean Windows, Linux, Android, macOS and iOS builds from the public source tag.
- [ ] Replace `docs/upstream-deploy-reference.yml` with reviewed Nexa-owned CI jobs; do not copy it back unchanged.
- [ ] Use Nexa-owned Windows Authenticode, Android upload and Apple signing identities.
- [ ] Verify Windows signatures, APK/AAB signatures, Apple codesigning, notarization and provisioning entitlements.
- [ ] Build an actual iOS archive/IPA; the inherited workflow only compiles the target.
- [ ] Repair and validate the macOS Network Extension build.
- [ ] Store release secrets outside the repository and restrict CI access.

## Functional validation

- [ ] Test install, upgrade, coexistence with Amnezia VPN and uninstall on clean systems.
- [ ] Test import of legacy `.vpn`/`vpn://`, WireGuard, AmneziaWG, OpenVPN and Xray configurations.
- [ ] Test connection, reconnection, suspend/resume and network handover on physical devices.
- [ ] Test split tunnel, kill switch, DNS, IPv4/IPv6 routes and failure recovery.
- [ ] Test self-hosted install/upgrade/removal against each supported server OS.
- [ ] Confirm that no UI path sends users to an Amnezia store, subscription or update endpoint.

## Store delivery

- [ ] Create unique store listings, screenshots and accessibility text using only Nexa assets.
- [ ] Confirm the application IDs and app-group/extension IDs belong to the publishing accounts.
- [ ] Complete store privacy/data-safety declarations based on measured behavior.
- [ ] Stage a signed beta, monitor crashes/connectivity and define rollback before production rollout.
