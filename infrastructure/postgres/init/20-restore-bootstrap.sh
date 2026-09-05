#!/bin/sh
set -eu

snapshot=/opt/fuel-intelligence/bootstrap.dump
manifest=/opt/fuel-intelligence/bootstrap.manifest

if [ ! -s "$snapshot" ] || [ ! -s "$manifest" ]; then
  echo "Bootstrap database snapshot tidak tersedia." >&2
  exit 1
fi

expected=$(awk -F= '$1 == "sha256" { print $2 }' "$manifest")
actual=$(sha256sum "$snapshot" | awk '{print $1}')
if [ -z "$expected" ] || [ "$expected" != "$actual" ]; then
  echo "Checksum bootstrap database tidak cocok." >&2
  exit 1
fi

echo "Memulihkan snapshot Fuel Intelligence ke database baru $POSTGRES_DB..."
# The PostGIS base image creates its extension schemas first. This hook only runs
# for a brand-new PGDATA, so replacing those empty bootstrap objects is safe.
pg_restore --clean --if-exists --exit-on-error --no-owner --no-privileges --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" "$snapshot"
echo "Snapshot Fuel Intelligence berhasil dipulihkan. Credential provider harus dikonfigurasi ulang melalui UI."
