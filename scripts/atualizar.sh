#!/usr/bin/env bash
# Roda a atualização diária e guarda o log.
# Usado pelo agendamento da VM (systemd) ou por cron:
#   0 5 * * * /caminho/para/bem-te-vi/scripts/atualizar.sh
# Argumentos são repassados ao pipeline, ex.: scripts/atualizar.sh --simular
set -euo pipefail
cd "$(dirname "$0")/.."
export TZ=America/Manaus
mkdir -p logs
LOG="logs/$(date +%F).log"

# Impede duas execuções ao mesmo tempo
exec 9>.cache.lock
if ! flock -n 9; then
  echo "$(date '+%F %T') já existe uma atualização rodando; saindo." | tee -a "$LOG"
  exit 0
fi

# Aviso de falha opcional (ex.: healthchecks.io): HEALTHCHECK_URL no .env
HC=$(grep -E '^HEALTHCHECK_URL=' .env 2>/dev/null | cut -d= -f2- | tr -d '"'"'" || true)
[ -n "$HC" ] && curl -fsS -m 10 --retry 3 "$HC/start" >/dev/null || true

status=0
.venv/bin/python -m pipeline.atualizar "$@" 2>&1 | tee -a "$LOG" || status=$?

if [ -n "$HC" ]; then
  if [ "$status" -eq 0 ]; then curl -fsS -m 10 --retry 3 "$HC" >/dev/null || true
  else curl -fsS -m 10 --retry 3 "$HC/fail" >/dev/null || true; fi
fi

# Mantém só os últimos 60 dias de log
find logs -name '*.log' -mtime +60 -delete 2>/dev/null || true
exit "$status"
