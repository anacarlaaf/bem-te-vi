"""
Gera o fluxo do Typebot que consulta o Supabase (em vez da planilha).

Cada busca vira UMA chamada HTTP a uma função do banco
(supabase/001_bemtevi.sql), que já devolve o texto pronto:

  bt_resolver_bairro   reconhece o bairro (exato, parcial, erro de digitação)
  bt_buscar_unidades   busca no bairro, sem bairro, só SUS, com sinônimos
  bt_detalhar_unidade  dados e especialidades de uma unidade

Não há JavaScript de normalização no fluxo: toda a regra fica no banco.
Se o Supabase não responder, o bot avisa e volta ao menu.

URL e chave pública do Supabase: lidas de SUPABASE_URL e
SUPABASE_PUBLISHABLE_KEY (.env). Se não existirem, usa o projeto e a chave
que já aparecem no export (bloco que grava a tabela "interacoes").

Uso:
    python typebot/gerar_typebot_supabase.py
"""

import json
import os
import random
import re
import sys

PASTA = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PASTA)
sys.path.insert(0, os.path.dirname(PASTA))

import gerar_typebot as base  # noqa: E402
from gerar_typebot import Fluxo  # noqa: E402

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(PASTA), ".env"))
except ImportError:
    pass

NENHUM = "Nenhum desses"

# Grupos do fluxo antigo baseados em planilha (substituídos pelas chamadas HTTP)
GRUPOS_REMOVIDOS = [
    # encontrar posto
    "ptx72iuc2xqo3f8rs6otyquw", "ex8gqv8e01h5n24xqn02yics", "fsakiazy3n4gruwii9lv3k9f",
    # especialidade
    "gi0736h7bt90w3medjafnk10", "df4ct7tem0b5j2f0fp4feae1", "jaxk5pwtudnu23dh4lrry1dt",
    "row2iifnp02optqnynhbehzu", "k8ztp25cof6czwbe4pdirfvl", "lxp9wmamfmn9h66cddv0shfm",
    # detalhe de unidade
    "v13xnur38c5wj71pnsigjm86", "zl7w1qhy3k49l3n72xd8q8ab", "nod7s0nfdltwsvmja921kt21",
]

# Grupos de mensagem que continuam sendo usados
G_LISTA_POSTO = "liyfgdrrnayx7ozljndosarw"       # "Encontrei essas opções no bairro..."
G_ESP_NO_BAIRRO = "bwoawm4lcdgooyki0pps4x22"     # "...para a especialidade X no bairro Y"
G_ESP_SEM_BAIRRO = "x5f1ezz239gdm90bo882bepc"    # "Poxa! Não encontrei resultados no seu bairro..."
G_ESP_NADA = "n2wal0x8vwroysbhw1htihti"          # "Não temos informações sobre esta especialidade"
G_UNIDADE_OK = "dokurfvap0mm5nra5nipcucj"        # "Encontrei as seguintes informações..."
G_UNIDADE_NADA = "r3lircltnjwpww2cnbujh98n"      # "Desculpe. Não temos informações..."
G_MENU = "ye5ozt6v55lbsk5vhyyr4boa"              # "Deseja voltar ao menu inicial?"
E_INPUT_UNIDADE = "gg0myelqwn9q3lnlpwpi1shk"


def credenciais_supabase(d):
    url = os.getenv("SUPABASE_URL", "").rstrip("/")
    chave = os.getenv("SUPABASE_PUBLISHABLE_KEY", "")
    if url and chave:
        return url, chave, ".env"
    for g in d["groups"]:
        for b in g["blocks"]:
            w = (b.get("options") or {}).get("webhook") or {}
            m = re.match(r"(https://[^/]+\.supabase\.co)", w.get("url") or "")
            if m:
                for h in w.get("headers", []):
                    for campo in (h.get("value"), h.get("key")):
                        if campo and campo.startswith(("sb_publishable_", "eyJ")):
                            return m.group(1), campo, "export do Typebot"
    raise SystemExit("Defina SUPABASE_URL e SUPABASE_PUBLISHABLE_KEY no .env.")


