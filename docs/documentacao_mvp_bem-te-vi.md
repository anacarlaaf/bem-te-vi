# Documentação técnica --- MVP de consulta a estabelecimentos de saúde do Amazonas via CNES

> **Escopo:** documentar o protótipo em Python que consulta o ambiente
> de homologação dos Web Services do Cadastro Nacional de
> Estabelecimentos de Saúde (CNES), recupera códigos CNES por município,
> consulta os detalhes dos estabelecimentos e consolida os dados em CSV.
>
> **Importante:** o fluxo descrito consulta estabelecimentos cadastrados
> no CNES. A menos que seja acrescentado um filtro específico pelo tipo
> de unidade, o resultado **não é necessariamente composto apenas por
> UBS**. O protótipo também não consulta horário de funcionamento.

## 1. Objetivo do MVP

Construir uma primeira etapa de integração para alimentar um futuro
chatbot com informações cadastrais de unidades de saúde do Amazonas.

O processo automatiza quatro atividades:

1.  Ler os códigos dos municípios a partir de `municipios_am.csv`.
2.  Consultar o serviço CNES para obter os códigos CNES dos
    estabelecimentos de cada município.
3.  Consultar individualmente cada estabelecimento para recuperar seus
    dados cadastrais e serviços especializados.
4.  Extrair e organizar os campos relevantes em `resultado_ubs_am.csv`.

O CSV gerado é uma primeira base estruturada para posterior indexação,
busca ou integração com a camada conversacional do chatbot.

## 2. Tecnologias utilizadas

  -----------------------------------------------------------------------
  Tecnologia                          Papel no projeto
  ----------------------------------- -----------------------------------
  Python                              Orquestra as consultas, percorre
                                      municípios e estabelecimentos e
                                      grava os resultados.

  SOAP 1.2                            Protocolo usado para enviar
                                      requisições aos Web Services do
                                      CNES.

  Web Services do CNES                Fonte dos dados cadastrais
                                      consultados.

  XML                                 Formato das mensagens SOAP de
                                      requisição e resposta.

  `requests`                          Envia as requisições HTTP POST.

  `lxml`                              Interpreta o XML e permite
                                      localizar elementos com XPath.

  XPath                               Seleciona os campos relevantes
                                      dentro da resposta XML.

  CSV                                 Armazena os dados extraídos em
                                      formato tabular.
  -----------------------------------------------------------------------

### 2.1 SOAP Web Services

SOAP (Simple Object Access Protocol) é um protocolo de troca de
mensagens entre aplicações. No serviço utilizado, a comunicação é feita
por HTTP e o conteúdo das mensagens é XML.

Uma requisição SOAP contém, em linhas gerais:

-   um `Envelope`, que envolve a mensagem;
-   um `Header`, que pode conter informações de segurança;
-   um `Body`, que contém a operação e seus parâmetros.

O serviço valida a estrutura da mensagem. Por isso, nomes de elementos e
namespaces XML precisam corresponder ao contrato publicado pelo serviço.

### 2.2 API / Web Services do CNES

O CNES é o Cadastro Nacional de Estabelecimentos de Saúde. Neste MVP, a
integração é feita pelos Web Services SOAP disponibilizados pelo
Ministério da Saúde, e não por uma API REST/JSON.

Foram utilizadas duas operações:

**Consultar Estabelecimento de Saúde por Município**

-   Entrada: código do município no formato esperado pelo serviço.
-   Retorno esperado, conforme o manual utilizado: código CNES e nome
    fantasia dos estabelecimentos encontrados.

**Consultar Estabelecimento Saúde**

-   Entrada: código CNES do estabelecimento.
-   Retorno: dados gerais do estabelecimento, incluindo nome, endereço,
    telefones e estruturas de serviços especializados, quando
    disponíveis no cadastro.

### 2.3 XML e namespaces

XML representa os dados em uma estrutura hierárquica de elementos. Uma
resposta pode conter elementos aninhados, por exemplo:

``` xml
<servicoespecializados>
  <servicoespecializado>
    <classificacoes>
      <servicoclassificacao>
        <codigo>001</codigo>
        <descricao>ASSISTENCIA FISIOTERAPEUTICA</descricao>
      </servicoclassificacao>
    </classificacoes>
  </servicoespecializado>
</servicoespecializados>
```

