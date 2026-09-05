#!/bin/sh
set -eu

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$repo_root"

snapshot_file="$repo_root/database/bootstrap.dump"
manifest_file="$repo_root/database/bootstrap.manifest"

if [ ! -s "$snapshot_file" ] || [ ! -s "$manifest_file" ]; then
  echo "Snapshot atau manifest tidak ditemukan. Jalankan 'make snapshot'." >&2
  exit 1
fi

expected=$(awk -F= '$1 == "sha256" { print $2 }' "$manifest_file")
if command -v sha256sum >/dev/null 2>&1; then
  actual=$(sha256sum "$snapshot_file" | awk '{print $1}')
elif command -v shasum >/dev/null 2>&1; then
  actual=$(shasum -a 256 "$snapshot_file" | awk '{print $1}')
else
  actual=$(openssl dgst -sha256 "$snapshot_file" | awk '{print $NF}')
fi

if [ -z "$expected" ] || [ "$expected" != "$actual" ]; then
  echo "Checksum snapshot tidak cocok." >&2
  exit 1
fi

if command -v docker >/dev/null 2>&1 && docker compose ps --status running postgres 2>/dev/null | grep -q postgres; then
  docker compose exec -T postgres pg_restore --list < "$snapshot_file" >/dev/null
fi

echo "Snapshot valid: $actual"
