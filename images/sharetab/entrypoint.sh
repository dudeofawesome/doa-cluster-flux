#!/bin/sh
set -eu

: "${DATABASE_URL:?DATABASE_URL must point to the external PostgreSQL database}"
: "${AUTH_SECRET:?AUTH_SECRET is required}"
: "${NEXTAUTH_SECRET:?NEXTAUTH_SECRET is required}"

export UPLOAD_DIR="${UPLOAD_DIR:-/data/uploads}"
export CLAUDE_DIR="${CLAUDE_DIR:-/data/claude}"
export OPENAI_CODEX_DIR="${OPENAI_CODEX_DIR:-/data/chatgpt}"
export PGCONNECT_TIMEOUT=2
mkdir -p "$UPLOAD_DIR/receipts" "$CLAUDE_DIR" "$OPENAI_CODEX_DIR"
ln -sfn "$CLAUDE_DIR" "$HOME/.claude"

# Bound startup waiting so failed credentials/database connectivity are visible.
attempt=0
until psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -c 'SELECT 1' >/dev/null 2>&1; do
  attempt=$((attempt + 1))
  if [ "$attempt" -ge 60 ]; then
    echo "External PostgreSQL was not available after 60 attempts" >&2
    exit 1
  fi
  sleep 2
done

# The pinned upstream SQL migration upgrades GuestSplit, and assumes that table
# exists. On a fresh database Prisma creates the current schema directly.
has_guest_split=$(psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -Atc \
  "SELECT to_regclass('\"GuestSplit\"') IS NOT NULL")
if [ "$has_guest_split" = t ]; then
  for migration in /app/prisma/migrations/*.sql; do
    [ -f "$migration" ] || continue
    psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f "$migration"
  done
fi
NODE_PATH=/prisma-cli/node_modules \
  node /prisma-cli/node_modules/prisma/build/index.js db push

exec node server.js
