#!/usr/bin/env bash
# Browser-Test der Dashboard-Karten: startet einen Semaphore-Nachbau und ein frisches Home Assistant
# in einem Wegwerf-Ordner, richtet beides ein und prüft die Karten mit Playwright.
#
#   HA_PYTHON=venv/bin/python PW_PYTHON=venv/bin/python bash tests/browser/run_e2e.sh
#
# HA_PYTHON  Python mit installiertem Home Assistant (wie für pytest)
# PW_PYTHON  Python mit `playwright` (pip install playwright && playwright install chromium)
# KEEP=1     Arbeitsordner (Screenshots, Logs) nicht löschen
# CHECK_SCRIPT  anderes Prüfskript statt check_cards.py (z. B. zum Ausprobieren)
# UPDATE_SCREENSHOTS=1  die Karten-Bilder für die Doku neu erzeugen und nach docs/screenshots/ schreiben
#                       (sonst bleibt docs/screenshots unverändert: die Bilder enthalten Uhrzeiten und würden bei jedem Lauf abweichen)
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
HA_PYTHON="${HA_PYTHON:-python3}"
PW_PYTHON="${PW_PYTHON:-$HA_PYTHON}"
# relative Pfade (venv/bin/python) absolut machen: Home Assistant startet in einem anderen Ordner
for var in HA_PYTHON PW_PYTHON; do
  case "${!var}" in
    */*) printf -v "$var" '%s' "$(cd "$(dirname "${!var}")" && pwd)/$(basename "${!var}")" ;;
  esac
done
HA_PORT="${HA_PORT:-8123}"   # Standard-Port: Home Assistant 2026.10 fragt bei einem anderen Port im YAML per Dialog nach
FAKE_PORT="${FAKE_PORT:-13000}"
export E2E_DIR="${E2E_DIR:-$(mktemp -d)}"
[ "${UPDATE_SCREENSHOTS:-0}" = "1" ] && export DOCS_SHOTS="$ROOT/docs/screenshots"
export HA_URL="http://127.0.0.1:${HA_PORT}"
export FAKE_URL="http://127.0.0.1:${FAKE_PORT}"
CONFIG="$E2E_DIR/config"
HTTP_YAML=""
[ "$HA_PORT" = "8123" ] || HTTP_YAML=$'http:\n  server_port: '"$HA_PORT"$'\n'
PIDS=()

cleanup() {
  for pid in "${PIDS[@]:-}"; do kill "$pid" 2>/dev/null || true; done
  for pid in "${PIDS[@]:-}"; do wait "$pid" 2>/dev/null || true; done   # Home Assistant schreibt beim Beenden noch Dateien
  if [ "${KEEP:-0}" = "1" ]; then echo "Arbeitsordner: $E2E_DIR"; else
    # Screenshots bleiben nur bei Fehlern erhalten
    [ "${FAILED:-0}" = "1" ] && echo "Screenshots/Logs: $E2E_DIR" || rm -rf "$E2E_DIR" || true
  fi
}
trap cleanup EXIT

mkdir -p "$CONFIG/custom_components" "$CONFIG/.storage"
cp -r "$ROOT/custom_components/semaphore_ui" "$CONFIG/custom_components/"
cat > "$CONFIG/configuration.yaml" <<EOF
homeassistant:
  name: Test
  latitude: 52.5
  longitude: 13.4
  elevation: 30
  unit_system: metric
  time_zone: Europe/Berlin
  language: de
  country: DE
${HTTP_YAML}frontend:
config:
lovelace:
logger:
  default: warning
  logs:
    custom_components.semaphore_ui: debug
EOF
echo '{"version":4,"minor_version":1,"key":"onboarding","data":{"done":["user","core_config","analytics","integration"]}}' > "$CONFIG/.storage/onboarding"
"$HA_PYTHON" -m homeassistant --script auth -c "$CONFIG" add tester testpass123 > /dev/null

"$HA_PYTHON" "$HERE/fake_server.py" "$FAKE_PORT" > "$E2E_DIR/fake.log" 2>&1 &
PIDS+=($!)
(cd "$E2E_DIR" && exec "$HA_PYTHON" -m homeassistant -c "$CONFIG" > "$E2E_DIR/ha.log" 2>&1) &
PIDS+=($!)

echo "Warte auf Home Assistant …"
for _ in $(seq 1 90); do
  code=$(curl -s -m 3 -o /dev/null -w "%{http_code}" "$HA_URL/" || true)
  case "$code" in 200|302) break;; esac
  sleep 2
done
[ "$code" = "200" ] || [ "$code" = "302" ] || { echo "Home Assistant startet nicht – siehe $E2E_DIR/ha.log"; FAILED=1; exit 1; }

"$HA_PYTHON" "$HERE/setup_ha.py"
if "$PW_PYTHON" "${CHECK_SCRIPT:-$HERE/check_cards.py}"; then :; else FAILED=1; exit 1; fi