class FluxoSupabase(Fluxo):
    def __init__(self, d, url, chave):
        super().__init__(d)
        self.url, self.chave = url, chave

    def http(self, funcao, corpo, mapeamento):
        """corpo: {param: "{{variavel}}" ou texto}; mapeamento: {variavel: expressão JS sobre data}"""
        body = "{\n" + ",\n".join(f'  "{k}": "{v}"' for k, v in corpo.items()) + "\n}"
        return {"id": self.rid(), "type": "Webhook", "options": {
            "isCustomBody": True,
            "timeout": 20,
            "webhook": {
                "method": "POST",
                "url": f"{self.url}/rest/v1/rpc/{funcao}",
                "headers": [
                    {"id": self.rid(), "key": "apikey", "value": self.chave},
                    {"id": self.rid(), "key": "Content-Type", "value": "application/json"},
                ],
                "body": body,
            },
            "responseVariableMapping": [
                {"id": self.rid(), "bodyPath": expr, "variableId": self.var(var)}
                for var, expr in mapeamento.items()
            ],
        }}

    def remover_grupos(self, ids):
        blocos = {b["id"] for g in self.d["groups"] if g["id"] in ids for b in g["blocks"]}
        self.d["groups"] = [g for g in self.d["groups"] if g["id"] not in ids]
        self.d["edges"] = [e for e in self.d["edges"]
                           if e["to"]["groupId"] not in ids and e["from"].get("blockId") not in blocos]
        self.G = {g["id"]: g for g in self.d["groups"]}
        self.E = {e["id"]: e for e in self.d["edges"]}

    def resolvedor_bairro(self, titulo, ancora, ok, nao_encontrado, erro):
        x, y = self.coords(ancora)
        mapa = {
            "bairro_status": 'data && data.status ? data.status : "erro"',
            "bairro_busca": 'data && data.busca ? data.busca : "-"',
            "bairro_nome": 'data && data.nome ? data.nome : ""',
        }

        # 3) bairro escolhido nos botões: confirma no banco para obter a chave
        confirma = self.grupo(f"{titulo}: confirmar bairro escolhido", x + 1050, y + 700, [
            self.http("bt_resolver_bairro",
                      {"p_municipio": "{{municipio_busca}}", "p_texto": "{{bairro_escolhido}}"}, mapa)])
        self.G[confirma]["blocks"].append(self.condicao([
            ("bairro_status", "Equal to", "ok", ok),
            ("bairro_status", "Equal to", "erro", erro),
        ], senao_grupo=nao_encontrado))

        escolhido = self.grupo(f"{titulo}: bairro escolhido", x + 700, y + 700, [])
        self.G[escolhido]["blocks"].append(self.condicao(
            [("bairro_escolhido", "Equal to", NENHUM, nao_encontrado)], senao_grupo=confirma))

        # 2) vários bairros parecidos: botões
        botoes = {"id": self.rid(), "type": "choice input",
                  "items": [{"id": self.rid(), "content": "(opções do bairro)"}],
                  "options": {"isMultipleChoice": False,
                              "dynamicVariableId": self.var("bairro_opcoes"),
                              "variableId": self.var("bairro_escolhido")}}
        escolher = self.grupo(f"{titulo}: escolher bairro", x + 350, y + 700,
                              [self.texto("{{bairro_pergunta}}"), botoes])
        botoes["outgoingEdgeId"] = self.edge(botoes["id"], escolhido)

        # 1) reconhecer o texto digitado
        entrada = self.grupo(f"{titulo}: reconhecer bairro", x, y + 700, [
            self.http("bt_resolver_bairro",
                      {"p_municipio": "{{municipio_busca}}", "p_texto": "{{bairro}}"},
                      {**mapa,
                       "bairro_opcoes": "data && data.opcoes ? data.opcoes : []",
                       "bairro_pergunta": 'data && data.pergunta ? data.pergunta : ""'})])
        self.G[entrada]["blocks"].append(self.condicao([
            ("bairro_status", "Equal to", "ok", ok),
            ("bairro_status", "Equal to", "nao_encontrado", nao_encontrado),
            ("bairro_status", "Equal to", "erro", erro),
        ], senao_grupo=escolher))
        return entrada


