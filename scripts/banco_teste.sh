#!/usr/bin/env bash
# Postgres local descartável para testar o SQL e o fluxo sem tocar no Supabase.
#   scripts/banco_teste.sh iniciar   cria (se preciso) e sobe em localhost:54329, banco "bemtevi"
#   scripts/banco_teste.sh parar
#   scripts/banco_teste.sh recriar   apaga e cria do zero
# Requer PostgreSQL 16 instalado (pacotes postgresql-16 e postgresql-contrib).
set -euo pipefail
cd "$(dirname "$0")/.."
BIN=$(ls -d /usr/lib/postgresql/*/bin | sort -V | tail -1)
DADOS=.cache/pg
PSQL="psql -h localhost -p 54329 -U postgres -q -v ON_ERROR_STOP=1"

iniciar() {
  if [ ! -d "$DADOS" ]; then
    "$BIN/initdb" -D "$DADOS" -U postgres --auth=trust -E UTF8 --locale=C.UTF-8 >/dev/null
  fi
  "$BIN/pg_ctl" -D "$DADOS" -o "-p 54329 -k /tmp -c listen_addresses=localhost" -l .cache/pg.log status >/dev/null 2>&1 \
    || "$BIN/pg_ctl" -D "$DADOS" -o "-p 54329 -k /tmp -c listen_addresses=localhost" -l .cache/pg.log -w start >/dev/null
  $PSQL -tc "select 1 from pg_database where datname='bemtevi'" | grep -q 1 || $PSQL -c "create database bemtevi"
  $PSQL -d bemtevi -f supabase/teste_local_bootstrap.sql
  $PSQL -d bemtevi -f supabase/001_bemtevi.sql 2>&1 | grep -v NOTICE || true
  echo "Banco de teste pronto: postgresql://postgres@localhost:54329/bemtevi"
}

case "${1:-}" in
  iniciar) iniciar ;;
  parar) "$BIN/pg_ctl" -D "$DADOS" stop ;;
  recriar) "$BIN/pg_ctl" -D "$DADOS" stop 2>/dev/null || true; rm -rf "$DADOS"; iniciar ;;
  *) echo "uso: $0 iniciar|parar|recriar"; exit 1 ;;
esac
