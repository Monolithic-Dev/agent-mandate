#!/bin/sh
# Refuse to start an open database, then hand over to the image's own start script.
set -eu
: "${FALKORDB_PASSWORD:?set FALKORDB_PASSWORD}"
export REDIS_ARGS="--requirepass ${FALKORDB_PASSWORD} --appendonly yes"
exec /var/lib/falkordb/bin/run.sh "$@"
