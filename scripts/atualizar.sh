#!/usr/bin/env bash
# Alternativa ao GitHub Actions: rodar via cron numa máquina/servidor.
# crontab -e  ->  0 5 * * * /caminho/para/bem-te-vi/scripts/atualizar.sh
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p logs
.venv/bin/python -m pipeline.atualizar >> "logs/$(date +%F).log" 2>&1
