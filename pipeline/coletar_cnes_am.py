"""
Coleta de estabelecimentos de saúde do Amazonas nos Web Services SOAP do CNES.

Reconstruído a partir de documentacao_mvp_bem-te-vi.md e
documentacao_integracao.md, mantendo o formato que está em produção:

    cnes,nome,endereco,telefone,especialidades

- endereco:       "RUA X, 123 - Bairro - Município/UF - CEP 69000-000"
- telefone:       "(92) 31824547" (vários separados por "; ")
- especialidades: separadas por " | " (o Typebot faz split("|"))

Colunas extras são acrescentadas no FINAL (não quebram o Typebot, que lê por
nome de coluna): municipio, bairro, tipo_unidade, data_atualizacao_cnes.

Uso isolado (gera só o CSV):
    python -m pipeline.coletar_cnes_am
    python -m pipeline.coletar_cnes_am --limite 20      # teste rápido
"""

import argparse
import csv
import logging
import os
import re
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from lxml import etree

from pipeline import normalizacao

try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(normalizacao.RAIZ, ".env"))
except ImportError:  # python-dotenv é opcional
    pass

log = logging.getLogger("bemtevi.coleta")

# ------------------------------------------------------------
# CONFIGURAÇÕES (todas sobrescrevíveis por variável de ambiente)
# ------------------------------------------------------------

USUARIO = os.getenv("CNES_USUARIO", "CNES.PUBLICO")
SENHA = os.getenv("CNES_SENHA", "")

URL_CNES = os.getenv(
    "CNES_URL_MUNICIPIO",
    "https://servicoshm.saude.gov.br/cnes/CnesService/v1r0",
)
URL_ESTAB = os.getenv(
    "CNES_URL_ESTABELECIMENTO",
    "https://servicoshm.saude.gov.br/cnes/EstabelecimentoSaudeService/v1r0",
)

ARQUIVO_MUNICIPIOS = os.getenv(
    "ARQUIVO_MUNICIPIOS",
    os.path.join(normalizacao.PASTA_DADOS, "municipios_am.csv"),
)
ARQUIVO_SAIDA = os.getenv(
    "ARQUIVO_SAIDA",
    os.path.join(normalizacao.RAIZ, "saida", "resultado_ubs_am.csv"),
)

# Requisições de detalhe em paralelo. Mantenha baixo para não sobrecarregar
# o serviço do Ministério da Saúde.
WORKERS = int(os.getenv("CNES_WORKERS", "4"))
TIMEOUT = int(os.getenv("CNES_TIMEOUT", "90"))
TENTATIVAS = int(os.getenv("CNES_TENTATIVAS", "4"))

# Filtro opcional por tipo de unidade (códigos do CNES separados por vírgula).
# Ex.: "01,02" = posto de saúde + centro de saúde/unidade básica.
# Vazio = todos os estabelecimentos (comportamento do MVP em produção).
TIPOS_UNIDADE = {
    t.strip().zfill(2)
    for t in os.getenv("CNES_TIPOS_UNIDADE", "").split(",")
    if t.strip()
}

CAMPOS = [
    # Colunas originais, na mesma ordem da planilha em produção
    "cnes",
    "nome",
    "endereco",
    "telefone",
    "especialidades",
    # Colunas novas (no final)
    "municipio",
    "bairro",
    "tipo_unidade",
    "data_atualizacao_cnes",
    "atende_sus",
    "bairro_oficial",
    # Colunas técnicas para o Typebot filtrar (ver normalizacao.py).
    # "filtro_sus" vale "todos sus" (atende SUS) ou "todos" (não atende),
    # então o filtro "contém sus" traz só SUS e "contém todos" traz tudo.
    "filtro_sus",
    "busca_nome",
    "busca_endereco",
    "busca_especialidades",
    "busca_servicos",
    "busca_bairro",
]


def normalizar(texto):
    """Mantido por compatibilidade; ver normalizacao.sem_acento."""
    return normalizacao.sem_acento(texto)


