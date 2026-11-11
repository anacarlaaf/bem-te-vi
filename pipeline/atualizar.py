"""
Atualização diária: coleta o CNES e grava nos destinos configurados.

Destinos (ativados pelas variáveis de ambiente):
  - Supabase       SUPABASE_DB_URL   fonte de dados do bot
  - Google Sheets  GOOGLE_SHEET_ID   opcional, cópia legível para a equipe

Fluxo:
  1. Lê a base atual do destino principal (Supabase, se houver), para comparar
     e para ter um "plano B" por CNES.
  2. Coleta tudo de novo no CNES.
  3. Travas de segurança: se algo parecer errado, NÃO grava nada e sai com
     erro (o bot continua com os dados de ontem).
  4. Grava em cada destino.

Uso:
    python -m pipeline.atualizar              # execução real
    python -m pipeline.atualizar --simular    # coleta e valida, não grava
"""

import argparse
import logging
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from pipeline import coletar_cnes_am as coleta
from pipeline import destino_sheets, destino_supabase

log = logging.getLogger("bemtevi.atualizar")

# A nova base precisa ter pelo menos X% das linhas da base atual.
PROPORCAO_MINIMA = float(os.getenv("PROPORCAO_MINIMA", "0.8"))
# Máximo de CNES que podem falhar no detalhe (em % do total).
MAX_PERCENT_ERROS = float(os.getenv("MAX_PERCENT_ERROS", "5"))

FUSO = ZoneInfo("America/Manaus")


class AbortarAtualizacao(Exception):
    pass


def destinos_configurados():
    destinos = []
    if destino_supabase.configurado():
        destinos.append(destino_supabase.DestinoSupabase())
    if destino_sheets.configurado():
        destinos.append(destino_sheets.DestinoSheets())
    return destinos


def montar_registros(resultado, atuais):
    """Registros coletados hoje + linhas de ontem para os CNES que falharam.
    Recalcula bairro oficial e colunas de busca para todas as linhas."""
    registros = list(resultado["registros"])
    reaproveitados = 0
    for cnes in resultado["cnes_com_erro"]:
        if cnes in atuais:
            registros.append(dict(atuais[cnes]))
            reaproveitados += 1
    coleta.enriquecer(registros)
    registros.sort(key=lambda r: (r.get("municipio", ""), r.get("nome", ""), r.get("cnes", "")))
    return registros, reaproveitados


def validar(resultado, total_novo, total_atual):
    if resultado["municipios_com_erro"]:
        raise AbortarAtualizacao(
            "Municípios sem resposta do CNES: " + ", ".join(resultado["municipios_com_erro"]))

    total = resultado["total_cnes"] or 1
    perc_erros = 100 * len(resultado["cnes_com_erro"]) / total
    if perc_erros > MAX_PERCENT_ERROS:
        raise AbortarAtualizacao(
            f"{perc_erros:.1f}% dos CNES falharam (limite {MAX_PERCENT_ERROS}%)")

    if total_novo == 0:
        raise AbortarAtualizacao("Coleta retornou zero estabelecimentos")

    if total_atual and total_novo < PROPORCAO_MINIMA * total_atual:
        raise AbortarAtualizacao(
            f"Nova base tem {total_novo} linhas contra {total_atual} atuais "
            f"(mínimo {PROPORCAO_MINIMA:.0%}). Verifique antes de sobrescrever.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--simular", action="store_true",
                        help="coleta e valida, mas não grava em nenhum destino")
    parser.add_argument("--limite", type=int, default=0,
                        help="só para teste: máximo de estabelecimentos")
    args = parser.parse_args()

    coleta.configurar_log()
    coleta.validar_credenciais()
    destinos = destinos_configurados()
    if not destinos:
        raise SystemExit("Nenhum destino configurado: defina SUPABASE_DB_URL e/ou GOOGLE_SHEET_ID.")
    log.info("Destinos: %s", ", ".join(d.nome for d in destinos))

    inicio = datetime.now(FUSO)
    _, atuais = destinos[0].ler_atual()
    log.info("Base atual (%s): %d unidades", destinos[0].nome, len(atuais))

    resultado = coleta.coletar(limite=args.limite)
    registros, reaproveitados = montar_registros(resultado, atuais)
    bairros = coleta.montar_bairros(registros)

    # Backup local do que será enviado (vira artefato no GitHub Actions)
    coleta.salvar_csv(registros, coleta.ARQUIVO_SAIDA)

    log.info("Coletados: %d | falhas de detalhe: %d (reaproveitados de ontem: %d) | bairros: %d",
             len(resultado["registros"]), len(resultado["cnes_com_erro"]),
             reaproveitados, len(bairros))

    try:
        validar(resultado, len(registros), 0 if args.limite else len(atuais))
    except AbortarAtualizacao as erro:
        log.error("ATUALIZAÇÃO CANCELADA, nada foi alterado: %s", erro)
        sys.exit(1)

    if args.simular:
        log.info("Simulação: %d unidades seriam gravadas. Nada foi alterado.", len(registros))
        return

    meta = {
        "ultima_atualizacao": datetime.now(FUSO).strftime("%d/%m/%Y %H:%M"),
        "fonte": "CNES / DATASUS",
        "total_estabelecimentos": len(registros),
        "falhas_reaproveitadas": reaproveitados,
        "duracao_min": round((datetime.now(FUSO) - inicio).seconds / 60, 1),
    }
    falhas = []
    for destino in destinos:
        try:
            destino.gravar(registros, bairros, meta)
        except Exception as erro:  # noqa: BLE001 - um destino não derruba o outro
            log.error("Falha ao gravar em %s: %s", destino.nome, erro)
            falhas.append(destino.nome)
    if falhas:
        sys.exit(1)
    log.info("Atualização concluída: %d unidades.", len(registros))


if __name__ == "__main__":
    main()