O XML do CNES também utiliza **namespaces**, que qualificam os nomes dos
elementos. O prefixo (`ns25`, `ns26`, etc.) pode variar entre respostas.
Por isso, o código usa `local-name()` no XPath para localizar elementos
pelo nome local, sem depender do prefixo.

### 2.4 XPath

XPath é uma linguagem para selecionar elementos de um documento XML.

Exemplos usados no projeto:

``` python
# Nome fantasia
xml.xpath("//*[local-name()='nomeFantasia']")

# Telefones
xml.xpath("//*[local-name()='Telefone']")

# Descrições das classificações de serviços especializados
xml.xpath(
    "//*[local-name()='servicoclassificacao']/*[local-name()='descricao']"
)
```

O `lxml` executa essas expressões e devolve os elementos encontrados
para que o Python possa extrair seus textos.

## 3. Ambiente e endereços utilizados

O MVP foi desenvolvido para o **ambiente de homologação**, conforme
solicitado.

  ------------------------------------------------------------------------------------------------------------------
  Serviço                             WSDL de homologação
  ----------------------------------- ------------------------------------------------------------------------------
  CnesService                         `https://servicoshm.saude.gov.br/cnes/CnesService/v1r0?wsdl`

  EstabelecimentoSaudeService         `https://servicoshm.saude.gov.br/cnes/EstabelecimentoSaudeService/v1r0?wsdl`
  ------------------------------------------------------------------------------------------------------------------

Os endpoints usados para enviar as requisições (sem `?wsdl`) são:

``` text
https://servicoshm.saude.gov.br/cnes/CnesService/v1r0
https://servicoshm.saude.gov.br/cnes/EstabelecimentoSaudeService/v1r0
```

O WSDL (Web Services Description Language) é o documento que descreve o
serviço: operações disponíveis, parâmetros, tipos de dados, namespaces e
formato esperado das mensagens. O endpoint é o endereço para o qual o
programa envia a requisição SOAP.

> Homologação é um ambiente de testes. Antes de qualquer uso
> operacional, confirme com o responsável pelo serviço as condições de
> acesso, credenciais, limites de uso, estabilidade e possibilidade de
> utilização do ambiente de produção.

## 4. Fluxo implementado

``` text
municipios_am.csv
       |
       v
Ler código do município
       |
       v
SOAP: Consultar Estabelecimento por Município
       |
       v
Extrair códigos CNES da resposta
       |
       v
Para cada CNES:
SOAP: Consultar Estabelecimento de Saúde
       |
       v
Verificar se a resposta contém SOAP Fault
       |
       v
Extrair nome, endereço, telefone e classificações
       |
       v
Acumular até 50 registros válidos
       |
       v
resultado_ubs_am.csv
```

O limite de 50 registros é aplicado aos **registros que foram
consultados e adicionados com sucesso**. Erros de consulta não são
contabilizados como registros válidos.

## 5. Preparação do ambiente

### 5.1 Requisitos

-   Python 3 instalado.
-   Acesso à internet para alcançar os endpoints de homologação.
-   Arquivo `municipios_am.csv` no mesmo diretório do script.

### 5.2 Instalação das bibliotecas

No terminal:

``` bash
python -m pip install requests lxml
```

### 5.3 Arquivo de municípios

O script espera um CSV chamado `municipios_am.csv`, com uma coluna
chamada `codigo_ibge`.

Exemplo estrutural:

``` csv
codigo_ibge
130260
130010
130030
```

Os valores acima são apenas exemplos de formato. Preencha o arquivo com
os códigos corretos dos municípios do Amazonas, conforme a codificação
aceita pelo serviço.

**Atenção ao tamanho do código:** o manual apresentado para a operação
informa que `codigoMunicipio` aceita seis posições. Códigos IBGE
municipais normalmente também são encontrados em cadastros com sete
dígitos. Não remova dígitos automaticamente sem validar a
correspondência com o contrato e com a lista oficial usada pelo serviço.
O script abaixo espera que a coluna já contenha o código de seis
posições aceito pelo endpoint.

## 6. Código completo do protótipo

Salve o conteúdo abaixo em um arquivo, por exemplo,
`coletar_cnes_am.py`.

