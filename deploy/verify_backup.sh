#!/usr/bin/env bash
set -euo pipefail

target="${1:?usage: verify_backup.sh BACKUP_DIRECTORY}"
test -s "$target/mysql.sql.gz"
test -s "$target/qdrant.snapshot"
(cd "$target" && sha256sum -c SHA256SUMS)
gzip -t "$target/mysql.sql.gz"
gzip -dc "$target/mysql.sql.gz" | grep -q -- '-- MySQL dump'
echo "backup_verified path=$target mysql_gzip=ok checksums=ok qdrant_snapshot=present"
