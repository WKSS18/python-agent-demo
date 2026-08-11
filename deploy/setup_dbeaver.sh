#!/usr/bin/env bash
set -euo pipefail

cd "${PROJECT_DIR:-/opt/fieldnote/python-agent-demo}"
reader_password="$(openssl rand -hex 16)"

sudo docker compose --env-file .env.production exec -T mysql \
  sh -c 'exec mysql -u root -p"$MYSQL_ROOT_PASSWORD" "$MYSQL_DATABASE"' <<SQL
CREATE USER IF NOT EXISTS 'fieldnote_reader'@'%' IDENTIFIED BY '$reader_password';
ALTER USER 'fieldnote_reader'@'%' IDENTIFIED BY '$reader_password';
REVOKE ALL PRIVILEGES, GRANT OPTION FROM 'fieldnote_reader'@'%';
GRANT SELECT ON \`$(sed -n 's/^MYSQL_DATABASE=//p' .env.production | tail -1)\`.* TO 'fieldnote_reader'@'%';
FLUSH PRIVILEGES;
SQL

database="$(sed -n 's/^MYSQL_DATABASE=//p' .env.production | tail -1)"
sudo docker compose --env-file .env.production exec -T mysql \
  mysql -N -u fieldnote_reader "-p$reader_password" "$database" \
  -e 'SHOW GRANTS FOR CURRENT_USER; SELECT COUNT(*) AS note_count FROM notes;'

echo "DB_NAME=$database"
echo "READER_USERNAME=fieldnote_reader"
echo "READER_PASSWORD=$reader_password"
echo "PORT_BINDING=$(sudo docker port python-agent-demo-mysql-1 3306/tcp)"
