"""
Destino Google Sheets (opcional desde a migração para o Supabase).

Útil como cópia legível para a equipe, ou para quem ainda usa o fluxo antigo
do Typebot (typebot/typebot-bem-te-vi.json), que lê direto da planilha.

Variáveis de ambiente:
  GOOGLE_SHEET_ID               ID da planilha (trecho entre /d/ e /edit)
  GOOGLE_SHEET_ABA              aba principal (vazio = primeira aba)
  GOOGLE_CREDENTIALS_JSON       conteúdo do JSON da conta de serviço (CI)
  GOOGLE_APPLICATION_CREDENTIALS  ou o caminho do arquivo JSON
"""

import json
import logging
import os

import gspread

from pipeline import coletar_cnes_am as coleta
from pipeline.normalizacao import RAIZ

log = logging.getLogger("bemtevi.sheets")

SHEET_ID = os.getenv("GOOGLE_SHEET_ID", "")
SHEET_ABA = os.getenv("GOOGLE_SHEET_ABA", "")
ABA_META = os.getenv("GOOGLE_SHEET_ABA_META", "atualizacao")
# O Typebot identifica a aba pelo número interno (gid). A aba de bairros é
# criada com um gid FIXO, o mesmo usado por typebot/gerar_typebot.py.
ABA_BAIRROS = os.getenv("GOOGLE_SHEET_ABA_BAIRROS", "bairros")
GID_BAIRROS = int(os.getenv("GOOGLE_SHEET_GID_BAIRROS", "7001"))
CREDENCIAIS_ARQUIVO = os.getenv(
    "GOOGLE_APPLICATION_CREDENTIALS", os.path.join(RAIZ, "credenciais_google.json")
)


def configurado():
    return bool(SHEET_ID)


class DestinoSheets:
    nome = "Google Sheets"

    def __init__(self):
        conteudo = os.getenv("GOOGLE_CREDENTIALS_JSON")
        if conteudo:
            cliente = gspread.service_account_from_dict(json.loads(conteudo))
        else:
            cliente = gspread.service_account(filename=CREDENCIAIS_ARQUIVO)
        self.planilha = cliente.open_by_key(SHEET_ID)
        self.aba = (self.planilha.worksheet(SHEET_ABA) if SHEET_ABA
                    else self.planilha.sheet1)

    def ler_atual(self):
        """Retorna (cabeçalho, {cnes: linha_como_dict})."""
        valores = self.aba.get_all_values()
        if not valores:
            return [], {}
        cabecalho = [c.strip() for c in valores[0]]
        linhas = {}
        for valores_linha in valores[1:]:
            linha = dict(zip(cabecalho, valores_linha))
            cnes = str(linha.get("cnes", "")).strip()
            if cnes:
                linhas[cnes] = linha
        return cabecalho, linhas

    def gravar(self, registros, bairros, meta):
        # Colunas criadas à mão na planilha são preservadas (valor pelo CNES)
        cabecalho_atual, atuais = self.ler_atual()
        extras = [c for c in cabecalho_atual if c and c not in coleta.CAMPOS]
        if extras:
            log.info("Sheets: preservando colunas manuais %s", extras)
        cabecalho = coleta.CAMPOS + extras
        tabela = [cabecalho]
        for reg in registros:
            antigo = atuais.get(str(reg.get("cnes", "")), {})
            tabela.append([str(reg.get(c, antigo.get(c, "")) or "") for c in cabecalho])

        _sobrescrever(self.aba, tabela)
        self._gravar_bairros(bairros)
        self._gravar_meta(meta)
        log.info("Sheets: %d linhas gravadas.", len(registros))

    def _gravar_bairros(self, linhas):
        try:
            aba = self.planilha.get_worksheet_by_id(GID_BAIRROS)
        except gspread.WorksheetNotFound:
            try:
                existente = self.planilha.worksheet(ABA_BAIRROS)
                raise RuntimeError(
                    f"A aba '{ABA_BAIRROS}' já existe com gid {existente.id}, mas o "
                    f"Typebot espera gid {GID_BAIRROS}. Apague/renomeie essa aba "
                    "para o script recriá-la."
                )
            except gspread.WorksheetNotFound:
                pass
            self.planilha.batch_update({"requests": [{"addSheet": {"properties": {
                "title": ABA_BAIRROS, "sheetId": GID_BAIRROS,
                "gridProperties": {"rowCount": 10, "columnCount": 5},
            }}}]})
            aba = self.planilha.get_worksheet_by_id(GID_BAIRROS)
            log.info("Sheets: aba '%s' criada (gid %s).", ABA_BAIRROS, GID_BAIRROS)

        tabela = [coleta.CAMPOS_BAIRROS] + [
            [str(l[c]) for c in coleta.CAMPOS_BAIRROS] for l in linhas
        ]
        _sobrescrever(aba, tabela)

    def _gravar_meta(self, info):
        try:
            aba = self.planilha.worksheet(ABA_META)
        except gspread.WorksheetNotFound:
            aba = self.planilha.add_worksheet(ABA_META, rows=20, cols=2)
        linhas = [["campo", "valor"]] + [[k, str(v)] for k, v in info.items()]
        aba.clear()
        aba.update(range_name="A1", values=linhas,
                   value_input_option=gspread.utils.ValueInputOption.raw)


def _sobrescrever(aba, tabela):
    n_linhas, n_colunas = len(tabela), len(tabela[0])
    # Garante espaço (a API recusa escrever fora da grade)...
    aba.resize(rows=max(n_linhas, aba.row_count), cols=max(n_colunas, aba.col_count))
    # ...escreve tudo numa única chamada. RAW evita que o Sheets transforme
    # CNES, telefone ou datas em número.
    aba.update(range_name="A1", values=tabela,
               value_input_option=gspread.utils.ValueInputOption.raw)
    # ...e remove as linhas que sobraram da base anterior.
    aba.resize(rows=n_linhas)
