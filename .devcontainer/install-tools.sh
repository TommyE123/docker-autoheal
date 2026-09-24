#!/usr/bin/env bash
set -euo pipefail

manifest="$(dirname "${BASH_SOURCE[0]}")/tools.json"
install_dir="${HOME}/.local/bin"
mkdir -p "$install_dir"

get_version() {
  python - "$manifest" "$1" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as manifest_file:
    manifest = json.load(manifest_file)

for tool in manifest["tools"]:
    if tool["repository"] == sys.argv[2]:
        print(tool["version"])
        break
else:
    raise SystemExit(f"Tool is not defined: {sys.argv[2]}")
PY
}

install_release() {
  local repository="$1"
  local version="$2"
  local asset="$3"
  local binary="$4"
  local checksum_asset="$5"
  local release_url="https://github.com/${repository}/releases/download/v${version}"
  local temporary_directory
  temporary_directory="$(mktemp -d)"
  trap 'rm -rf "$temporary_directory"' RETURN

  curl --fail --silent --show-error --location \
    --output "${temporary_directory}/${asset}" \
    "${release_url}/${asset}"
  curl --fail --silent --show-error --location \
    --output "${temporary_directory}/checksums.txt" \
    "${release_url}/${checksum_asset}"

  local expected_checksum
  expected_checksum="$(grep -E "(^|[[:space:]])${asset//./\\.}$" "${temporary_directory}/checksums.txt" | head -n 1 | awk '{print $1}')"
  if [[ ! "$expected_checksum" =~ ^[[:xdigit:]]{64}$ ]]; then
    echo "No valid checksum found for ${repository} ${asset}" >&2
    exit 1
  fi
  printf '%s  %s\n' "$expected_checksum" "${temporary_directory}/${asset}" |
    sha256sum --check --status -

  case "$asset" in
  *.tar.gz)
    tar -xzf "${temporary_directory}/${asset}" -C "$temporary_directory"
    install_source="$(find "$temporary_directory" -maxdepth 2 -type f -name "$binary" -print -quit)"
    ;;
  *)
    install_source="${temporary_directory}/${asset}"
    ;;
  esac

  if [[ -z "${install_source:-}" || ! -f "$install_source" ]]; then
    echo "Binary ${binary} was not found in ${asset}" >&2
    exit 1
  fi
  install -m 0755 "$install_source" "${install_dir}/${binary}"
}

architecture="$(uname -m)"
case "$architecture" in
x86_64) architecture_suffix="amd64" ;;
aarch64 | arm64) architecture_suffix="arm64" ;;
*)
  echo "Unsupported architecture: ${architecture}" >&2
  exit 1
  ;;
esac

actionlint_version="$(get_version rhysd/actionlint)"
install_release rhysd/actionlint "$actionlint_version" \
  "actionlint_${actionlint_version}_linux_${architecture_suffix}.tar.gz" \
  actionlint "actionlint_${actionlint_version}_checksums.txt"

hadolint_version="$(get_version hadolint/hadolint)"
hadolint_architecture="$([[ "$architecture_suffix" == amd64 ]] && echo x86_64 || echo arm64)"
install_release hadolint/hadolint "$hadolint_version" \
  "hadolint-linux-${hadolint_architecture}" hadolint checksums.sha256

osv_version="$(get_version google/osv-scanner)"
install_release google/osv-scanner "$osv_version" \
  "osv-scanner_linux_${architecture_suffix}" osv-scanner \
  osv-scanner_SHA256SUMS

trivy_version="$(get_version aquasecurity/trivy)"
trivy_architecture="$([[ "$architecture_suffix" == amd64 ]] && echo 64bit || echo ARM64)"
install_release aquasecurity/trivy "$trivy_version" \
  "trivy_${trivy_version}_Linux-${trivy_architecture}.tar.gz" trivy \
  "trivy_${trivy_version}_checksums.txt"

trufflehog_version="$(get_version trufflesecurity/trufflehog)"
install_release trufflesecurity/trufflehog "$trufflehog_version" \
  "trufflehog_${trufflehog_version}_linux_${architecture_suffix}.tar.gz" trufflehog \
  "trufflehog_${trufflehog_version}_checksums.txt"

betterleaks_version="$(get_version betterleaks/betterleaks)"
betterleaks_architecture="$([[ "$architecture_suffix" == amd64 ]] && echo x64 || echo arm64)"
install_release betterleaks/betterleaks "$betterleaks_version" \
  "betterleaks_${betterleaks_version}_linux_${betterleaks_architecture}.tar.gz" betterleaks \
  checksums.txt

case ":${PATH}:" in
*":${install_dir}:"*) ;;
*) echo "Add ${install_dir} to PATH to use the installed tools." >&2 ;;
esac