def enriquecer(registros):
    """Preenche bairro_oficial, filtro_sus e as colunas busca_* de todas as
    linhas. Precisa ver a base inteira para decidir o bairro oficial
    ("Cidade Nova II" só vira "Cidade Nova" se "Cidade Nova" existe)."""
    nomes = defaultdict(set)
    for reg in registros:
        nomes[reg.get("municipio", "")].add(reg.get("bairro", ""))
    resolvedor = normalizacao.ResolvedorBairros(nomes)
    regras = normalizacao.carregar_sinonimos_termos()

    for reg in registros:
        sus = str(reg.get("atende_sus", "")).strip().lower()
        reg["filtro_sus"] = "todos sus" if sus == "sim" else "todos"
        reg["bairro_oficial"] = resolvedor.oficial(
            reg.get("municipio", ""), reg.get("bairro", "")
        )
        reg["busca_bairro"] = normalizacao.sem_acento(reg["bairro_oficial"])
        reg["busca_nome"] = normalizacao.normalizar_busca(reg.get("nome"))
        reg["busca_endereco"] = normalizacao.sem_acento(reg.get("endereco"))
        reg["busca_especialidades"] = normalizacao.normalizar_busca(
            reg.get("especialidades")
        )
        reg["busca_servicos"] = normalizacao.texto_busca_servicos(
            reg.get("nome", ""), reg.get("especialidades", ""),
            reg.get("tipo_unidade", ""), regras,
        )
    return registros


def montar_bairros(registros):
    """Linhas da aba 'bairros', usada pelo Typebot para reconhecer o bairro
    digitado e oferecer opções quando houver mais de um parecido."""
    agrupado = {}
    for reg in registros:
        oficial = reg.get("bairro_oficial", "")
        if not oficial:
            continue
        chave = (reg.get("municipio", ""), oficial)
        item = agrupado.setdefault(chave, {"variantes": set(), "unidades": 0})
        item["unidades"] += 1
        item["variantes"].add(normalizacao.sem_acento(reg.get("bairro", "")))
    # sinônimos populares (ex.: Japiinlândia -> Japiim) também viram variantes
    for (municipio_norm, variante), oficial in normalizacao.carregar_sinonimos_bairros().items():
        for (municipio, of), item in agrupado.items():
            if of == oficial and normalizacao.sem_acento(municipio) == municipio_norm:
                item["variantes"].add(variante)

    linhas = []
    for (municipio, oficial), item in sorted(agrupado.items()):
        chave = normalizacao.sem_acento(oficial)
        variantes = sorted(v for v in item["variantes"] if v and v != chave)
        linhas.append({
            "municipio": municipio,
            "bairro": oficial,
            "busca_bairro": chave,
            "variantes": " | ".join(variantes),
            "unidades": item["unidades"],
        })
    return linhas


CAMPOS_BAIRROS = ["municipio", "bairro", "busca_bairro", "variantes", "unidades"]


HEADERS = {
    "Content-Type": "application/soap+xml; charset=utf-8",
    "Accept": "application/soap+xml, application/xml, text/xml",
}

SOAP_NS = "http://www.w3.org/2003/05/soap-envelope"
WSSE_NS = (
    "http://docs.oasis-open.org/wss/2004/01/"
    "oasis-200401-wss-wssecurity-secext-1.0.xsd"
)

_sessao_local = threading.local()


def _sessao():
    # requests.Session não é thread-safe: uma por thread.
    if not hasattr(_sessao_local, "s"):
        _sessao_local.s = requests.Session()
        _sessao_local.s.headers.update(HEADERS)
    return _sessao_local.s


# ------------------------------------------------------------
# SOAP
# ------------------------------------------------------------

def soap_header():
    return f"""
    <soap:Header>
        <wsse:Security xmlns:wsse="{WSSE_NS}">
            <wsse:UsernameToken>
                <wsse:Username>{USUARIO}</wsse:Username>
                <wsse:Password>{SENHA}</wsse:Password>
            </wsse:UsernameToken>
        </wsse:Security>
    </soap:Header>
    """


class SoapFault(RuntimeError):
    """Erro de negócio devolvido pelo serviço (não adianta repetir)."""


