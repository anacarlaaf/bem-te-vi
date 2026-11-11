"""
Gera o fluxo do Typebot a partir do export original, aplicando:

  - busca sem acento/maiúsculas/plurais e com sinônimos (colunas busca_*);
  - pergunta "só SUS?" na busca por especialidade;
  - "Encontrar posto" só com unidades do SUS;
  - filtro pelo município do bot (variável municipio_busca, padrão Manaus);
  - bairro reconhecido pelo nome oficial (aba "bairros"), com botões para
    escolher quando o texto digitado bate com mais de um bairro e
    "você quis dizer...?" para erros de digitação;
  - formatação robusta das listas (1 ou vários resultados, máximo 5).

Uso:
    python typebot/gerar_typebot.py   (lê typebot/export-original/ e grava typebot/typebot-bem-te-vi.json)
"""

import json
import os
import random
import string
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pipeline import normalizacao  # noqa: E402

MUNICIPIO_PADRAO = "Manaus"
GID_BAIRROS = os.getenv("GOOGLE_SHEET_GID_BAIRROS", "7001")
NENHUM = "Nenhum desses"
MAX_OPCOES = 6

# ------------------------------------------------------------------
# JavaScript gerado a partir de normalizacao.py (mesmas regras)
# ------------------------------------------------------------------

JS_NORMALIZACAO = """const semAcento = (t) => String(t ?? "")
  .normalize("NFD")
  .replace(/[\\u0300-\\u036f]/g, "")
  .toLowerCase()
  .replace(/\\s+/g, " ")
  .trim();

const STOPWORDS = new Set(%s);

const radical = (p) => {
  if (p.length > 4 && p.endsWith("oes")) return p.slice(0, -3) + "ao";
  if (p.length > 4 && p.endsWith("ais")) return p.slice(0, -3) + "al";
  if (p.length > 3 && p.endsWith("s") && !p.endsWith("ss")) return p.slice(0, -1);
  return p;
};

const normalizarBusca = (t) => semAcento(t)
  .replace(/[^a-z0-9]+/g, " ")
  .split(" ")
  .filter((p) => p && !STOPWORDS.has(p))
  .map(radical)
  .join(" ");
""" % json.dumps(normalizacao.STOPWORDS)