O código: - utiliza SOAP 1.2; - envia o cabeçalho WS-Security com
usuário e senha; - consulta os estabelecimentos por município; -
consulta os detalhes por CNES; - identifica respostas SOAP Fault; -
extrai as classificações de serviços especializados; - organiza o
endereço a partir dos campos XML disponíveis; - grava no máximo 50
registros válidos no CSV; - registra falhas no terminal e continua para
os próximos itens.

``` python
import csv
import os
import time
import requests
from lxml import etree

# ------------------------------------------------------------
# CONFIGURAÇÕES
# ------------------------------------------------------------

# Configure as credenciais por variáveis de ambiente.
# Não publique nem versione credenciais em repositórios.
USUARIO = os.getenv("CNES_USUARIO", "CNES.PUBLICO")
SENHA = os.getenv("CNES_SENHA")

if not SENHA:
    raise RuntimeError(
        "Defina a variável de ambiente CNES_SENHA antes de executar."
    )

URL_CNES = (
    "https://servicoshm.saude.gov.br/cnes/CnesService/v1r0"
)

URL_ESTAB = (
    "https://servicoshm.saude.gov.br/cnes/"
    "EstabelecimentoSaudeService/v1r0"
)

ARQUIVO_MUNICIPIOS = "municipios_am.csv"
ARQUIVO_SAIDA = "resultado_ubs_am.csv"

LIMITE_REGISTROS = 50
PAUSA_ENTRE_REQUISICOES = 0.3
TIMEOUT = 60

HEADERS = {
    "Content-Type": "application/soap+xml; charset=utf-8",
    "Accept": "application/soap+xml, application/xml, text/xml",
}

SOAP_NS = "http://www.w3.org/2003/05/soap-envelope"


# ------------------------------------------------------------
# MONTAGEM DO CABEÇALHO SOAP / WS-SECURITY
# ------------------------------------------------------------

def soap_header():
    return f"""
    <soap:Header>
        <wsse:Security
            xmlns:wsse="http://docs.oasis-open.org/wss/2004/01/
            oasis-200401-wss-wssecurity-secext-1.0.xsd">
            <wsse:UsernameToken>
                <wsse:Username>{USUARIO}</wsse:Username>
                <wsse:Password>{SENHA}</wsse:Password>
            </wsse:UsernameToken>
        </wsse:Security>
    </soap:Header>
    """


# ------------------------------------------------------------
# ENVIO E TRATAMENTO DE REQUISIÇÕES
# ------------------------------------------------------------

def enviar_soap(url, xml):
    resposta = requests.post(
        url,
        data=xml.encode("utf-8"),
        headers=HEADERS,
        timeout=TIMEOUT,
    )

    resposta.raise_for_status()

    raiz = etree.fromstring(resposta.content)

    # Uma falha SOAP pode vir no corpo mesmo quando o XML é válido.
    faults = raiz.xpath(
        "//*[local-name()='Fault']"
    )

    if faults:
        mensagem = " ".join(
            faults[0].itertext()
        ).strip()

        raise RuntimeError(f"SOAP Fault: {mensagem}")

    return raiz


# ------------------------------------------------------------
# CONSULTA DE ESTABELECIMENTOS POR MUNICÍPIO
# ------------------------------------------------------------

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


# ------------------------------------------------------------
# CONSULTA DETALHADA DO ESTABELECIMENTO
# ------------------------------------------------------------

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
# FUNÇÕES AUXILIARES DE EXTRAÇÃO
# ------------------------------------------------------------

def primeiro_texto(xml, xpath):
    elementos = xml.xpath(xpath)

    if not elementos:
        return ""

    return " ".join(
        "".join(elementos[0].itertext()).split()
    )


def texto_filho(elemento, nome):
    encontrados = elemento.xpath(
        f"./*[local-name()='{nome}']"
    )

    if not encontrados:
        return ""

    return " ".join(
        "".join(encontrados[0].itertext()).split()
    )


# ------------------------------------------------------------
# EXTRAÇÃO DO ENDEREÇO
# ------------------------------------------------------------

def extrair_endereco(xml):
    enderecos = xml.xpath(
        "//*[local-name()='Endereco']"
    )

    if not enderecos:
        return ""

    endereco = enderecos[0]

    tipo_logradouro = ""
    tipos = endereco.xpath(
        ".//*[local-name()='TipoLogradouro']"
        "/*[local-name()='descricaoTipoLogradouro']"
    )
    if tipos:
        tipo_logradouro = " ".join(
            "".join(tipos[0].itertext()).split()
        )

    logradouro = texto_filho(endereco, "nomeLogradouro")
    numero = texto_filho(endereco, "numero")
    complemento = texto_filho(endereco, "complemento")

    bairro = primeiro_texto(
        endereco,
        ".//*[local-name()='Bairro']"
        "/*[local-name()='descricaoBairro']"
    )

    cep = primeiro_texto(
        endereco,
        ".//*[local-name()='CEP']"
        "/*[local-name()='numeroCEP']"
    )

    municipio = primeiro_texto(
        endereco,
        ".//*[local-name()='Municipio']"
        "/*[local-name()='nomeMunicipio']"
    )

    uf = primeiro_texto(
        endereco,
        ".//*[local-name()='Municipio']"
        "//*[local-name()='siglaUF']"
    )

    partes_logradouro = [
        parte for parte in [tipo_logradouro, logradouro]
        if parte
    ]

    linha = " ".join(partes_logradouro)

    if numero:
        linha += f", {numero}"

    if complemento:
        linha += f", {complemento}"

    partes = [
        linha,
        bairro,
        municipio,
        uf,
    ]

    resultado = " - ".join(
        parte for parte in partes if parte
    )

    if cep:
        resultado += f" - CEP: {cep}"

    return resultado


# ------------------------------------------------------------
# EXTRAÇÃO DOS TELEFONES
# ------------------------------------------------------------

def extrair_telefones(xml):
    telefones = []

    for telefone in xml.xpath(
        "//*[local-name()='Telefone']"
    ):
        ddd = texto_filho(telefone, "DDD")
        numero = texto_filho(
            telefone,
            "numeroTelefone"
        )

        if numero:
            if ddd:
                valor = f"({ddd}) {numero}"
            else:
                valor = numero

            if valor not in telefones:
                telefones.append(valor)

    return "; ".join(telefones)


# ------------------------------------------------------------
# EXTRAÇÃO DOS SERVIÇOS / CLASSIFICAÇÕES
# ------------------------------------------------------------

def extrair_especialidades(xml):
    especialidades = []

    descricoes = xml.xpath(
        "//*[local-name()='servicoclassificacao']"
        "/*[local-name()='descricao']"
    )

    for descricao in descricoes:
        valor = " ".join(
            "".join(descricao.itertext()).split()
        )

        if valor and valor not in especialidades:
            especialidades.append(valor)

    return "; ".join(especialidades)


# ------------------------------------------------------------
# EXTRAÇÃO CONSOLIDADA
# ------------------------------------------------------------

def extrair(xml):
    nome = primeiro_texto(
        xml,
        "//*[local-name()='nomeFantasia']"
    )

    endereco = extrair_endereco(xml)
    telefone = extrair_telefones(xml)
    especialidades = extrair_especialidades(xml)

    return {
        "nome": nome,
        "endereco": endereco,
        "telefone": telefone,
        "especialidades": especialidades,
    }


# ------------------------------------------------------------
# EXECUÇÃO PRINCIPAL
# ------------------------------------------------------------

def executar():
    dados = []
    cnes_processados = set()

    with open(
        ARQUIVO_MUNICIPIOS,
        "r",
        newline="",
        encoding="utf-8-sig"
    ) as arquivo:
        leitor = csv.DictReader(arquivo)

        if not leitor.fieldnames or "codigo_ibge" not in leitor.fieldnames:
            raise ValueError(
                f"O arquivo {ARQUIVO_MUNICIPIOS} precisa ter "
                "uma coluna chamada codigo_ibge."
            )

        for linha in leitor:
            if len(dados) >= LIMITE_REGISTROS:
                break

            codigo = (linha.get("codigo_ibge") or "").strip()

            if not codigo:
                continue

            print(f"Consultando município: {codigo}")

            try:
                resposta_municipio = consultar_cnes_municipio(
                    codigo
                )

                codigos = resposta_municipio.xpath(
                    "//*[local-name()='CodigoCNES']"
                    "/*[local-name()='codigo']/text()"
                )

                print(
                    f"  CNES encontrados: {len(codigos)}"
                )

            except Exception as erro:
                print(
                    f"  Falha ao consultar município "
                    f"{codigo}: {erro}"
                )
                continue

            for codigo_cnes in codigos:
                if len(dados) >= LIMITE_REGISTROS:
                    break

                cnes = str(codigo_cnes).strip()

                if not cnes or cnes in cnes_processados:
                    continue

                cnes_processados.add(cnes)

                try:
                    time.sleep(PAUSA_ENTRE_REQUISICOES)

                    detalhe = consultar_estabelecimento(cnes)
                    info = extrair(detalhe)

                    info["cnes"] = cnes
                    dados.append(info)

                    print(
                        f"  [{len(dados)}/{LIMITE_REGISTROS}] "
                        f"{cnes} - {info['nome']}"
                    )

                except Exception as erro:
                    print(f"  Erro no CNES {cnes}: {erro}")

    campos = [
        "cnes",
        "nome",
        "endereco",
        "telefone",
        "especialidades",
    ]

    with open(
        ARQUIVO_SAIDA,
        "w",
        newline="",
        encoding="utf-8-sig"
    ) as arquivo:
        escritor = csv.DictWriter(
            arquivo,
            fieldnames=campos
        )

        escritor.writeheader()
        escritor.writerows(dados)

    print()
    print("Processamento finalizado.")
    print(f"Registros salvos: {len(dados)}")
    print(f"Arquivo gerado: {ARQUIVO_SAIDA}")


if __name__ == "__main__":
    executar()
```