def enviar_soap(url, xml):
    """POST com retentativa e espera progressiva para falhas temporárias."""
    ultimo_erro = None

    for tentativa in range(1, TENTATIVAS + 1):
        try:
            resposta = _sessao().post(
                url, data=xml.encode("utf-8"), timeout=TIMEOUT
            )

            # O serviço pode devolver Fault com HTTP 500; tenta interpretar
            # o corpo antes de tratar como erro HTTP.
            try:
                raiz = etree.fromstring(resposta.content)
            except etree.XMLSyntaxError:
                resposta.raise_for_status()
                raise

            faults = raiz.xpath("//*[local-name()='Fault']")
            if faults:
                mensagem = " ".join(" ".join(faults[0].itertext()).split())
                raise SoapFault(mensagem)

            resposta.raise_for_status()
            return raiz

        except SoapFault:
            raise
        except (requests.RequestException, etree.XMLSyntaxError) as erro:
            ultimo_erro = erro
            if tentativa < TENTATIVAS:
                espera = 2 ** tentativa
                log.warning(
                    "Falha temporária (%s/%s), nova tentativa em %ss: %s",
                    tentativa, TENTATIVAS, espera, erro,
                )
                time.sleep(espera)

    raise RuntimeError(f"Falhou após {TENTATIVAS} tentativas: {ultimo_erro}")


def consultar_cnes_municipio(codigo):
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
    <soap:Envelope
        xmlns:soap="{SOAP_NS}"
        xmlns:cnes="http://servicos.saude.gov.br/cnes/v1r0/cnesservice"
        xmlns:mun="http://servicos.saude.gov.br/schema/corporativo/v1r2/municipio">
        {soap_header()}
        <soap:Body>
            <cnes:requestConsultarEstabelecimentoSaudePorMunicipio>
                <mun:Municipio>
                    <mun:codigoMunicipio>{codigo}</mun:codigoMunicipio>
                </mun:Municipio>
            </cnes:requestConsultarEstabelecimentoSaudePorMunicipio>
        </soap:Body>
    </soap:Envelope>
    """
    return enviar_soap(URL_CNES, xml)


def consultar_estabelecimento(cnes):
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
    <soap:Envelope
        xmlns:soap="{SOAP_NS}"
        xmlns:est="http://servicos.saude.gov.br/cnes/v1r0/estabelecimentosaudeservice"
        xmlns:fil="http://servicos.saude.gov.br/wsdl/mensageria/v1r0/filtropesquisaestabelecimentosaude"
        xmlns:cod="http://servicos.saude.gov.br/schema/cnes/v1r0/codigocnes">
        {soap_header()}
        <soap:Body>
            <est:requestConsultarEstabelecimentoSaude>
                <fil:FiltroPesquisaEstabelecimentoSaude>
                    <cod:CodigoCNES>
                        <cod:codigo>{cnes}</cod:codigo>
                    </cod:CodigoCNES>
                </fil:FiltroPesquisaEstabelecimentoSaude>
            </est:requestConsultarEstabelecimentoSaude>
        </soap:Body>
    </soap:Envelope>
    """
    return enviar_soap(URL_ESTAB, xml)


# ------------------------------------------------------------
# EXTRAÇÃO
# ------------------------------------------------------------

def _texto(elemento):
    return " ".join("".join(elemento.itertext()).split())


def primeiro_texto(xml, xpath):
    elementos = xml.xpath(xpath)
    return _texto(elementos[0]) if elementos else ""


def texto_filho(elemento, nome):
    return primeiro_texto(elemento, f"./*[local-name()='{nome}']")


def _titulo(texto):
    # "PRACA 14 DE JANEIRO" -> "Praca 14 De Janeiro" (formato em produção)
    return texto.title() if texto else ""


def _formatar_cep(cep):
    digitos = re.sub(r"\D", "", cep)
    return f"{digitos[:5]}-{digitos[5:]}" if len(digitos) == 8 else cep