JS_RESOLVER_BAIRRO = JS_NORMALIZACAO + r"""
// Reconhece o bairro digitado a partir da aba "bairros".
const lista = (v) => Array.isArray(v) ? v : (v === undefined || v === null || v === "" ? [] : [v]);
const nomes = lista({{lista_bairros}});
const chaves = lista({{lista_chaves}});
const variantes = lista({{lista_variantes}}).map((v) => String(v ?? "").split("|").map((s) => s.trim()).filter(Boolean));
const unidades = lista({{lista_unidades}}).map((n) => Number(n) || 0);

const SUFIXO = /SUFIXO_REGEX/;
const digitado = semAcento(String({{bairro}} ?? "").replace(/[.,;:!?()"]+/g, " "))
  .replace(/^((bairro|conjunto|conj|cj|residencial|res|comunidade|loteamento|lot|no|na|do|da)\s+)+/, "");
const semSufixo = digitado.replace(SUFIXO, "");
const nomesDe = (i) => [chaves[i], ...(variantes[i] || [])];

const resposta = (status, i, opcoes, pergunta) => JSON.stringify({
  status,
  busca: i === null ? "-" : chaves[i],
  nome: i === null ? "" : nomes[i],
  opcoes: opcoes || [],
  pergunta: pergunta || "",
});

if (!digitado) return resposta("nao_encontrado", null);

// 1) Nome exato (ou variação conhecida, como "Cidade Nova II" ou "Japiinlândia")
for (let i = 0; i < chaves.length; i++) {
  const n = nomesDe(i);
  if (n.includes(digitado) || n.includes(semSufixo)) return resposta("ok", i);
}

// 2) Parcial: cada palavra digitada é começo de uma palavra do bairro
//    ("nova" -> Cidade Nova, Nova Cidade, Nova Esperança...)
const palavras = digitado.split(" ");
let candidatos = [];
if (digitado.length >= 3) {
  for (let i = 0; i < chaves.length; i++) {
    const bate = nomesDe(i).some((nome) =>
      palavras.every((p) => nome.split(" ").some((w) => w.startsWith(p))));
    if (bate) candidatos.push(i);
  }
}
if (candidatos.length === 1) return resposta("ok", candidatos[0]);

let pergunta = `Encontrei mais de um bairro parecido com "${{{bairro}}}". Qual é o seu?`;

// 3) Erro de digitação ("japim" -> Japiim)
if (!candidatos.length) {
  const distancia = (a, b) => {
    const d = Array.from({ length: a.length + 1 }, (_, i) => [i]);
    for (let j = 1; j <= b.length; j++) d[0][j] = j;
    for (let i = 1; i <= a.length; i++)
      for (let j = 1; j <= b.length; j++)
        d[i][j] = Math.min(d[i - 1][j] + 1, d[i][j - 1] + 1,
          d[i - 1][j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
    return d[a.length][b.length];
  };
  const limite = digitado.length <= 5 ? 1 : 2;
  for (let i = 0; i < chaves.length; i++) {
    if (nomesDe(i).some((nome) => distancia(digitado, nome) <= limite)) candidatos.push(i);
  }
  pergunta = `Não achei o bairro "${{{bairro}}}". Você quis dizer:`;
}

if (!candidatos.length) return resposta("nao_encontrado", null);

candidatos.sort((a, b) => unidades[b] - unidades[a]);
const opcoes = candidatos.slice(0, MAX_OPCOES).map((i) => nomes[i]).concat([NENHUM_DESSES]);
return resposta("escolher", null, opcoes, pergunta);
""".replace("SUFIXO_REGEX", normalizacao.SUFIXO_BAIRRO) \
   .replace("MAX_OPCOES", str(MAX_OPCOES)) \
   .replace("NENHUM_DESSES", json.dumps(NENHUM))

JS_LISTA = r"""const comoLista = (v) =>
  Array.isArray(v) ? v : (v === undefined || v === null || v === "" ? [] : [v]);

const nomes = comoLista({{nome}});
const enderecos = comoLista({{endereco}});
const telefones = comoLista({{telefone}});

const total = Math.min(5, nomes.length);
const partes = [];

for (let i = 0; i < total; i++) {
  partes.push(
    `🏥 ${nomes[i] || "Nome não informado"}\n` +
    `📍 ${enderecos[i] || "Endereço não informado"}\n` +
    `📞 ${telefones[i] || "Telefone não informado"}`
  );
}

let resposta = partes.join("\n\n");

if (nomes.length > total) {
  resposta += `\n\nMostrando ${total} de ${nomes.length} unidades encontradas.`;
}

return resposta;"""

JS_DETALHE_UNIDADE = r"""const primeiro = (v) => (Array.isArray(v) ? v[0] : v);

const nome = primeiro({{nome}}) || "Nome não informado";
const endereco = primeiro({{endereco}}) || "Endereço não informado";
const telefone = primeiro({{telefone}}) || "Telefone não informado";

const lista = String(primeiro({{todas_especialidades}}) || "")
  .split("|")
  .map((x) => x.trim())
  .filter(Boolean);

const funcoes = lista.length
  ? lista.map((x) => `• ${x}`).join("\n")
  : "Não informado";

return `🏥 ${nome}\n📍 ${endereco}\n📞 ${telefone}\n\n🩺 Especialidades:\n${funcoes}`;"""


# ------------------------------------------------------------------
# IDs do export original (blocos e grupos existentes)
# ------------------------------------------------------------------

G_INICIO = "wifp2i2vqzcbj4nnz7tq8yd2"
G_INPUT_BAIRRO_POSTO = "lm5qph45zvsaoio6gxn6yv9c"
G_SHEETS_POSTO = "ptx72iuc2xqo3f8rs6otyquw"
B_SHEETS_POSTO = "reh01k7u4kzetvnuytycipmf"
G_BAIRRO_SEM_INFO = "ybclgxjchjz6jv5p23rr9zzw"
E_INPUT_BAIRRO_POSTO = "aa70gmydxna5dv4136rvuaz2"