### 6.1 Configurar a senha

O código não deixa a senha escrita diretamente no arquivo. No
Linux/macOS, configure a variável no terminal antes de executar:

``` bash
export CNES_SENHA='SUA_SENHA'
```

Se necessário, configure também o usuário:

``` bash
export CNES_USUARIO='CNES.PUBLICO'
```

Não compartilhe arquivos contendo credenciais e não envie senhas para
repositórios públicos.

### 6.2 Executar

No diretório em que estão o script e o CSV:

``` bash
python coletar_cnes_am.py
```

Ao final, o programa deverá informar quantos registros foram salvos e
gerar:

``` text
resultado_ubs_am.csv
```

O arquivo é gravado em UTF-8 com BOM (`utf-8-sig`) para melhorar a
abertura de caracteres acentuados em alguns programas de planilha.

## 7. Estrutura do CSV de saída

O arquivo `resultado_ubs_am.csv` possui as colunas:

  -----------------------------------------------------------------------
  Campo                               Conteúdo
  ----------------------------------- -----------------------------------
  `cnes`                              Código CNES do estabelecimento.

  `nome`                              Nome fantasia.

  `endereco`                          Endereço montado a partir dos
                                      elementos retornados pelo serviço.

  `telefone`                          Telefones encontrados, com DDD
                                      quando informado.

  `especialidades`                    Descrições encontradas em
                                      `servicoclassificacao/descricao`.
  -----------------------------------------------------------------------

