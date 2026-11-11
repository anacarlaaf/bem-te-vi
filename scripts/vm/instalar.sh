#!/usr/bin/env bash
# Prepara uma VM Ubuntu (ex.: Oracle Cloud) para rodar a atualização diária.
# Rodar DENTRO da pasta do projeto, com um usuário comum que tenha sudo:
#   bash scripts/vm/instalar.sh
# Pode ser rodado de novo (ex.: depois de um git pull) sem problema.
set -euo pipefail
cd "$(dirname "$0")/../.."
PASTA=$(pwd)
USUARIO=$(id -un)

echo "==> Pacotes do sistema"
sudo apt-get update -qq
sudo apt-get install -y -qq python3-venv python3-pip git curl >/dev/null

echo "==> Ambiente Python"
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt

echo "==> Arquivo .env"
if [ ! -f .env ]; then
  echo "ERRO: crie o .env antes (copie do seu computador com scp ou use .env.example)."
  exit 1
fi
chmod 600 .env
if grep -qE '^SUPABASE_DB_URL=.*@db\.[a-z0-9]+\.supabase\.co' .env; then
  echo "AVISO: SUPABASE_DB_URL usa a conexão direta (só IPv6). Na VM use a do 'Session pooler'."
fi

echo "==> Agendamento (systemd)"
for u in bemtevi-atualizar.service bemtevi-atualizar.timer; do
  sed -e "s|__PASTA__|$PASTA|g" -e "s|__USUARIO__|$USUARIO|g" "scripts/vm/$u" \
    | sudo tee "/etc/systemd/system/$u" >/dev/null
done
chmod +x scripts/atualizar.sh
sudo systemctl daemon-reload
sudo systemctl enable --now bemtevi-atualizar.timer >/dev/null

echo
systemctl list-timers bemtevi-atualizar.timer --no-pager
echo
echo "Pronto. Próximos passos:"
echo "  teste sem gravar:   scripts/atualizar.sh --simular"
echo "  rodar agora:        scripts/atualizar.sh --forcar   (ignora o INTERVALO_DIAS)"
echo "  ver o resultado:    journalctl -u bemtevi-atualizar.service -n 50 --no-pager"