G_INPUT_BAIRRO_ESP = "t1txodz6jzri6k1j56unisny"
E_INPUT_BAIRRO_ESP = "pk0vx3gvyxancbzhu2llqprn"
G_SHEETS_ESP = "gi0736h7bt90w3medjafnk10"
B_SHEETS_ESP = "nceb30jhdyvrwv7398liih86"
B_SHEETS_ESP_RESERVA = "ourlohxyrk8dl2vko0sn21tp"

G_SHEETS_UNIDADE = "v13xnur38c5wj71pnsigjm86"
B_SHEETS_UNIDADE = "zo7lz0g1zahwfeu0c7i54fvz"

B_LISTAS = ["wrgff4bbjooimgulcr0v46qh", "foxgihtrwrzbfjp6hppzrmzo",
            "oo8as0rkq6m5xi21trbw78c6"]
B_DETALHE = "l2ngnz2225dxf2vyq9z5q79g"
B_TEXTOS_COM_BAIRRO = ["uwcsvg3hm4l5otm6fq2ssfje", "cem90304mok3ql4g88ibf0l3"]


class Fluxo:
    def __init__(self, d):
        self.d = d
        self.G = {g["id"]: g for g in d["groups"]}
        self.B = {b["id"]: b for g in d["groups"] for b in g["blocks"]}
        self.E = {e["id"]: e for e in d["edges"]}
        sheets = self.B[B_SHEETS_POSTO]["options"]
        self.spreadsheet_id = sheets["spreadsheetId"]
        self.credentials_id = sheets["credentialsId"]

    @staticmethod
    def rid():
        return random.choice(string.ascii_lowercase) + "".join(
            random.choices(string.ascii_lowercase + string.digits, k=23))

    def var(self, nome):
        for v in self.d["variables"]:
            if v["name"] == nome:
                return v["id"]
        v = {"id": self.rid(), "name": nome, "isSessionVariable": True}
        self.d["variables"].append(v)
        return v["id"]

    def edge(self, de_bloco, para_grupo, item=None):
        e = {"id": self.rid(), "from": {"blockId": de_bloco}, "to": {"groupId": para_grupo}}
        if item:
            e["from"]["itemId"] = item
        self.d["edges"].append(e)
        self.E[e["id"]] = e
        return e["id"]

    def grupo(self, titulo, x, y, blocos):
        g = {"id": self.rid(), "title": titulo,
             "graphCoordinates": {"x": x, "y": y}, "blocks": blocos}
        self.d["groups"].append(g)
        self.G[g["id"]] = g
        for b in blocos:
            self.B[b["id"]] = b
        return g["id"]

    def codigo(self, variavel, js):
        return {"id": self.rid(), "type": "Set variable", "options": {
            "variableId": self.var(variavel), "expressionToEvaluate": js,
            "isCode": True, "type": "Custom"}}

    def texto(self, texto):
        return {"id": self.rid(), "type": "text", "content": {"richText": [
            {"id": self.rid()[:10], "type": "p", "children": [{"text": texto}]}]}}

    def condicao(self, casos, senao_grupo=None):
        """casos: [(variavel, operador, valor, grupo_destino)]"""
        b = {"id": self.rid(), "type": "Condition", "items": []}
        for variavel, op, valor, destino in casos:
            item = {"id": self.rid(), "content": {"logicalOperator": "AND", "comparisons": [
                {"id": self.rid(), "variableId": self.var(variavel),
                 "comparisonOperator": op, "value": valor}]}}
            item["outgoingEdgeId"] = self.edge(b["id"], destino, item["id"])
            b["items"].append(item)
        if senao_grupo:
            b["outgoingEdgeId"] = self.edge(b["id"], senao_grupo)
        return b

    def prepend(self, grupo_id, blocos):
        self.G[grupo_id]["blocks"][0:0] = blocos
        for b in blocos:
            self.B[b["id"]] = b
        for e in self.d["edges"]:
            if e["to"].get("groupId") == grupo_id:
                e["to"].pop("blockId", None)

    def filtro(self, bloco_id, comparacoes):
        self.B[bloco_id]["options"]["filter"] = {
            "logicalOperator": "AND",
            "comparisons": [{"id": self.rid(), "column": c, "comparisonOperator": op,
                             "value": v} for c, op, v in comparacoes]}

    def coords(self, grupo_id):
        c = self.G[grupo_id]["graphCoordinates"]
        return c["x"], c["y"]

    # --------------------------------------------------------------
    def resolvedor_bairro(self, titulo, ancora, ok, nao_encontrado):
        """Cria os grupos que reconhecem o bairro. Retorna o grupo de entrada."""
        x, y = self.coords(ancora)

        # Escolha entre bairros parecidos
        botoes = {"id": self.rid(), "type": "choice input",
                  "items": [{"id": self.rid(), "content": "(opções do bairro)"}],
                  "options": {"isMultipleChoice": False,
                              "dynamicVariableId": self.var("bairro_opcoes"),
                              "variableId": self.var("bairro_escolhido")}}
        escolhido = self.grupo(f"{titulo}: bairro escolhido", x + 700, y + 700, [
            self.codigo("bairro_nome",
                        f'const e = {{{{bairro_escolhido}}}};\nreturn e === {json.dumps(NENHUM)} ? "" : e;'),
            self.codigo("bairro_busca", JS_NORMALIZACAO +
                        f'\nconst e = {{{{bairro_escolhido}}}};\nreturn e === {json.dumps(NENHUM)} ? "-" : semAcento(e);'),
        ])
        self.G[escolhido]["blocks"].append(self.condicao(
            [("bairro_escolhido", "Equal to", NENHUM, nao_encontrado)], senao_grupo=ok))

        escolher = self.grupo(f"{titulo}: escolher bairro", x + 350, y + 700,
                              [self.texto("{{bairro_pergunta}}"), botoes])
        botoes["outgoingEdgeId"] = self.edge(botoes["id"], escolhido)

        sheets = {"id": self.rid(), "type": "Google Sheets", "options": {
            "credentialsId": self.credentials_id, "sheetId": GID_BAIRROS,
            "spreadsheetId": self.spreadsheet_id, "action": "Get data from sheet",
            "filter": {"logicalOperator": "AND", "comparisons": [
                {"id": self.rid(), "column": "municipio", "comparisonOperator": "Equal to",
                 "value": "{{municipio_busca}}"}]},
            "cellsToExtract": [
                {"id": self.rid(), "column": col, "variableId": self.var(var)}
                for col, var in [("bairro", "lista_bairros"), ("busca_bairro", "lista_chaves"),
                                 ("variantes", "lista_variantes"), ("unidades", "lista_unidades")]],
            "totalRowsToExtract": "All"}}
        campo = lambda nome: f"return JSON.parse({{{{bairro_resolucao}}}}).{nome};"
        blocos = [
            sheets,
            self.codigo("bairro_resolucao", JS_RESOLVER_BAIRRO),
            self.codigo("bairro_status", campo("status")),
            self.codigo("bairro_busca", campo("busca")),
            self.codigo("bairro_nome", campo("nome")),
            self.codigo("bairro_opcoes", campo("opcoes")),
            self.codigo("bairro_pergunta", campo("pergunta")),
        ]
        entrada = self.grupo(f"{titulo}: reconhecer bairro", x, y + 700, blocos)
        self.G[entrada]["blocks"].append(self.condicao([
            ("bairro_status", "Equal to", "ok", ok),
            ("bairro_status", "Equal to", "nao_encontrado", nao_encontrado),
        ], senao_grupo=escolher))
        return entrada


