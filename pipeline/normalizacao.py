"""
Normalização de texto, sinônimos de termos e bairro oficial.

As MESMAS regras rodam no Typebot (o JavaScript é gerado a partir daqui por
typebot/gerar_typebot.py). Se mudar algo aqui, gere o fluxo de novo.

Arquivos editáveis (sem programar), em dados/:
  sinonimos_termos.csv   termo como aparece no CNES -> palavras que o usuário usa
  sinonimos_bairros.csv  grafia/variação -> bairro oficial
"""

import csv
import os
import re
import unicodedata

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PASTA_DADOS = os.path.join(RAIZ, "dados")
ARQ_TERMOS = os.path.join(PASTA_DADOS, "sinonimos_termos.csv")
ARQ_BAIRROS = os.path.join(PASTA_DADOS, "sinonimos_bairros.csv")

# Palavras ignoradas na busca ("quero um dentista" -> "dentista").
# Aplicadas dos dois lados (planilha e usuário), então não quebram termos
# como "saude da familia" (vira "saude familia" nos dois lados).
STOPWORDS = [
    "a", "o", "as", "os", "um", "uma", "uns", "umas", "de", "do", "da",
    "dos", "das", "e", "em", "no", "na", "nos", "nas", "para", "pra", "pro",
    "com", "por", "que", "quero", "queria", "preciso", "procuro", "gostaria",
    "meu", "minha", "bairro", "unidade",
]

# Algarismos romanos/números no fim do nome de bairro ("Cidade Nova II").
SUFIXO_BAIRRO = r"\s+(i{1,3}|iv|[1-4])$"


def sem_acento(texto):
    """Minúsculas, sem acento e sem espaços repetidos."""
    t = unicodedata.normalize("NFD", str(texto or ""))
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return " ".join(t.lower().split())


def _radical(palavra):
    # Plural simples: "exames"->"exame", "vacinacoes"->"vacinacao",
    # "hospitais"->"hospital". Igual dos dois lados, então é seguro.
    if len(palavra) > 4 and palavra.endswith("oes"):
        return palavra[:-3] + "ao"
    if len(palavra) > 4 and palavra.endswith("ais"):
        return palavra[:-3] + "al"
    if len(palavra) > 3 and palavra.endswith("s") and not palavra.endswith("ss"):
        return palavra[:-1]
    return palavra


def normalizar_busca(texto):
    """Forma usada nas colunas busca_* e no que o usuário digita."""
    t = re.sub(r"[^a-z0-9]+", " ", sem_acento(texto))
    palavras = [_radical(p) for p in t.split() if p not in STOPWORDS]
    return " ".join(palavras)


# ------------------------------------------------------------
# Sinônimos de termos (especialidades/serviços)
# ------------------------------------------------------------

def carregar_sinonimos_termos(caminho=ARQ_TERMOS):
    """[(termo_normalizado, "sinonimos normalizados")]"""
    regras = []
    if not os.path.exists(caminho):
        return regras
    with open(caminho, newline="", encoding="utf-8") as f:
        for linha in csv.DictReader(f):
            termo = normalizar_busca(linha.get("termo_no_cnes"))
            sinonimos = [
                normalizar_busca(s) for s in (linha.get("sinonimos") or "").split(";")
            ]
            sinonimos = [s for s in sinonimos if s]
            if termo and sinonimos:
                regras.append((termo, " ".join(sinonimos)))
    return regras


def texto_busca_servicos(nome, especialidades, tipo_unidade, regras):
    """Nome + especialidades + tipo + sinônimos dos termos encontrados."""
    base = normalizar_busca(f"{nome} {especialidades} {tipo_unidade}")
    extras = [sin for termo, sin in regras if termo in base]
    return " | ".join([base] + extras) if extras else base


# ------------------------------------------------------------
# Bairro oficial
# ------------------------------------------------------------

def carregar_sinonimos_bairros(caminho=ARQ_BAIRROS):
    """{(municipio_norm, variante_norm): bairro_oficial}"""
    mapa = {}
    if not os.path.exists(caminho):
        return mapa
    with open(caminho, newline="", encoding="utf-8") as f:
        for linha in csv.DictReader(f):
            municipio = sem_acento(linha.get("municipio") or "Manaus")
            variante = sem_acento(linha.get("variante"))
            if variante:
                mapa[(municipio, variante)] = (linha.get("bairro") or "").strip()
    return mapa


def tirar_sufixo(bairro_norm):
    return re.sub(SUFIXO_BAIRRO, "", bairro_norm)


class ResolvedorBairros:
    """Converte o bairro do CNES no bairro oficial (nome para exibir)."""

    def __init__(self, nomes_cnes_por_municipio, sinonimos=None):
        self.sin = sinonimos if sinonimos is not None else carregar_sinonimos_bairros()
        # Bairros "conhecidos": os que aparecem no CNES + destinos dos sinônimos
        self.conhecidos = {}
        for municipio, nomes in nomes_cnes_por_municipio.items():
            m = sem_acento(municipio)
            self.conhecidos.setdefault(m, set()).update(sem_acento(n) for n in nomes)
        for (m, _), oficial in self.sin.items():
            if oficial:
                self.conhecidos.setdefault(m, set()).add(sem_acento(oficial))

    def oficial(self, municipio, bairro_cnes):
        m, b = sem_acento(municipio), sem_acento(bairro_cnes)
        if not b:
            return ""
        if (m, b) in self.sin:
            return self.sin[(m, b)]
        base = tirar_sufixo(b)
        # Só remove o "II" se o que sobra também é um bairro
        # ("Cidade Nova II" -> "Cidade Nova", mas "Parque 10" fica).
        if base != b and base in self.conhecidos.get(m, set()):
            if (m, base) in self.sin:
                return self.sin[(m, base)]
            return base.title()
        return str(bairro_cnes).strip()
