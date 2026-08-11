#!/usr/bin/env bash
set -euo pipefail

destination="${1:-/opt/fieldnote/backups}"
retention_days="${BACKUP_RETENTION_DAYS:-14}"
project_dir="${PROJECT_DIR:-/opt/fieldnote/python-agent-demo}"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
target="$destination/$stamp"
mkdir -p "$target"
cd "$project_dir"

sudo docker compose --env-file .env.production exec -T mysql \
  sh -c 'exec mysqldump --single-transaction --routines --triggers -u root -p"$MYSQL_ROOT_PASSWORD" "$MYSQL_DATABASE"' \
  | gzip -9 > "$target/mysql.sql.gz"

qdrant_key="$(sed -n 's/^QDRANT_API_KEY=//p' .env.production | tail -1)"
collection="$(sed -n 's/^QDRANT_COLLECTION=//p' .env.production | tail -1)"
snapshot_json="$(curl -fsS -X POST -H "api-key: $qdrant_key" \
  "http://127.0.0.1:6333/collections/$collection/snapshots")"
snapshot_name="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["result"]["name"])' <<< "$snapshot_json")"
curl -fsS -H "api-key: $qdrant_key" \
  "http://127.0.0.1:6333/collections/$collection/snapshots/$snapshot_name" \
  -o "$target/qdrant.snapshot"

printf '%s  %s\n' "$(sha256sum "$target/mysql.sql.gz" | cut -d' ' -f1)" mysql.sql.gz > "$target/SHA256SUMS"
printf '%s  %s\n' "$(sha256sum "$target/qdrant.snapshot" | cut -d' ' -f1)" qdrant.snapshot >> "$target/SHA256SUMS"
find "$destination" -mindepth 1 -maxdepth 1 -type d -mtime "+$retention_days" -print -exec rm -rf -- {} +
echo "backup_completed path=$target"