Exemplo ilustrativo:

``` csv
cnes,nome,endereco,telefone,especialidades
3360377,UNIDADE DE SAUDE EXEMPLO,RUA EXEMPLO 100 - CENTRO - MANAUS - AM,(92) 30000000,ATENDIMENTO EXEMPLO; SERVICO EXEMPLO
```

Os valores acima são fictícios e servem apenas para demonstrar o
formato.

## 8. Como testar cada operação isoladamente

Antes de executar a coleta completa, é recomendável testar uma consulta
de cada vez.

### 8.1 Testar a consulta por município

``` python
resposta = consultar_cnes_municipio("CODIGO_DE_SEIS_POSICOES")

print(
    etree.tostring(
        resposta,
        pretty_print=True,
        encoding="unicode"
    )
)
```

Confira se a resposta contém elementos `CodigoCNES` com filhos `codigo`.

### 8.2 Testar a consulta de um estabelecimento

``` python
resposta = consultar_estabelecimento("CODIGO_CNES")

print(
    etree.tostring(
        resposta,
        pretty_print=True,
        encoding="unicode"
    )
)
```

Confira se o retorno contém `DadosGeraisEstabelecimentoSaude`,
`nomeFantasia`, `Endereco`, `Telefone` e, quando cadastrados,
`servicoclassificacao`.

