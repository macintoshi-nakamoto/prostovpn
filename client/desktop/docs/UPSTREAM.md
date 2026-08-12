# Upstream provenance and compatibility

## Baseline

- Project: `amnezia-vpn/amnezia-client`
- Branch at fork time: `dev`
- Commit: `e38a233904d9db148f620fdd30fd56a770b457e8`
- Commit date: 2026-07-31
- Local remote name: `upstream`
- Nexa working branch: `nexa/rebrand`

Submodules are retained at the revisions recorded by that commit. Update them only as part of an intentional dependency review.

## What Nexa changes

- UI name, wordmark, original icon artwork and store metadata;
- executable, service and installer naming;
- Android application ID, action/provider/process identifiers;
- Apple app, extension and app-group identifiers;
- Windows installer upgrade identity;
- product URLs as configurable CMake values;
- safe default that disables inherited update/store checks;
- build, security, release and attribution documentation.

## What deliberately keeps an Amnezia name

The following are compatibility or attribution, not unfinished branding:

- `AmneziaWG` and `amneziawg-*` library names;
- the `amnezia` C++ namespace;
- translation filenames and internal source paths where renaming adds no user value;
- `/opt/amnezia`, `amnezia-*` containers and the existing Docker network;
- old profile keys, schemes and serialized enum values;
- original copyright notices and upstream links in attribution.

Changing these values without a migration can prevent old profiles from loading, fail to discover an existing VPS installation or break binary/library integration.

## Updating from upstream

1. Fetch `upstream` and review the upstream range before merging.
2. Merge or rebase on a dedicated integration branch.
3. Resolve product-boundary conflicts without renaming protocol compatibility values.
4. Re-run `scripts/generate-brand-assets.ps1` only if source artwork requirements changed.
5. Run `scripts/verify-branding.ps1` and all platform builds/tests.
6. Re-audit endpoints, updater behavior, signing configuration, dependencies and notices.
7. Record the new upstream commit in this file, both READMEs and `NOTICE`.

Never copy upstream release secrets, store identities, provisioning profiles or signing assets into Nexa.
