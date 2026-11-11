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

ler_env() { grep -E "^$1=" .env 2>/dev/null | tail -1 | cut -d= -f2- | tr -d '"'"'" || true; }

# Aviso de falha opcional (ex.: healthchecks.io): HEALTHCHECK_URL no .env
HC=$(ler_env HEALTHCHECK_URL)

# Intervalo entre atualizações (INTERVALO_DIAS no .env, padrão 1).
# O agendador chama este script todo dia; ele só atualiza se a última
# atualização BEM-SUCEDIDA foi há INTERVALO_DIAS dias ou mais. Se uma falhar,
# tenta de novo no dia seguinte. "--simular" ou "--forcar" ignoram o intervalo.
INTERVALO_DIAS=$(ler_env INTERVALO_DIAS); INTERVALO_DIAS=${INTERVALO_DIAS:-1}
MARCA=.cache/ultima_atualizacao_ok
FORCAR=0; ARGS=()
for a in "$@"; do
  case "$a" in --forcar) FORCAR=1 ;; --simular) FORCAR=1; ARGS+=("$a") ;; *) ARGS+=("$a") ;; esac
done
if [ "$FORCAR" -eq 0 ] && [ -f "$MARCA" ]; then
  idade_h=$(( ( $(date +%s) - $(cat "$MARCA") ) / 3600 ))
  # tolerância de 6h para pequenas variações no horário de início
  if [ "$idade_h" -lt $(( INTERVALO_DIAS * 24 - 6 )) ]; then
    echo "$(date '+%F %T') última atualização há ${idade_h}h; intervalo é de ${INTERVALO_DIAS} dia(s). Pulando." | tee -a "$LOG"
    [ -n "$HC" ] && curl -fsS -m 10 --retry 3 "$HC" >/dev/null || true
    exit 0
  fi
fi

[ -n "$HC" ] && curl -fsS -m 10 --retry 3 "$HC/start" >/dev/null || true

status=0
.venv/bin/python -m pipeline.atualizar "${ARGS[@]}" 2>&1 | tee -a "$LOG" || status=$?

# Marca a última atualização real que deu certo (simulação não conta)
if [ "$status" -eq 0 ] && [[ " ${ARGS[*]} " != *" --simular "* ]]; then
  mkdir -p .cache && date +%s > "$MARCA"
fi

if [ -n "$HC" ]; then
  if [ "$status" -eq 0 ]; then curl -fsS -m 10 --retry 3 "$HC" >/dev/null || true
  else curl -fsS -m 10 --retry 3 "$HC/fail" >/dev/null || true; fi
fi

# Mantém só os últimos 60 dias de log
find logs -name '*.log' -mtime +60 -delete 2>/dev/null || true
exit "$status"
