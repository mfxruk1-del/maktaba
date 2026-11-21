#!/usr/bin/env bash
# Installer (draft). Tested on Ubuntu 22.04 ARM64 up to "the search service starts". Run it as the user who will own the files.
#   ./install.sh                 folders, code, two Python environments, service files (services are NOT started)
#   ./install.sh --no-systemd    the same without touching /etc (for a trial in another folder: LIB_HOME=/some/folder ./install.sh --no-systemd)
set -euo pipefail
SRC="$(cd "$(dirname "$0")" && pwd)"; HOME_DIR="${LIB_HOME:-$HOME}"; USER_NAME="$(id -un)"; SYSTEMD=1
[ "${1:-}" = "--no-systemd" ] && SYSTEMD=0
echo "Installing into $HOME_DIR as $USER_NAME"
mkdir -p "$HOME_DIR/semsearch/pages" "$HOME_DIR/semsearch/findings" "$HOME_DIR/semsearch/data" "$HOME_DIR/library/maktaba" "$HOME_DIR/backups"
cp "$SRC"/search/*.py "$HOME_DIR/semsearch/"
cp "$SRC"/search/pages/ingest.py "$HOME_DIR/semsearch/pages/"
cp "$SRC"/connector/*.py "$HOME_DIR/library/maktaba/"
cp "$SRC"/ops/*.py "$HOME_DIR/backups/"
# build scripts, where their default paths expect them (own-library index; the optional imported books)
mkdir -p "$HOME_DIR/semsearch/mk" "$HOME_DIR/semsearch/kutub" "$HOME_DIR/semsearch/tests" "$HOME_DIR/kutub"
cp "$SRC"/build/maktaba-index/*.py "$HOME_DIR/semsearch/mk/"
cp "$SRC"/build/kutub-index/kt_*.py "$HOME_DIR/semsearch/kutub/"
cp "$SRC"/build/kutub-index/catalog.py "$SRC"/build/kutub-index/overlap_check.py "$HOME_DIR/kutub/"
cp "$SRC"/build/imported-books/*.py "$HOME_DIR/library/"
cp "$SRC"/search/tests/merged_test.py "$HOME_DIR/semsearch/tests/"
[ -f "$HOME_DIR/backups/health.json" ] || cp "$SRC/ops/health.json" "$HOME_DIR/backups/"
[ -f "$HOME_DIR/semsearch/labels.json" ] || cp "$SRC/search/labels.example.json" "$HOME_DIR/semsearch/labels.json"
echo "Python environment for the search service (about 1 GB on disk) ..."
python3 -m venv "$HOME_DIR/semsearch/venv"
"$HOME_DIR/semsearch/venv/bin/pip" install -q --upgrade pip
# the CPU build of torch: the default one pulls several GB of GPU libraries that the server does not use
"$HOME_DIR/semsearch/venv/bin/pip" install -q torch --index-url https://download.pytorch.org/whl/cpu
"$HOME_DIR/semsearch/venv/bin/pip" install -q -r "$SRC/search/requirements.txt"
echo "Python environment for the connector ..."
python3 -m venv "$HOME_DIR/library/maktaba-venv"
"$HOME_DIR/library/maktaba-venv/bin/pip" install -q --upgrade pip
"$HOME_DIR/library/maktaba-venv/bin/pip" install -q -r "$SRC/connector/requirements.txt"
if [ "$SYSTEMD" = 1 ]; then
  for f in "$SRC"/ops/systemd/*; do
    sed -e "s#__HOME__#$HOME_DIR#g" -e "s#__USER__#$USER_NAME#g" "$f" | sudo tee "/etc/systemd/system/$(basename "$f")" >/dev/null
  done
  if ! sudo test -f /etc/maktaba.env; then
    printf 'MAKTABA_DIR=%s\nMAKTABA_TOKEN=%s\nMAKTABA_HOST=127.0.0.1\nMAKTABA_PORT=8790\nMAKTABA_PUBLIC_HOST=%s\nMAKTABA_OCR_TOKEN=%s\n' \
      "$HOME_DIR/library" "$(openssl rand -hex 24)" "${MAKTABA_PUBLIC_HOST:-maktaba.example.org}" "$(openssl rand -hex 24)" | sudo tee /etc/maktaba.env >/dev/null
    sudo chmod 600 /etc/maktaba.env
    echo "Wrote /etc/maktaba.env with a new secret token (root only). Set MAKTABA_PUBLIC_HOST in it to your own address."
  fi
  sudo systemctl daemon-reload
fi
cat <<MSG

Code and environments are in place. Still to do (see README.md):
  1. Put the search index into $HOME_DIR/semsearch/data            (build it with build/shamela-index, about \$8 on Modal)
  2. Copy the Shamela pages:  cd $HOME_DIR/semsearch/pages && ../venv/bin/python ingest.py run     (free, about 1.5 hours, 18 GB)
  3. Start the services:      sudo systemctl enable --now shamela-sem maktaba
  4. Put an HTTPS address in front of port 8790 and add  https://<your address>/<token>/mcp  to Claude as a connector
MSG