def extrair_endereco(xml):
    """
    Monta: "RUA DUQUE DE CAXIAS, 1142 - Praca 14 De Janeiro - Manaus/AM - CEP 69020-140"
    Também devolve bairro e município separados para as colunas novas.
    """
    enderecos = xml.xpath("//*[local-name()='Endereco']")
    if not enderecos:
        return "", "", ""

    end = enderecos[0]

    logradouro = texto_filho(end, "nomeLogradouro")
    numero = texto_filho(end, "numero")
    bairro = _titulo(primeiro_texto(
        end, "./*[local-name()='Bairro']/*[local-name()='descricaoBairro']"
    ))
    cep = _formatar_cep(primeiro_texto(
        end, "./*[local-name()='CEP']/*[local-name()='numeroCEP']"
    ))
    municipio = _titulo(primeiro_texto(
        end, "./*[local-name()='Municipio']/*[local-name()='nomeMunicipio']"
    ))
    uf = primeiro_texto(
        end, "./*[local-name()='Municipio']//*[local-name()='siglaUF']"
    )

    linha = logradouro
    if numero:
        linha = f"{linha}, {numero}" if linha else numero

    cidade = "/".join(p for p in [municipio, uf] if p)

    partes = [p for p in [linha, bairro, cidade] if p]
    if cep:
        partes.append(f"CEP {cep}")

    return " - ".join(partes), bairro, municipio


def extrair_telefones(xml):
    telefones = []
    for tel in xml.xpath("//*[local-name()='Telefone']"):
        ddd = texto_filho(tel, "DDD")
        numero = texto_filho(tel, "numeroTelefone")
        if numero:
            valor = f"({ddd}) {numero}" if ddd else numero
            if valor not in telefones:
                telefones.append(valor)
    return "; ".join(telefones)


def extrair_especialidades(xml):
    especialidades = []
    for desc in xml.xpath(
        "//*[local-name()='servicoclassificacao']/*[local-name()='descricao']"
    ):
        valor = _texto(desc)
        if valor and valor not in especialidades:
            especialidades.append(valor)
    # Ordem alfabética: o CNES devolve a lista em ordem variável a cada chamada
    return " | ".join(sorted(especialidades))


def extrair(xml):
    dados = xml.xpath("//*[local-name()='DadosGeraisEstabelecimentoSaude']")
    if not dados:
        raise ValueError("resposta sem DadosGeraisEstabelecimentoSaude")
    d = dados[0]

    endereco, bairro, municipio = extrair_endereco(d)

    return {
        "cnes": primeiro_texto(
            d, "./*[local-name()='CodigoCNES']/*[local-name()='codigo']"
        ),
        "nome": primeiro_texto(d, "./*[local-name()='nomeFantasia']"),
        "endereco": endereco,
        "telefone": extrair_telefones(d),
        "especialidades": extrair_especialidades(d),
        "municipio": municipio,
        "bairro": bairro,
        "tipo_unidade": primeiro_texto(
            d, "./*[local-name()='tipoUnidade']/*[local-name()='descricao']"
        ),
        "_tipo_codigo": primeiro_texto(
            d, "./*[local-name()='tipoUnidade']/*[local-name()='codigo']"
        ),
        "data_atualizacao_cnes": primeiro_texto(
            d, "./*[local-name()='dataAtualizacao']"
        ),
        "atende_sus": (
            "sim"
            if primeiro_texto(d, "./*[local-name()='perteceSistemaSUS']")
            .lower() == "true"
            else "nao"
        ),
    }


# ------------------------------------------------------------
# ORQUESTRAÇÃO
# ------------------------------------------------------------

def ler_municipios(caminho=ARQUIVO_MUNICIPIOS):
    """Aceita coluna codigo_municipio (6 dígitos) ou codigo_ibge (7 dígitos).

    O 7º dígito do código IBGE é dígito verificador; o serviço do CNES usa
    os 6 primeiros (validado: Manaus 1302603 -> 130260).
    """
    with open(caminho, newline="", encoding="utf-8-sig") as f:
        leitor = csv.DictReader(f)
        campos = leitor.fieldnames or []
        if "codigo_municipio" not in campos and "codigo_ibge" not in campos:
            raise ValueError(
                f"{caminho} precisa de uma coluna codigo_municipio ou codigo_ibge"
            )
        municipios = []
        for linha in leitor:
            codigo = (
                linha.get("codigo_municipio") or linha.get("codigo_ibge") or ""
            ).strip()
            if codigo:
                municipios.append((codigo[:6], (linha.get("nome") or "").strip()))
        return municipios