def gerar(d):
    url, chave, origem = credenciais_supabase(d)
    print(f"Supabase: {url} (credenciais de: {origem})")
    f = FluxoSupabase(d, url, chave)

    mapa_busca = {"modo_busca": 'data && data.modo ? data.modo : "erro"',
                  "resultado": 'data && data.texto ? data.texto : ""'}

    # Município do bot
    f.prepend(base.G_INICIO, [f.codigo("municipio_busca", f"return {json.dumps(base.MUNICIPIO_PADRAO)};")])

    # Erro de conexão com o banco
    x, y = f.coords(G_MENU)
    erro_txt = f.texto("Desculpe, não consegui consultar as unidades agora. "
                       "Tente de novo em alguns minutos. 🙏")
    erro = f.grupo("Erro ao consultar o Supabase", x - 400, y, [erro_txt])
    erro_txt["outgoingEdgeId"] = f.edge(erro_txt["id"], G_MENU)

    # --- Encontrar posto (só SUS) ---------------------------------
    x, y = f.coords(base.G_INPUT_BAIRRO_POSTO)
    busca_posto = f.grupo("Posto: buscar", x + 350, y, [
        f.http("bt_buscar_unidades", {"p_municipio": "{{municipio_busca}}", "p_bairro": "{{bairro_busca}}",
                                      "p_termo": "", "p_so_sus": "sim"}, mapa_busca)])
    f.G[busca_posto]["blocks"].append(f.condicao([
        ("modo_busca", "Equal to", "bairro", G_LISTA_POSTO),
        ("modo_busca", "Equal to", "erro", erro),
    ], senao_grupo=base.G_BAIRRO_SEM_INFO))
    resolver_posto = f.resolvedor_bairro("Posto", base.G_INPUT_BAIRRO_POSTO, ok=busca_posto,
                                         nao_encontrado=base.G_BAIRRO_SEM_INFO, erro=erro)
    f.E[base.E_INPUT_BAIRRO_POSTO]["to"] = {"groupId": resolver_posto}

    # --- Especialidade + bairro + pergunta SUS --------------------
    x, y = f.coords(base.G_INPUT_BAIRRO_ESP)
    busca_esp = f.grupo("Especialidade: buscar", x + 700, y, [
        f.codigo("so_sus", 'const r = String({{resposta_sus}} ?? "");\nreturn r.includes("Sim") ? "sim" : "nao";'),
        f.http("bt_buscar_unidades", {"p_municipio": "{{municipio_busca}}", "p_bairro": "{{bairro_busca}}",
                                      "p_termo": "{{especialidade}}", "p_so_sus": "{{so_sus}}"}, mapa_busca)])
    f.G[busca_esp]["blocks"].append(f.condicao([
        ("modo_busca", "Equal to", "bairro", G_ESP_NO_BAIRRO),
        ("modo_busca", "Equal to", "sem_bairro", G_ESP_SEM_BAIRRO),
        ("modo_busca", "Equal to", "erro", erro),
    ], senao_grupo=G_ESP_NADA))

    botoes_sus = {"id": f.rid(), "type": "choice input", "items": [],
                  "options": {"isMultipleChoice": False, "variableId": f.var("resposta_sus")}}
    for rotulo in ["✅ Sim, só pelo SUS", "Não, mostrar todas"]:
        item = {"id": f.rid(), "content": rotulo}
        item["outgoingEdgeId"] = f.edge(botoes_sus["id"], busca_esp, item["id"])
        botoes_sus["items"].append(item)
    pergunta_sus = f.grupo("Pergunta SUS", x + 350, y, [
        f.texto("Você quer ver só unidades que atendem pelo SUS?"), botoes_sus])

    # bairro não reconhecido: segue; a função busca a especialidade sem bairro
    resolver_esp = f.resolvedor_bairro("Especialidade", base.G_INPUT_BAIRRO_ESP, ok=pergunta_sus,
                                       nao_encontrado=pergunta_sus, erro=erro)
    f.E[base.E_INPUT_BAIRRO_ESP]["to"] = {"groupId": resolver_esp}

    # --- Especialidades de uma unidade ----------------------------
    x, y = f.coords(G_UNIDADE_OK)
    detalhe = f.grupo("Unidade: detalhar", x - 400, y, [
        f.http("bt_detalhar_unidade", {"p_municipio": "{{municipio_busca}}", "p_nome": "{{unidade}}"},
               {"unidade_encontrada": 'data && data.encontrado ? data.encontrado : "erro"',
                "resultado": 'data && data.texto ? data.texto : ""'})])
    f.G[detalhe]["blocks"].append(f.condicao([
        ("unidade_encontrada", "Equal to", "sim", G_UNIDADE_OK),
        ("unidade_encontrada", "Equal to", "erro", erro),
    ], senao_grupo=G_UNIDADE_NADA))
    f.E[E_INPUT_UNIDADE]["to"] = {"groupId": detalhe}

    # --- Textos que mostram o bairro --------------------------------
    for b in base.B_TEXTOS_COM_BAIRRO:
        for p in f.B[b]["content"]["richText"]:
            for c in p["children"]:
                c["text"] = c["text"].replace("{{bairro}}", "{{bairro_nome}}")

    # Por último: remove os grupos antigos de planilha (as entradas já foram religadas)
    f.remover_grupos(set(GRUPOS_REMOVIDOS))
    return d


if __name__ == "__main__":
    origem = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        PASTA, "export-original", "typebot-export-my-typebot-p07wqpu.json")
    destino = sys.argv[2] if len(sys.argv) > 2 else os.path.join(PASTA, "typebot-bem-te-vi-supabase.json")
    random.seed(42)
    fluxo = gerar(json.load(open(origem, encoding="utf-8")))
    json.dump(fluxo, open(destino, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"Fluxo gerado: {destino}")