def gerar(d):
    f = Fluxo(d)
    MUN = ("municipio", "Equal to", "{{municipio_busca}}")

    # Município do bot
    f.prepend(G_INICIO, [f.codigo("municipio_busca", f"return {json.dumps(MUNICIPIO_PADRAO)};")])

    # --- Encontrar posto (só SUS) ---------------------------------
    resolver_posto = f.resolvedor_bairro("Posto", G_INPUT_BAIRRO_POSTO,
                                         ok=G_SHEETS_POSTO, nao_encontrado=G_BAIRRO_SEM_INFO)
    f.E[E_INPUT_BAIRRO_POSTO]["to"] = {"groupId": resolver_posto}
    f.filtro(B_SHEETS_POSTO, [("busca_bairro", "Equal to", "{{bairro_busca}}"),
                              ("filtro_sus", "Contains", "sus"), MUN])

    # --- Especialidade + bairro + pergunta SUS --------------------
    x, y = f.coords(G_SHEETS_ESP)
    botoes_sus = {"id": f.rid(), "type": "choice input", "items": [],
                  "options": {"isMultipleChoice": False, "variableId": f.var("resposta_sus")}}
    for rotulo in ["✅ Sim, só pelo SUS", "Não, mostrar todas"]:
        item = {"id": f.rid(), "content": rotulo}
        item["outgoingEdgeId"] = f.edge(botoes_sus["id"], G_SHEETS_ESP, item["id"])
        botoes_sus["items"].append(item)
    pergunta_sus = f.grupo("Pergunta SUS", x - 200, y + 350, [
        f.texto("Você quer ver só unidades que atendem pelo SUS?"), botoes_sus])

    # bairro não reconhecido: segue mesmo assim; a busca no bairro volta vazia
    # e o fluxo já existente procura a especialidade sem bairro.
    resolver_esp = f.resolvedor_bairro("Especialidade", G_INPUT_BAIRRO_ESP,
                                       ok=pergunta_sus, nao_encontrado=pergunta_sus)
    f.E[E_INPUT_BAIRRO_ESP]["to"] = {"groupId": resolver_esp}

    f.prepend(G_SHEETS_ESP, [
        f.codigo("filtro_sus", 'const r = String({{resposta_sus}} ?? "");\n'
                               'return r.includes("Sim") ? "sus" : "todos";'),
        f.codigo("especialidade_busca", JS_NORMALIZACAO + "\nreturn normalizarBusca({{especialidade}});"),
    ])
    f.filtro(B_SHEETS_ESP, [("busca_servicos", "Contains", "{{especialidade_busca}}"),
                            ("busca_bairro", "Equal to", "{{bairro_busca}}"),
                            ("filtro_sus", "Contains", "{{filtro_sus}}"), MUN])
    f.filtro(B_SHEETS_ESP_RESERVA, [("busca_servicos", "Contains", "{{especialidade_busca}}"),
                                    ("filtro_sus", "Contains", "{{filtro_sus}}"), MUN])

    # --- Especialidades de uma unidade ----------------------------
    f.prepend(G_SHEETS_UNIDADE, [
        f.codigo("unidade_busca", JS_NORMALIZACAO + "\nreturn normalizarBusca({{unidade}});")])
    f.filtro(B_SHEETS_UNIDADE, [("busca_nome", "Contains", "{{unidade_busca}}"), MUN])

    # --- Formatação e textos --------------------------------------
    for b in B_LISTAS:
        f.B[b]["options"]["expressionToEvaluate"] = JS_LISTA
    f.B[B_DETALHE]["options"]["expressionToEvaluate"] = JS_DETALHE_UNIDADE
    for b in B_TEXTOS_COM_BAIRRO:
        for p in f.B[b]["content"]["richText"]:
            for c in p["children"]:
                c["text"] = c["text"].replace("{{bairro}}", "{{bairro_nome}}")
    return d


if __name__ == "__main__":
    pasta = os.path.dirname(os.path.abspath(__file__))
    origem = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        pasta, "export-original", "typebot-export-my-typebot-p07wqpu.json")
    destino = sys.argv[2] if len(sys.argv) > 2 else os.path.join(pasta, "typebot-bem-te-vi.json")
    random.seed(42)  # IDs estáveis entre execuções
    fluxo = gerar(json.load(open(origem, encoding="utf-8")))
    json.dump(fluxo, open(destino, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"Fluxo gerado: {destino}")
