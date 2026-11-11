"""
Simula conversas no fluxo do Typebot, sem publicar nada.

Funciona com os dois fluxos:
  - typebot-bem-te-vi-supabase.json: as chamadas HTTP às funções do Supabase
    são executadas num Postgres local (SIMULADOR_DB_URL), como papel "anon";
  - typebot-bem-te-vi.json (planilha): filtros aplicados sobre .cache/base.csv.

Percorre grupos/blocos/edges como o Typebot, executa o JavaScript dos blocos
"Set variable" no node e aplica os filtros dos blocos Google Sheets sobre um
CSV local (mesma lógica do Typebot: "Contains" ignora maiúsculas e é falso
com valor vazio; "Equal to" é exato).

Uso:
    python typebot/simular_bot.py "Encontrar um posto" "nova" "Cidade Nova"
    SIMULADOR_FLUXO=planilha python typebot/simular_bot.py ...

(usa typebot/typebot-bem-te-vi.json e .cache/base.csv; gere a base com
 python -m pipeline.coletar_cnes_am --saida .cache/base.csv)
"""

import csv
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pipeline import coletar_cnes_am as coleta  # noqa: E402
from pipeline.normalizacao import RAIZ  # noqa: E402

FIM = "r9oyq7gp7ns3j7wdmnp4r729"  # "Essa resposta te ajudou?"