def listar_cnes(municipios):
    """Retorna (lista de CNES únicos, lista de municípios que falharam)."""
    todos, vistos, falhas = [], set(), []
    for codigo, nome in municipios:
        try:
            resp = consultar_cnes_municipio(codigo)
            codigos = resp.xpath(
                "//*[local-name()='CodigoCNES']/*[local-name()='codigo']/text()"
            )
            novos = [c.strip() for c in codigos if c.strip() not in vistos]
            vistos.update(novos)
            todos.extend(novos)
            log.info("Município %s %s: %d CNES", codigo, nome, len(codigos))
        except Exception as erro:  # noqa: BLE001
            log.error("Falha no município %s %s: %s", codigo, nome, erro)
            falhas.append(codigo)
    return todos, falhas


def coletar(limite=0, municipios=None):
    """
    Executa a coleta completa.

    Retorna dict com:
      registros:          lista de dicts (colunas CAMPOS)
      cnes_com_erro:      CNES cuja consulta de detalhe falhou
      municipios_com_erro
      total_cnes
    """
    if TIPOS_UNIDADE:
        log.info("Filtrando tipos de unidade: %s", sorted(TIPOS_UNIDADE))

    municipios = municipios or ler_municipios()
    log.info("Municípios a consultar: %d", len(municipios))

    lista_cnes, municipios_com_erro = listar_cnes(municipios)
    if limite:
        lista_cnes = lista_cnes[:limite]
    log.info("Estabelecimentos a detalhar: %d", len(lista_cnes))

    registros, cnes_com_erro = [], []
    feitos = 0

    def tarefa(cnes):
        info = extrair(consultar_estabelecimento(cnes))
        info["cnes"] = info["cnes"] or cnes
        return info

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futuros = {pool.submit(tarefa, c): c for c in lista_cnes}
        for futuro in as_completed(futuros):
            cnes = futuros[futuro]
            feitos += 1
            try:
                info = futuro.result()
                tipo = info.pop("_tipo_codigo", "")
                if not TIPOS_UNIDADE or tipo.zfill(2) in TIPOS_UNIDADE:
                    registros.append(info)
            except Exception as erro:  # noqa: BLE001
                log.error("Erro no CNES %s: %s", cnes, erro)
                cnes_com_erro.append(cnes)
            if feitos % 200 == 0 or feitos == len(lista_cnes):
                log.info("Progresso: %d/%d", feitos, len(lista_cnes))

    enriquecer(registros)

    # Ordem estável (município, nome) para a planilha não "embaralhar"
    registros.sort(key=lambda r: (r["municipio"], r["nome"], r["cnes"]))

    return {
        "registros": registros,
        "cnes_com_erro": cnes_com_erro,
        "municipios_com_erro": municipios_com_erro,
        "total_cnes": len(lista_cnes),
    }


def salvar_csv(registros, caminho=ARQUIVO_SAIDA):
    os.makedirs(os.path.dirname(os.path.abspath(caminho)), exist_ok=True)
    with open(caminho, "w", newline="", encoding="utf-8-sig") as f:
        escritor = csv.DictWriter(f, fieldnames=CAMPOS, extrasaction="ignore")
        escritor.writeheader()
        escritor.writerows(registros)


def configurar_log():
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(message)s",
    )


def validar_credenciais():
    if not SENHA:
        raise SystemExit(
            "Defina CNES_SENHA (no .env ou como variável de ambiente)."
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("--limite", type=int, default=0,
                        help="máximo de estabelecimentos (0 = todos)")
    parser.add_argument("--saida", default=ARQUIVO_SAIDA)
    args = parser.parse_args()

    configurar_log()
    validar_credenciais()
    resultado = coletar(limite=args.limite)
    salvar_csv(resultado["registros"], args.saida)
    log.info(
        "Registros salvos: %d | erros de CNES: %d | municípios com erro: %d | arquivo: %s",
        len(resultado["registros"]),
        len(resultado["cnes_com_erro"]),
        len(resultado["municipios_com_erro"]),
        args.saida,
    )
