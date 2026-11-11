"""
Destino Supabase (Postgres): fonte de dados do bot.

Grava as tabelas criadas por supabase/001_bemtevi.sql numa ÚNICA transação:
quem estiver consultando continua vendo a base antiga até o fim da carga, e
se qualquer coisa falhar nada muda.

Variável de ambiente:
  SUPABASE_DB_URL  string de conexão do Postgres. No Supabase:
                   Project Settings > Database > Connection string > "Session pooler"
                   (funciona em IPv4, inclusive no GitHub Actions).
                   Ex.: postgresql://postgres.<projeto>:<SENHA>@aws-0-sa-east-1.pooler.supabase.com:5432/postgres
"""

import logging
import os

import psycopg

from pipeline import normalizacao

log = logging.getLogger("bemtevi.supabase")

DB_URL = os.getenv("SUPABASE_DB_URL", "")

COLUNAS = [
    "cnes", "nome", "endereco", "telefone", "especialidades", "municipio",
    "bairro", "bairro_oficial", "tipo_unidade", "data_atualizacao_cnes",
    "atende_sus", "busca_nome", "busca_servicos", "busca_bairro",
]

# Textos difíceis para conferir se o SQL normaliza igual ao Python
AMOSTRAS_FIXAS = [
    "  Japiinlândia  ", "São José Operário II", "PRAÇA 14", "Psicólogos", "Vacinações",
    "Hospitais", "exame de sangue", "Pré-Natal", "USF 1º de Maio", "Ação & Saúde",
    "quero um dentista", "Raio-X", "Clínico   Geral", "stress", "ÁÉÍÓÚ âêô ãõ ç ü",
]


def configurado():
    return bool(DB_URL)


class DestinoSupabase:
    nome = "Supabase"

    def __init__(self, url=None):
        self.url = url or DB_URL

    def _conectar(self):
        # prepare_threshold=None: compatível com o pooler do Supabase
        return psycopg.connect(self.url, prepare_threshold=None)

    def ler_atual(self):
        with self._conectar() as conn:
            cur = conn.execute(f"select {', '.join(COLUNAS)} from public.bt_unidades")
            atuais = {}
            for linha in cur.fetchall():
                reg = dict(zip(COLUNAS, linha))
                reg["atende_sus"] = "sim" if reg["atende_sus"] else "nao"
                atuais[reg["cnes"]] = reg
        return list(COLUNAS), atuais

    def verificar_normalizacao(self, conn, registros):
        """Confere se as funções SQL normalizam igual ao Python.

        Diferença sistemática (ex.: SQL desatualizado) aborta a carga.
        Diferenças pontuais (caracteres raros) só geram aviso.
        """
        textos = list(AMOSTRAS_FIXAS)
        for reg in registros:
            textos += [reg.get("nome", ""), reg.get("bairro", ""),
                       reg.get("especialidades", "")[:200]]
        textos = sorted(set(textos))
        cur = conn.execute(
            "select t, public.bt_sem_acento(t), public.bt_normalizar_busca(t) "
            "from unnest(%s::text[]) as t", (textos,))
        divergentes = [
            (t, sql_a, normalizacao.sem_acento(t), sql_b, normalizacao.normalizar_busca(t))
            for t, sql_a, sql_b in cur.fetchall()
            if sql_a != normalizacao.sem_acento(t) or sql_b != normalizacao.normalizar_busca(t)
        ]
        if not divergentes:
            return
        for t, sa, pa, sb, pb in divergentes[:5]:
            log.warning("Normalização diverge para %r: SQL=(%r, %r) Python=(%r, %r)",
                        t, sa, sb, pa, pb)
        fixas_divergentes = [d for d in divergentes if d[0] in AMOSTRAS_FIXAS]
        if fixas_divergentes or len(divergentes) > 0.01 * len(textos):
            raise RuntimeError(
                f"As funções SQL normalizam diferente do Python em {len(divergentes)} "
                f"de {len(textos)} textos. Reaplique supabase/001_bemtevi.sql."
            )

    def gravar(self, registros, bairros, meta):
        with self._conectar() as conn:          # uma transação; commit no final
            self.verificar_normalizacao(conn, registros)

            conn.execute("delete from public.bt_unidades")
            with conn.cursor().copy(
                f"copy public.bt_unidades ({', '.join(COLUNAS)}) from stdin"
            ) as copia:
                for reg in registros:
                    copia.write_row([
                        str(reg.get("atende_sus", "")).lower() == "sim" if c == "atende_sus"
                        else str(reg.get(c) or "")
                        for c in COLUNAS
                    ])

            conn.execute("delete from public.bt_bairros")
            with conn.cursor().copy(
                "copy public.bt_bairros (municipio, bairro, busca_bairro, variantes, unidades) "
                "from stdin"
            ) as copia:
                for b in bairros:
                    variantes = [v.strip() for v in b["variantes"].split("|") if v.strip()]
                    copia.write_row([b["municipio"], b["bairro"], b["busca_bairro"],
                                     variantes, int(b["unidades"])])

            for chave, valor in meta.items():
                conn.execute(
                    "insert into public.bt_meta (chave, valor) values (%s, %s) "
                    "on conflict (chave) do update set valor = excluded.valor",
                    (chave, str(valor)))
        log.info("Supabase: %d unidades e %d bairros gravados.", len(registros), len(bairros))
