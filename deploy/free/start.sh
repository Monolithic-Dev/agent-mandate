#!/bin/sh
# Starts FalkorDB (in memory, bound to localhost), seeds the demo tenant, creates the first
# admin, then serves the API and the console on $PORT. Stops if either process dies, so the
# host restarts the container rather than leaving half of it running.
set -eu

PORT="${PORT:-10000}"
random() { python -c 'import secrets; print(secrets.token_hex(24))'; }
export FALKORDB_PASSWORD="${FALKORDB_PASSWORD:-$(random)}"   # nothing outside the container can reach it
export MANDATE_API_KEY="${MANDATE_API_KEY:-$(random)}"        # for scripts; people sign in
export FALKORDB_HOST=127.0.0.1 FALKORDB_PORT=6379
# Render sets the service's own address; approval links in alerts are built from it.
export MANDATE_PUBLIC_URL="${MANDATE_PUBLIC_URL:-${RENDER_EXTERNAL_URL:-}}"

mkdir -p /tmp/falkordb
redis-server --bind 127.0.0.1 --port 6379 --protected-mode yes \
  --requirepass "$FALKORDB_PASSWORD" --save "" --appendonly no --maxmemory 192mb \
  --dir /tmp/falkordb --loadmodule /opt/falkordb/falkordb.so \
  MAX_QUEUED_QUERIES 25 TIMEOUT 1000 RESULTSET_SIZE 10000 &
DB=$!

tries=0
until redis-cli --no-auth-warning -a "$FALKORDB_PASSWORD" ping 2>/dev/null | grep -q PONG; do
  tries=$((tries + 1))
  if [ "$tries" -gt 120 ] || ! kill -0 "$DB" 2>/dev/null; then
    echo "FalkorDB did not start" >&2
    exit 1
  fi
  sleep 0.5
done

if [ "${MANDATE_SEED:-1}" = "1" ]; then
  python -m mandate.seed --reset >/dev/null || echo "seeding the demo tenant failed; continuing" >&2
fi
if [ -n "${MANDATE_ADMIN_EMAIL:-}" ] && [ -n "${MANDATE_ADMIN_PASSWORD:-}" ]; then
  MANDATE_NEW_PASSWORD="$MANDATE_ADMIN_PASSWORD" \
    python -m mandate.users add "$MANDATE_ADMIN_EMAIL" --name "${MANDATE_ADMIN_NAME:-Admin}" --role admin \
    || echo "creating the admin failed; continuing" >&2
else
  echo "MANDATE_ADMIN_EMAIL and MANDATE_ADMIN_PASSWORD are not set: nobody can sign in" >&2
fi
# An optional second account for visitors (judges): it can run scenarios and approve held
# actions, but cannot manage users or read the audit log.
if [ -n "${MANDATE_DEMO_EMAIL:-}" ] && [ -n "${MANDATE_DEMO_PASSWORD:-}" ]; then
  MANDATE_NEW_PASSWORD="$MANDATE_DEMO_PASSWORD"     python -m mandate.users add "$MANDATE_DEMO_EMAIL" --name "Demo visitor" --role operator     || echo "creating the demo account failed; continuing" >&2
fi

uvicorn --factory mandate.api.app:create_app --host 0.0.0.0 --port "$PORT" \
  --proxy-headers --forwarded-allow-ips '*' &
API=$!

trap 'kill "$DB" "$API" 2>/dev/null; exit 0' TERM INT
while kill -0 "$DB" 2>/dev/null && kill -0 "$API" 2>/dev/null; do
  sleep 2
done
echo "a process stopped; exiting so the host restarts the container" >&2
kill "$DB" "$API" 2>/dev/null || true
exit 1