### 8.3 Conferir as classificações extraídas

``` python
for descricao in resposta.xpath(
    "//*[local-name()='servicoclassificacao']"
    "/*[local-name()='descricao']"
):
    print(" -", "".join(descricao.itertext()).strip())
```

## 9. Erros encontrados durante o desenvolvimento e interpretação

### 9.1 Código de município com tamanho inválido

Foi retornado um erro de validação indicando que `codigoMunicipio` tinha
sete caracteres, mas o schema da operação aceitava no máximo seis.

**Interpretação:** o valor enviado não respeitou o tamanho definido no
contrato do serviço.

**Tratamento:** conferir o formato esperado pelo WSDL/manual e fornecer
o código de seis posições aceito pelo endpoint. Não truncar códigos sem
conferir a correspondência do município.

### 9.2 `invalid predicate` no XPath

Esse erro pode ocorrer quando uma expressão XPath está malformada ou
quando se utiliza uma operação incompatível com o objeto consultado.

**Tratamento:** usar expressões XPath válidas do `lxml` e testar cada
expressão isoladamente sobre o XML recebido.

### 9.3 SOAP Fault / `MessageBlocked`

O serviço pode responder com um envelope SOAP contendo `Fault`, mesmo
que a resposta seja XML válido. Isso indica que a requisição foi
rejeitada ou falhou no processamento.

Durante o desenvolvimento, uma falha de validação informou que o
elemento `FiltroPesquisaEstabelecimentoSaude` era esperado em um
namespace específico:

``` text
http://servicos.saude.gov.br/wsdl/mensageria/v1r0/filtropesquisaestabelecimentosaude
```

O namespace do elemento externo do filtro precisou ser ajustado para
corresponder ao schema do serviço.

**Tratamento recomendado:** - conferir o namespace e a estrutura no
WSDL; - conferir o nome exato da operação; - conferir os tipos e a ordem
dos elementos; - registrar o XML de requisição e a resposta de erro para
diagnóstico; - não tratar um `Fault` como se fosse um estabelecimento
válido.

### 9.4 Especialidades não apareciam no CSV

A primeira versão procurava elementos com nome contendo `Especialidade`,
mas a resposta analisada utilizava outra estrutura:

``` xml
<servicoclassificacao>
    <codigo>001</codigo>
    <descricao>ASSISTENCIA FISIOTERAPEUTICA</descricao>
</servicoclassificacao>
```

A extração foi corrigida para procurar:

``` python
xml.xpath(
    "//*[local-name()='servicoclassificacao']"
    "/*[local-name()='descricao']"
)
```

Assim, cada descrição de classificação é adicionada ao campo
`especialidades`.

### 9.5 Respostas diferentes entre estabelecimentos

Nem todos os estabelecimentos possuem necessariamente os mesmos dados
preenchidos. Alguns podem não apresentar telefone ou classificações de
serviços especializados.

**Interpretação:** campo vazio no CSV não significa necessariamente erro
de extração; pode significar que a informação não foi retornada para
aquele cadastro.

## 10. Limitações e cuidados do MVP

1.  **Homologação:** o código utiliza o ambiente de homologação, que
    pode ter dados, disponibilidade e comportamento diferentes do
    ambiente de produção.
2.  **Não é uma lista exclusiva de UBS:** a consulta por município
    retorna estabelecimentos cadastrados no CNES. Para produzir uma base
    somente de UBS, será necessário aplicar um filtro pelo
    código/descrição do tipo de estabelecimento, conforme a
    classificação oficial retornada pelo serviço.
3.  **Horário de funcionamento:** não faz parte desta versão do
    protótipo.
4.  **Especialidades e serviços:** o código extrai classificações em
    `servicoclassificacao/descricao`. Isso representa os
    serviços/classificações retornados pelo CNES e não deve ser
    interpretado automaticamente como uma lista completa de
    especialidades médicas ou garantia de atendimento disponível.
5.  **Dados cadastrais:** podem estar ausentes, desatualizados ou variar
    conforme o estabelecimento.
6.  **Limite de registros:** a execução de demonstração salva no máximo
    50 estabelecimentos válidos.
