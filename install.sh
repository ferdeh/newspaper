#!/bin/sh
set -eu

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$repo_root"

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker belum tersedia. Install Docker Desktop/Docker Engine terlebih dahulu." >&2
  exit 1
fi
if ! docker compose version >/dev/null 2>&1; then
  echo "Docker Compose v2 belum tersedia." >&2
  exit 1
fi

./scripts/verify-database-snapshot.sh

random_hex() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex "$1"
  else
    od -An -N "$1" -tx1 /dev/urandom | tr -d ' \n'
  fi
}

set_env_value() {
  key=$1
  value=$2
  temporary=$(mktemp "${TMPDIR:-/tmp}/fuel-env.XXXXXX")
  awk -v key="$key" -v value="$value" '
    BEGIN { found = 0 }
    index($0, key "=") == 1 { print key "=" value; found = 1; next }
    { print }
    END { if (!found) print key "=" value }
  ' .env > "$temporary"
  mv "$temporary" .env
}

if [ ! -f .env ]; then
  echo "Membuat .env dengan secret lokal unik..."
  cp .env.example .env
  postgres_password=$(random_hex 24)
  set_env_value POSTGRES_PASSWORD "$postgres_password"
  set_env_value DATABASE_URL "postgresql+psycopg://fuel_app:${postgres_password}@postgres:5432/fuel_intelligence"
  set_env_value INTERNAL_API_TOKEN "$(random_hex 32)"
  set_env_value APP_ENCRYPTION_KEY "$(random_hex 32)"
  set_env_value EMAIL_TOKEN_ENCRYPTION_KEY "$(random_hex 32)"
  chmod 0600 .env
else
  echo "Menggunakan .env yang sudah ada; tidak ada secret yang ditimpa."
fi

docker compose config --quiet

if command -v git >/dev/null 2>&1 && git rev-parse --git-dir >/dev/null 2>&1; then
  git config core.hooksPath .githooks
  echo "Git hook snapshot database diaktifkan."
fi

echo "Membangun dan menjalankan aplikasi..."
docker compose up -d --build --wait --wait-timeout 300

echo "Instalasi selesai."
echo "Dashboard     : http://localhost"
echo "Documentation : http://localhost/documentation"
echo "API readiness : http://localhost/ready"
echo "Data TBBM, signal, incident, dan histori discovery berasal dari snapshot Git saat volume PostgreSQL dibuat pertama kali."
