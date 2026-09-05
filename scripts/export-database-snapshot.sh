#!/bin/sh
set -eu

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$repo_root"

snapshot_dir="$repo_root/database"
snapshot_file="$snapshot_dir/bootstrap.dump"
manifest_file="$snapshot_dir/bootstrap.manifest"
stage_snapshot=false

if [ "${1:-}" = "--stage" ]; then
  stage_snapshot=true
elif [ -n "${1:-}" ]; then
  echo "Usage: $0 [--stage]" >&2
  exit 2
fi

if ! command -v docker >/dev/null 2>&1 || ! docker compose version >/dev/null 2>&1; then
  echo "Docker Compose v2 diperlukan untuk membuat snapshot database." >&2
  exit 1
fi

if ! docker compose ps --status running postgres 2>/dev/null | grep -q postgres; then
  echo "Service postgres tidak aktif. Jalankan 'docker compose up -d postgres' terlebih dahulu." >&2
  exit 1
fi

mkdir -p "$snapshot_dir"
umask 077
work_dump=$(mktemp "$snapshot_dir/.snapshot-work.XXXXXX")
next_dump=$(mktemp "$snapshot_dir/.snapshot-next.XXXXXX")
next_manifest=$(mktemp "$snapshot_dir/.snapshot-manifest.XXXXXX")
work_database="fuel_snapshot_${$}_$(date -u +%H%M%S)"

cleanup() {
  rm -f "$work_dump" "$next_dump" "$next_manifest"
  docker compose exec -T postgres sh -lc 'dropdb --if-exists -U "$POSTGRES_USER" "$1"' sh "$work_database" >/dev/null 2>&1 || true
}
trap cleanup EXIT HUP INT TERM

case "$work_database" in
  fuel_snapshot_[0-9]*) ;;
  *) echo "Nama database kerja tidak aman." >&2; exit 1 ;;
esac

echo "Membuat snapshot konsisten dari database aktif..."
docker compose exec -T postgres sh -lc 'pg_dump --format=custom --no-owner --no-privileges -U "$POSTGRES_USER" -d "$POSTGRES_DB"' > "$work_dump"

docker compose exec -T postgres sh -lc 'createdb -U "$POSTGRES_USER" "$1"' sh "$work_database"
docker compose exec -T postgres sh -lc 'pg_restore --exit-on-error --no-owner --no-privileges -U "$POSTGRES_USER" -d "$1"' sh "$work_database" < "$work_dump"

echo "Membersihkan credential dan data penerima dari salinan kerja..."
docker compose exec -T postgres sh -lc 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$1"' sh "$work_database" <<'SQL'
UPDATE tiktok_settings
SET api_key_encrypted = NULL,
    enabled = FALSE,
    provider_health_status = 'NOT_CONFIGURED',
    last_health_checked_at = NULL,
    last_successful_request_at = NULL,
    last_provider_error = NULL;

UPDATE notification_channels
SET enabled = FALSE
WHERE channel_type = 'EMAIL';

TRUNCATE TABLE
  notification_deliveries,
  notification_jobs,
  notification_rule_recipients,
  notification_rules,
  notification_recipient_group_members,
  notification_recipient_groups,
  notification_recipients,
  notification_oauth_states,
  email_accounts,
  email_oauth_provider_configs
RESTART IDENTITY CASCADE;

UPDATE alert_history
SET recipient = 'configure-after-install',
    provider_message_id = NULL,
    error_message = NULL,
    message_payload = '{}'::jsonb;
SQL

docker compose exec -T postgres sh -lc 'pg_dump --format=custom --compress=9 --no-owner --no-privileges -U "$POSTGRES_USER" -d "$1"' sh "$work_database" > "$next_dump"

checksum_file() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | awk '{print $1}'
  else
    openssl dgst -sha256 "$1" | awk '{print $NF}'
  fi
}

query_value() {
  docker compose exec -T postgres sh -lc 'psql -U "$POSTGRES_USER" -d "$1" -Atc "$2"' sh "$work_database" "$1"
}

generated_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
schema_revision=$(query_value "SELECT version_num FROM alembic_version LIMIT 1;")
news_sources=$(query_value "SELECT count(*) FROM news_source;")
articles=$(query_value "SELECT count(*) FROM article;")
tiktok_posts=$(query_value "SELECT count(*) FROM tiktok_post;")
signals=$(query_value "SELECT count(*) FROM signal;")
incidents=$(query_value "SELECT count(*) FROM incident;")
master_tbbm=$(query_value "SELECT count(*) FROM master_tbbm;")
tbbm_candidates=$(query_value "SELECT count(*) FROM tbbm_discovery_result;")
sha256=$(checksum_file "$next_dump")

{
  printf 'format=PostgreSQL custom archive\n'
  printf 'generated_at=%s\n' "$generated_at"
  printf 'schema_revision=%s\n' "$schema_revision"
  printf 'sha256=%s\n' "$sha256"
  printf 'news_sources=%s\n' "$news_sources"
  printf 'articles=%s\n' "$articles"
  printf 'tiktok_posts=%s\n' "$tiktok_posts"
  printf 'signals=%s\n' "$signals"
  printf 'incidents=%s\n' "$incidents"
  printf 'master_tbbm=%s\n' "$master_tbbm"
  printf 'tbbm_candidates=%s\n' "$tbbm_candidates"
  printf 'sanitized=tiktok_api_key,email_oauth,email_accounts,email_recipients,email_rules,email_jobs,alert_recipient\n'
} > "$next_manifest"

chmod 0644 "$next_dump" "$next_manifest"
mv "$next_dump" "$snapshot_file"
mv "$next_manifest" "$manifest_file"

if [ "$stage_snapshot" = true ]; then
  git add -- database/bootstrap.dump database/bootstrap.manifest
fi

echo "Snapshot siap: signals=$signals, incidents=$incidents, master_tbbm=$master_tbbm, sha256=$sha256"
