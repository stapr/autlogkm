#!/usr/bin/env bash
# Installeert de webhook op Ubuntu/Debian. Uitvoeren als root, vanuit de gekloonde repo:
#   sudo bash deploy/install.sh
set -euo pipefail

TARGET=/opt/autlogkm
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

apt-get update
apt-get install -y python3 python3-venv rsync

id teslakm >/dev/null 2>&1 || useradd --system --home "$TARGET" --shell /usr/sbin/nologin teslakm
mkdir -p "$TARGET"
rsync -a --exclude .git --exclude .venv --exclude .env --exclude tokens.json --exclude ritten.csv "$SRC"/ "$TARGET"/

python3 -m venv "$TARGET/.venv"
"$TARGET/.venv/bin/pip" install -r "$TARGET/requirements.txt"

install -m 644 "$TARGET/deploy/tesla-km.service" /etc/systemd/system/tesla-km.service
chown -R teslakm:teslakm "$TARGET"

systemctl daemon-reload
echo
echo "Klaar. Zet nu .env en tokens.json in $TARGET (eigenaar teslakm, chmod 600), daarna:"
echo "  sudo systemctl enable --now tesla-km"
