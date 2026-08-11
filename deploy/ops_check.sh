#!/usr/bin/env bash
set -euo pipefail

project_dir="${PROJECT_DIR:-/opt/fieldnote/python-agent-demo}"
disk_limit="${DISK_USAGE_ALERT_PERCENT:-80}"
pending_limit="${INDEX_PENDING_ALERT_COUNT:-50}"
cd "$project_dir"

curl -fsS http://127.0.0.1:8000/ready >/dev/null
unhealthy="$(sudo docker compose --env-file .env.production ps --format json | \
  python3 -c 'import json,sys; rows=[json.loads(x) for x in sys.stdin if x.strip()]; print(sum(1 for x in rows if x.get("State") != "running" and x.get("Service") != "migrate"))')"
job_counts="$(sudo docker compose --env-file .env.production exec -T mysql sh -c \
  'mysql -N -u root -p"$MYSQL_ROOT_PASSWORD" "$MYSQL_DATABASE" -e "SELECT SUM(status=\"failed\"),SUM(status IN (\"pending\",\"processing\")) FROM knowledge_index_jobs"')"
failed="$(awk '{print $1+0}' <<< "$job_counts")"
pending="$(awk '{print $2+0}' <<< "$job_counts")"
disk="$(df -P / | awk 'NR==2 {gsub(/%/,"",$5); print $5}')"

echo "ops_check ready=1 unhealthy_containers=$unhealthy failed_index_jobs=$failed pending_index_jobs=$pending disk_percent=$disk"
(( unhealthy == 0 )) || exit 2
(( failed == 0 )) || exit 3
(( pending <= pending_limit )) || exit 4
(( disk < disk_limit )) || exit 5
