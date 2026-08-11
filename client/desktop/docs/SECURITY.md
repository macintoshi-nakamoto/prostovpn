# Security status

Nexa VPN inherits a large networking and privilege surface from its upstream baseline. The repository has not completed an independent security audit. Do not publish it as a production privacy product or use it for high-risk traffic until the items below are fixed and tested.

## Mitigations already applied in the fork

- Automatic desktop update checks are disabled by default with `NEXA_ENABLE_UPSTREAM_UPDATES=OFF`.
- Mobile marketplace update checks are disabled by the same build flag.
- The upstream commercial VPN card and purchase restoration entry are hidden from the initial connection flow.
- Apple team IDs and provisioning profile names are no longer inherited; release configuration must supply Nexa-owned credentials.
- Package/application IDs and the Windows installer upgrade GUID are distinct, so Nexa is not installed as an Amnezia update.

These safeguards prevent accidental use of upstream store/update identity. They do not resolve the inherited issues below.

## Release-blocking findings

1. **SSH host authentication.** The self-hosted installer connects and authenticates without a complete known-host/fingerprint verification flow. Implement strict known-host checking or an explicit TOFU confirmation that displays and persists the server fingerprint.

2. **Full-access backup export.** The inherited full-access export can include SSH credentials and private keys while using compression/Base64 rather than encryption. Disable that export until it uses a password-derived, versioned AEAD format with authenticated metadata and safe migration.

3. **Settings secret storage.** The inherited settings encryption uses AES-CBC with a fixed IV and no authentication; Linux can fall back to plaintext because keychain encryption is disabled there. Move secrets to platform keystores or a versioned AEAD envelope with per-record nonces and authenticated migration.

4. **Privileged local IPC.** Desktop service sockets use a broad local access mode and pass sensitive networking arguments across the privilege boundary. Restrict peer access, authenticate the client and enforce operation-specific allowlists.

5. **SSH command construction and logs.** Server scripts use string substitution for shell commands and may log substituted values. Add strict validation/shell escaping, secret redaction and a safer channel for secret material.

6. **Server image supply chain.** Some Dockerfiles use old or moving base tags, privileged containers and downloads without a pinned checksum. Rebuild Nexa-owned images from supported pinned digests, minimize Linux capabilities, verify downloads, generate SBOMs and sign images.

7. **Desktop updater trust.** Turning the updater back on would download and execute an installer without a signed manifest and explicit digest verification. Implement both before enabling it; platform package signatures remain required as defense in depth.

8. **Test coverage.** The inherited tree has little first-party integration coverage. Add protocol handshake, import/export, migration, DNS leak, kill-switch, reconnect and privilege-boundary tests before release.

## Secrets and logs

- Never commit keystores, certificates, private keys, provisioning profiles, VPS passwords or production endpoint credentials.
- Treat exported full-access backups and diagnostic logs as sensitive.
- Store CI signing material in protected environment secrets with limited release-job access.
- Rotate any credential that appears in a build log or support bundle.

## Reporting vulnerabilities

No public Nexa security contact has been configured yet. Before public distribution, create a monitored private reporting channel, publish a disclosure policy and define supported release lifetimes. Upstream-specific vulnerabilities should also be coordinated with the upstream Amnezia project when appropriate.