class Simulador:
    def __init__(self, fluxo, base_csv=None, db_url=None):
        self.d = json.load(open(fluxo, encoding="utf-8"))
        self.db_url = db_url
        self.G = {g["id"]: g for g in self.d["groups"]}
        self.E = {e["id"]: e for e in self.d["edges"]}
        self.V = {v["id"]: v["name"] for v in self.d["variables"]}
        self.abas = {}
        if base_csv:
            linhas = list(csv.DictReader(open(base_csv, encoding="utf-8-sig")))
            coleta.enriquecer(linhas)
            self.abas = {"0": linhas, "7001": coleta.montar_bairros(linhas)}

    def http(self, b, vars_):
        """Executa uma chamada /rest/v1/rpc/<funcao> no Postgres local, como o PostgREST."""
        import psycopg
        w = b["options"]["webhook"]
        m = re.search(r"/rest/v1/rpc/(\w+)$", w["url"])
        if not m:
            return  # outros webhooks (ex.: tabela interacoes) não são simulados
        def no_json(mt):  # mesma regra do Typebot para variáveis dentro de JSON
            v = vars_.get(mt.group(1))
            return json.dumps("" if v is None else v)[1:-1] if not isinstance(v, (list, dict)) else json.dumps(v)
        args = json.loads(re.sub(r"\{\{(\w+)\}\}", no_json, w["body"]))
        sql = f"select public.{m.group(1)}(" + ", ".join(f"{k} => %s" for k in args) + ")"
        try:
            with psycopg.connect(self.db_url) as conn:
                conn.execute("set role anon")
                data, status = conn.execute(sql, list(args.values())).fetchone()[0], 200
        except Exception as erro:  # noqa: BLE001
            data, status = {"message": str(erro)}, 500
        for mp in b["options"].get("responseVariableMapping", []):
            vars_[self.V[mp["variableId"]]] = self.js(
                f"const statusCode = {status}; const data = {json.dumps(data)}; return ({mp['bodyPath']});", {})

    def js(self, codigo, vars_):
        corpo = re.sub(r"\{\{(\w+)\}\}", lambda m: json.dumps(vars_.get(m.group(1))), codigo)
        r = subprocess.run(["node", "-e", f"console.log(JSON.stringify((()=>{{{corpo}}})()))"],
                           capture_output=True, text=True)
        if r.returncode:
            raise RuntimeError(r.stderr)
        return json.loads(r.stdout)

    @staticmethod
    def subst(texto, vars_):
        def valor(m):
            v = vars_.get(m.group(1))
            return ", ".join(map(str, v)) if isinstance(v, list) else ("" if v is None else str(v))
        return re.sub(r"\{\{(\w+)\}\}", valor, texto)

    @staticmethod
    def compara(celula, op, valor):
        celula, valor = str(celula or ""), str(valor or "")
        if op == "Contains":
            return bool(celula.strip()) and bool(valor.strip()) and \
                valor.lower().strip() in celula.lower().strip()
        if op == "Equal to":
            return celula == valor
        if op == "Is empty":
            return not celula
        raise ValueError(op)

    def sheets(self, b, vars_):
        o = b["options"]
        linhas = self.abas[o["sheetId"]]
        comps = (o.get("filter") or {}).get("comparisons", [])
        for c in comps:
            assert c["column"] in linhas[0], f"coluna inexistente: {c['column']}"
        achados = [r for r in linhas if all(
            self.compara(r[c["column"]], c["comparisonOperator"], self.subst(c["value"], vars_))
            for c in comps)]
        if o.get("totalRowsToExtract") == "First":
            achados = achados[:1]
        for cx in o["cellsToExtract"]:
            vals = [r[cx["column"]] for r in achados]
            vars_[self.V[cx["variableId"]]] = vals[0] if len(vals) == 1 else (vals or None)

    def condicao(self, b, vars_):
        for item in b["items"]:
            comps = (item.get("content") or {}).get("comparisons", [])
            if not comps:
                continue
            ok = []
            for c in comps:
                v = vars_.get(self.V[c["variableId"]])
                if c["comparisonOperator"] == "Is empty":
                    ok.append(v is None or v == "" or v == [])
                else:
                    ok.append(self.compara(v, c["comparisonOperator"], self.subst(c.get("value", ""), vars_)))
            if (all(ok) if item["content"].get("logicalOperator", "AND") == "AND" else any(ok)):
                return item.get("outgoingEdgeId")
        return b.get("outgoingEdgeId")

    def conversar(self, respostas, mostrar=True):
        vars_, respostas, falas = {}, list(respostas), []
        inicio = self.E[self.d["events"][0]["outgoingEdgeId"]]["to"]["groupId"]
        grupo, passos = inicio, 0
        while grupo and grupo != FIM and passos < 200:
            proximo = None
            for b in self.G[grupo]["blocks"]:
                passos += 1
                t = b["type"]
                if t == "text":
                    falas.append("🤖 " + "\n   ".join(
                        self.subst("".join(c["text"] for c in p["children"]), vars_)
                        for p in b["content"]["richText"]))
                elif t == "text input":
                    if not respostas:
                        grupo = None
                        break
                    r = respostas.pop(0)
                    falas.append(f"👤 {r}")
                    vars_[self.V[b["options"]["variableId"]]] = r
                elif t == "choice input":
                    o = b.get("options") or {}
                    if o.get("dynamicVariableId"):
                        itens = vars_.get(self.V[o["dynamicVariableId"]]) or []
                    else:
                        itens = [i["content"] for i in b["items"]]
                    falas.append("   [botões] " + " / ".join(itens))
                    if not respostas:
                        proximo = None
                        grupo = None
                        break
                    r = respostas.pop(0)
                    escolha = next((i for i in itens if i.startswith(r)), None)
                    assert escolha, f"'{r}' não está entre {itens}"
                    falas.append(f"👤 {escolha}")
                    if o.get("variableId"):
                        vars_[self.V[o["variableId"]]] = escolha
                    item = next((i for i in b["items"] if i["content"] == escolha), None)
                    proximo = (item or {}).get("outgoingEdgeId") or b.get("outgoingEdgeId")
                elif t == "Set variable":
                    o = b["options"]
                    vars_[self.V[o["variableId"]]] = self.js(o["expressionToEvaluate"], vars_)
                elif t == "Google Sheets":
                    self.sheets(b, vars_)
                elif t == "Condition":
                    proximo = self.condicao(b, vars_)
                elif t == "Webhook":
                    self.http(b, vars_)
                else:
                    raise ValueError(t)
                if proximo is None and b.get("outgoingEdgeId") and t not in ("Condition", "choice input"):
                    proximo = b["outgoingEdgeId"]
                if proximo:
                    break
            if grupo is None:
                break
            grupo = self.E[proximo]["to"]["groupId"] if proximo else None
        if mostrar:
            print("\n".join(falas))
        return vars_, falas


if __name__ == "__main__":
    if os.getenv("SIMULADOR_FLUXO") == "planilha":
        s = Simulador(os.path.join(RAIZ, "typebot", "typebot-bem-te-vi.json"),
                      base_csv=os.path.join(RAIZ, ".cache", "base.csv"))
    else:
        s = Simulador(os.path.join(RAIZ, "typebot", "typebot-bem-te-vi-supabase.json"),
                      db_url=os.getenv("SIMULADOR_DB_URL", "postgresql://postgres@localhost:54329/bemtevi"))
    s.conversar(sys.argv[1:])