7.  **Paginação e volume:** o protótipo não implementa paginação
    avançada nem processamento distribuído. Uma coleta estadual completa
    pode exigir controle de volume, retomada e tratamento de limites do
    serviço.
8.  **Requisições repetidas:** o script inclui uma pequena pausa entre
    consultas de detalhes. O intervalo deve ser ajustado às orientações
    do provedor do serviço.
9.  **Endereço:** o endereço é montado a partir dos elementos
    encontrados. Se algum campo não vier no XML, ele ficará ausente no
    texto final.
10. **Credenciais:** não armazene senhas diretamente no código nem as
    publique.

## 11. Melhorias recomendadas para a próxima versão

-   Aplicar filtro explícito para selecionar somente estabelecimentos
    classificados como UBS.
-   Implementar paginação ou estratégia de coleta completa, se o serviço
    oferecer esse recurso.
-   Salvar o progresso incrementalmente para permitir retomar uma
    execução interrompida.
-   Gerar um arquivo separado com erros por município/CNES.
-   Implementar tentativas controladas para falhas temporárias, com
    espera progressiva.
-   Validar e padronizar endereços e telefones.
-   Registrar data e hora da coleta e data de atualização cadastral,
    quando retornada.
-   Automatizar a atualização periódica da base.
-   Substituir o CSV por banco de dados quando houver necessidade de
    consultas concorrentes ou maior volume.
-   Criar uma camada de busca que permita ao chatbot localizar unidades
    por município, bairro, nome, serviço ou telefone.
-   Exibir ao usuário a origem dos dados e a data da última atualização.

## 12. Como os dados podem alimentar o chatbot

O CSV é uma etapa intermediária de preparação dos dados. Para o chatbot,
recomenda-se:

1.  Carregar o CSV em uma base de dados ou mecanismo de busca.
2.  Normalizar nomes de municípios, bairros, endereços e serviços.
3.  Criar filtros estruturados para município, bairro e tipo de
    estabelecimento.
4.  Recuperar registros relevantes a partir da pergunta do usuário.
5.  Gerar a resposta usando os dados recuperados, sem inventar
    informações ausentes.
6.  Informar quando um campo não estiver cadastrado.

Exemplos de perguntas que a base poderá apoiar, desde que os campos
estejam presentes:

-   "Qual é o telefone desta unidade?"
-   "Onde fica a unidade de saúde X?"
-   "Quais estabelecimentos de determinado município possuem o serviço
    Y?"
-   "Quais unidades estão cadastradas em determinado município?"

A pergunta "qual é a UBS mais próxima?" exige também a localização do
usuário e coordenadas geográficas confiáveis das unidades; não é
respondida apenas pelo endereço textual.

## 13. Referências técnicas

-   WSDL do CnesService (homologação):\
    `https://servicoshm.saude.gov.br/cnes/CnesService/v1r0?wsdl`
-   WSDL do EstabelecimentoSaudeService (homologação):\
    `https://servicoshm.saude.gov.br/cnes/EstabelecimentoSaudeService/v1r0?wsdl`
-   Manual de integração do CNES utilizado durante o desenvolvimento ---
    especialmente a operação de consulta por município e a operação de
    consulta detalhada de estabelecimento.
-   Documentação do Python: `https://docs.python.org/3/`
-   Documentação do Requests: `https://requests.readthedocs.io/`
-   Documentação do lxml: `https://lxml.de/`

------------------------------------------------------------------------

## Resumo para apresentação

O MVP implementa uma integração em Python com os Web Services SOAP do
CNES, no ambiente de homologação do Ministério da Saúde. A aplicação lê
os códigos dos municípios do Amazonas, consulta os estabelecimentos
cadastrados, recupera os detalhes de cada unidade e utiliza XML, `lxml`
e XPath para extrair nome, endereço, telefones e classificações de
serviços especializados. Os dados são consolidados em um CSV com até 50
registros válidos, que funciona como base inicial para a construção de
um chatbot de consulta a estabelecimentos de saúde.

**Ressalva importante para a apresentação:** a versão atual demonstra a
viabilidade técnica da integração e da extração de dados. Para afirmar
que a base contém exclusivamente UBS, ainda é necessário implementar e
validar o filtro pelo tipo de estabelecimento no cadastro CNES.
