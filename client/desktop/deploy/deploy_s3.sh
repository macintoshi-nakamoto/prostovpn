#!/usr/bin/env bash
set -euo pipefail

VERSION="${1:-}"

if [[ -z "$VERSION" ]]; then
    echo '::error::Usage: deploy_s3.sh <release-version>'
    exit 1
fi

if [[ ! "$VERSION" =~ ^[0-9]+(\.[0-9]+){2,3}(-[0-9A-Za-z.-]+)?$ ]]; then
    echo "::error::Invalid release version: ${VERSION}"
    exit 1
fi

: "${NEXA_GITHUB_REPOSITORY:?Set NEXA_GITHUB_REPOSITORY to the Nexa owner/repository}"
: "${NEXA_RCLONE_DESTINATION:?Set NEXA_RCLONE_DESTINATION to a Nexa-owned rclone destination}"

release_api="https://api.github.com/repos/${NEXA_GITHUB_REPOSITORY}/releases/tags/${VERSION}"
release_base="https://github.com/${NEXA_GITHUB_REPOSITORY}/releases/download/${VERSION}"
stage_dir="$(mktemp -d)"
trap 'rm -rf -- "$stage_dir"' EXIT

curl --fail --silent --show-error --location "$release_api" --output "$stage_dir/release.json"

if [[ "$(jq -r '.id // empty' "$stage_dir/release.json")" == "" ]]; then
    echo "::error::Release ${VERSION} does not exist in ${NEXA_GITHUB_REPOSITORY}."
    exit 1
fi

printf '%s\n' "$VERSION" > "$stage_dir/VERSION"
jq -r '.published_at' "$stage_dir/release.json" > "$stage_dir/RELEASE_DATE"
jq -r '.body // ""' "$stage_dir/release.json" | tr -d '\r' > "$stage_dir/CHANGELOG"
rm -- "$stage_dir/release.json"

artifact_assets=(
    "NexaVPN_${VERSION}_android9+_arm64-v8a.apk"
    "NexaVPN_${VERSION}_android9+_armeabi-v7a.apk"
    "NexaVPN_${VERSION}_android9+_x86.apk"
    "NexaVPN_${VERSION}_android9+_x86_64.apk"
    "NexaVPN_${VERSION}_linux_x64.run"
    "NexaVPN_${VERSION}_macos_x64.pkg"
    "NexaVPN_${VERSION}_windows_x64.exe"
)
assets=("${artifact_assets[@]}" "SHA256SUMS")

for asset in "${assets[@]}"; do
    echo "Downloading ${asset}..."
    curl --fail --silent --show-error --location \
        "${release_base}/${asset}" \
        --output "${stage_dir}/${asset}"
done

(
    cd "$stage_dir"
    : > EXPECTED_SHA256SUMS
    for artifact in "${artifact_assets[@]}"; do
        if ! manifest_line="$(awk -v expected="$artifact" '
            {
                hash = $1
                name = $2
                sub(/^\*/, "", name)
                if (length(hash) == 64 && hash ~ /^[0-9a-fA-F]+$/ && name == expected) {
                    count++
                    matched = tolower(hash) "  " name
                }
            }
            END {
                if (count != 1) {
                    exit 1
                }
                print matched
            }
        ' SHA256SUMS)"; then
            echo "::error::SHA256SUMS must contain exactly one valid entry for ${artifact}."
            exit 1
        fi
        printf '%s\n' "$manifest_line" >> EXPECTED_SHA256SUMS
    done
    sha256sum --check --strict EXPECTED_SHA256SUMS
    rm -- EXPECTED_SHA256SUMS
)

# `copy` cannot delete unrelated remote files, unlike the inherited `sync` command.
rclone copy "$stage_dir/" "$NEXA_RCLONE_DESTINATION"
echo "Uploaded verified Nexa VPN ${VERSION} artifacts to ${NEXA_RCLONE_DESTINATION}."
