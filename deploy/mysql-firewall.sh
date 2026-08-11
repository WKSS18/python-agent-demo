#!/usr/bin/env bash
set -euo pipefail

allowed_ip="${1:?usage: mysql-firewall.sh ALLOWED_PUBLIC_IP}"
comment="fieldnote-mysql-3306"

# Docker 发布端口可能绕过 UFW，因此在 DOCKER-USER 链建立显式白名单。
while sudo iptables -C DOCKER-USER -p tcp --dport 3306 -m comment --comment "$comment" -j DROP 2>/dev/null; do
  sudo iptables -D DOCKER-USER -p tcp --dport 3306 -m comment --comment "$comment" -j DROP
done
while sudo iptables -C DOCKER-USER -p tcp -s "$allowed_ip/32" --dport 3306 -m comment --comment "$comment" -j ACCEPT 2>/dev/null; do
  sudo iptables -D DOCKER-USER -p tcp -s "$allowed_ip/32" --dport 3306 -m comment --comment "$comment" -j ACCEPT
done

sudo iptables -I DOCKER-USER 1 -p tcp -s "$allowed_ip/32" --dport 3306 -m comment --comment "$comment" -j ACCEPT
sudo iptables -I DOCKER-USER 2 -p tcp --dport 3306 -m comment --comment "$comment" -j DROP
echo "mysql_firewall configured allowed_ip=$allowed_ip port=3306"
