# Documentação técnica — Integração CNES/DATASUS, Google Sheets e Typebot

```
          DATASUS / CNES
                |
                | SOAP
                v
         SCRIPT PYTHON
                |
                | Extração e tratamento
                v
             ARQUIVO CSV
                |
                | Importação
                v
          GOOGLE SHEETS
                |
                | Integração
                v
             TYPEBOT
                |
                v
          USUÁRIO FINAL
```

### Responsabilidade de cada componente

| Componente    | Responsabilidade                                |
| ------------- | ----------------------------------------------- |
| DATASUS/CNES  | Disponibilizar informações dos estabelecimentos |
| Python        | Consultar a API SOAP e processar os dados       |
| CSV           | Armazenar os dados extraídos                    |
| Google Sheets | Servir como base de dados acessível             |
| Typebot       | Receber consultas e apresentar resultados       |

### Por que essa arquitetura?

Para um MVP, essa abordagem apresenta algumas vantagens:

- Não exige a criação de um backend complexo.
- Não exige a contratação de infraestrutura.
- Permite atualizar os dados periodicamente.
- Facilita a manutenção da base.
- Permite testar a experiência do chatbot rapidamente.

Uma vantagem importante é que as consultas ao DATASUS não precisam acontecer durante cada conversa. Os dados podem ser extraídos previamente e disponibilizados no Google Sheets.

---

# 2. Extração de dados do DATASUS

A comunicação com o CNES é realizada por meio de serviços SOAP.

Foram utilizados dois serviços:

**Consulta de estabelecimentos por município:**

```
https://servicoshm.saude.gov.br/cnes/CnesService/v1r0
```

**Consulta detalhada de estabelecimento:**

```
https://servicoshm.saude.gov.br/cnes/EstabelecimentoSaudeService/v1r0
```

> Atenção: os endereços acima pertencem ao ambiente de homologação (`servicoshm`). Antes de utilizar o projeto em produção, é necessário confirmar os endpoints de produção e as condições de acesso.

## 2.1. Funcionamento da extração

O processo funciona em duas etapas.

**Etapa 1 — Consulta por município**

O script envia o código IBGE do município ao serviço SOAP.

Como resposta, recebe os códigos CNES dos estabelecimentos cadastrados naquele município.

**Etapa 2 — Consulta individual**

Para cada código CNES encontrado, o script realiza uma nova consulta.

Essa consulta retorna informações detalhadas, como:

- Nome fantasia;
- Endereço;
- Telefone;
- Serviços e classificações.

Os dados são processados e armazenados em uma lista Python.

Ao final, essa lista é exportada para CSV.

---

# 3. Estrutura dos arquivos

O projeto utiliza dois arquivos principais.

### municipios_am.csv

Contém a relação de municípios que serão consultados.

Exemplo:

```
codigo_ibge,nome
1302603,Manaus
1303403,Parintins
1301902,Itacoatiara
```

O script utiliza a coluna `codigo_ibge`.

### resultado_ubs_am.csv

É o arquivo gerado pelo processo de extração.

Sua estrutura é:

```
cnes,nome,endereco,telefone,especialidades
```

Cada linha representa um estabelecimento de saúde.

Exemplo:

```
cnes,nome,endereco,telefone,especialidades
2019558,MATERNIDADE BALBINA MESTRINHO,"RUA DUQUE DE CAXIAS, 1142 - Praca 14 De Janeiro - Manaus/AM - CEP 69020-140",(92) 31824547,"LAQUEADURA | ACOMPANHAMENTO DO PRE-NATAL DE ALTO RISCO | PARTO EM GESTACAO DE ALTO RISCO"
```

## 3.1. Descrição das colunas

| Campo          | Descrição                               |
| -------------- | --------------------------------------- |
| cnes           | Código identificador do estabelecimento |
| nome           | Nome fantasia                           |
| endereco       | Endereço formatado                      |
| telefone       | Telefone de contato                     |
| especialidades | Serviços e classificações oferecidos    |

O campo `especialidades` utiliza o separador `|` para distinguir cada serviço.

Isso permite que o Typebot apresente as especialidades individualmente.

---

# 4. Script Python de extração

## 4.1. Dependências

Instale as bibliotecas necessárias:

```
pip install requests lxml
```

São utilizadas:

- `requests`: para realizar requisições HTTP SOAP.
- `lxml`: para interpretar as respostas XML.
- `csv`: para gerar o arquivo CSV.
- `os`: para configuração de variáveis de ambiente.

## 4.2. Código completo

O código abaixo contempla:

- Autenticação SOAP;
- Consulta de estabelecimentos por município;
- Consulta individual por CNES;
- Extração de nome;
- Extração estruturada do endereço;
- Extração de telefone;
- Extração de especialidades;
- Exportação para CSV.

```
import csvimport requestsfrom lxml import etreeUSUARIO = "CNES.PUBLICO"SENHA = "cnes#2015public"URL_CNES = "https://servicoshm.saude.gov.br/cnes/CnesService/v1r0"URL_ESTAB = "https://servicoshm.saude.gov.br/cnes/EstabelecimentoSaudeService/v1r0"HEADERS = {    "Content-Type": "application/soap+xml; charset=utf-8"}LIMITE = 10000def soap_header():    return f"""    <soap:Header>        <wsse:Security xmlns:wsse="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd">            <wsse:UsernameToken>                <wsse:Username>{USUARIO}</wsse:Username>                <wsse:Password>{SENHA}</wsse:Password>
```

### Observação sobre credenciais

O exemplo preserva as credenciais utilizadas no desenvolvimento. Em produção, é recomendável armazená-las em variáveis de ambiente, em vez de deixá-las diretamente no código.

---

# 5. Tratamento dos endereços

Um dos principais problemas encontrados durante o desenvolvimento foi a concatenação dos elementos do endereço.

Inicialmente, o retorno da API apresentava informações semelhantes a:

```
AVENIDA CARVALHO LEAL891CACHOEIRINHA69065000130260MANAUS13AM
```

Isso acontecia porque o código extraía todo o conteúdo XML de uma vez, sem inserir separadores entre os campos.

## 5.1. Estrutura original do XML

A análise da resposta SOAP mostrou que o endereço possui campos separados:

```
<ns22:Endereco>

    <ns22:nomeLogradouro>
        AVN PRESIDENTE GETULIO VARGAS
    </ns22:nomeLogradouro>

    <ns22:numero>
        428
    </ns22:numero>

    <ns22:Bairro>

        <ns24:descricaoBairro>
            CENTRO
        </ns24:descricaoBairro>

    </ns22:Bairro>

    <ns22:CEP>

        <ns25:numeroCEP>
            54505560
        </ns25:numeroCEP>

    </ns22:CEP>

    <ns22:Municipio>

        <ns2:codigoMunicipio>
            260290
        </ns2:codigoMunicipio>

        <ns2:nomeMunicipio>
            CABO DE SANTO AGOSTINHO
        </ns2:nomeMunicipio>

        <ns2:UF>

            <ns3:codigoUF>
                26
            </ns3:codigoUF>

            <ns3:siglaUF>
                PE
            </ns3:siglaUF>

        </ns2:UF>

    </ns22:Municipio>

</ns22:Endereco>
```

## 5.2. Solução implementada

O código passou a extrair individualmente:

1. Logradouro;
2. Número;
3. Complemento;
4. Bairro;
5. CEP;
6. Município;
7. UF.

Depois, monta o endereço utilizando separadores.

Exemplo de resultado:

```
AVN PRESIDENTE GETULIO VARGAS, 428 - Centro - Cabo De Santo Agostinho/PE - CEP 54505-560
```

Essa abordagem evita depender da posição dos elementos no XML ou dos prefixos de namespace.

---

# 6. Integração com Google Sheets

Depois de gerar o CSV, os dados são disponibilizados no Google Sheets.

Para o MVP, a importação pode ser realizada manualmente.

## 6.1. Importação

1. Execute o script Python.
2. Abra o Google Sheets.
3. Crie uma nova planilha.
4. Acesse **Arquivo → Importar**.
5. Selecione o arquivo `resultado_ubs_am.csv`.
6. Configure a importação para separar os dados por vírgulas.
7. Confirme se os campos foram distribuídos corretamente.

A planilha deverá apresentar:

| cnes    | nome                          | endereco                 | telefone      | especialidades                  |
| ------- | ----------------------------- | ------------------------ | ------------- | ------------------------------- |
| 2019558 | MATERNIDADE BALBINA MESTRINHO | RUA DUQUE DE CAXIAS...   | (92) 31824547 | LAQUEADURA \| ACOMPANHAMENTO... |
| 3360377 | CENTRO MEDICO N S APARECIDA   | AVENIDA CARVALHO LEAL... | (92) 32328942 | ATENCAO A INFERTILIDADE...      |

## 6.2. Atualização da planilha

Sempre que o script for executado novamente, um novo CSV será gerado.

Para atualizar a base:

1. Execute o script.
2. Gere o novo CSV.
3. Importe os dados atualizados no Google Sheets, substituindo os registros anteriores.

**Melhoria futura:** automatizar essa atualização utilizando Google Apps Script ou a API oficial do Google Sheets.

## 6.3. Integração com Typebot

O Typebot utiliza a integração com Google Sheets para consultar os dados.

As variáveis utilizadas no fluxo são:

| Variável               | Conteúdo                  |
| ---------------------- | ------------------------- |
| `nome`                 | Nome dos estabelecimentos |
| `endereco`             | Endereços                 |
| `telefone`             | Telefones                 |
| `todas_especialidades` | Especialidades e serviços |

Essas variáveis são utilizadas posteriormente em blocos JavaScript para organizar as respostas.

---

# 7. Integração com Typebot — JavaScript

Durante o desenvolvimento, foi necessário resolver alguns problemas relacionados ao retorno de listas pelo Google Sheets.

O principal problema era que o Typebot poderia retornar:

- Uma string quando existia apenas um resultado;
- Uma lista quando existiam vários resultados.

Isso provocava erros na apresentação.

Por exemplo, quando havia somente um estabelecimento, o resultado aparecia assim:

```
🏥 H
📍 A
📞 (
```

O problema acontecia porque o JavaScript interpretava a string como uma sequência de caracteres.

A solução foi normalizar os valores, transformando strings em listas.

## 7.1. Exibir nome, endereço e telefone

Código utilizado:

```
const nomesBrutos = {{nome}};
const enderecosBrutos = {{endereco}};
const telefonesBrutos = {{telefone}};

const comoLista = (valor) =>
  Array.isArray(valor) ? valor : [valor];

const nomes = comoLista(nomesBrutos);
const enderecos = comoLista(enderecosBrutos);
const telefones = comoLista(telefonesBrutos);

let resposta = "";

const total = Math.min(
  5,
  nomes.length,
  enderecos.length,
  telefones.length
);

for (let i = 0; i < total; i++) {

  resposta += `🏥 ${nomes[i] || "Nome não informado"}\n`;

  resposta += `📍 ${enderecos[i] || "Endereço não informado"}\n`;

  resposta += `📞 ${telefones[i] || "Telefone não informado"}`;

  if (i < total - 1) {
    resposta += "\n\n";
  }
}

if (total === 0) {
  return "Não encontrei unidades para os critérios informados.";
}

return resposta;
```

### Funcionamento

O código:

1. Recebe as três variáveis.
2. Verifica se são listas ou strings.
3. Normaliza os valores.
4. Percorre os resultados.
5. Associa os campos pelo mesmo índice.
6. Exibe até cinco estabelecimentos.

O uso do índice é importante.

Por exemplo:

```
nomes[0]
enderecos[0]
telefones[0]
```

Os três valores pertencem ao mesmo estabelecimento.

Da mesma forma:

```
nomes[1]
enderecos[1]
telefones[1]
```

Pertencem ao segundo estabelecimento.

---

# 8. Exibir também as especialidades

Posteriormente, foi adicionada a necessidade de apresentar todas as especialidades e serviços oferecidos por cada estabelecimento.

A coluna `especialidades` contém informações semelhantes a:

```
ATENCAO A INFERTILIDADE | CONTRACEPCAO CLINICA | NUCLEO DE SEGURANCA DO PACIENTE
```

O objetivo é transformar essa string em uma lista visualmente organizada.

## 8.1. Código completo

```
const nomesBrutos = {{nome}};
const enderecosBrutos = {{endereco}};
const telefonesBrutos = {{telefone}};
const especialidadesBrutas = {{todas_especialidades}};

const comoLista = (valor) =>
  Array.isArray(valor) ? valor : [valor];

const nomes = comoLista(nomesBrutos);
const enderecos = comoLista(enderecosBrutos);
const telefones = comoLista(telefonesBrutos);
const especialidades = comoLista(especialidadesBrutas);

let resposta = "";

const total = Math.min(
  5,
  nomes.length,
  enderecos.length,
  telefones.length
);

for (let i = 0; i < total; i++) {

  const listaEspecialidades = String(especialidades[i] || "")
    .split("|")
    .map(item => item.trim())
    .filter(Boolean);

  const textoEspecialidades = listaEspecialidades.length
    ? listaEspecialidades.map(item => `• ${item}`).join("\n")
    : "Não informado";

  resposta += `🏥 ${nomes[i] || "Nome não informado"}\n`;

  resposta += `📍 ${enderecos[i] || "Endereço não informado"}\n`;

  resposta += `📞 ${telefones[i] || "Telefone não informado"}\n`;

  resposta += `🩺 Especialidades:\n${textoEspecialidades}`;

  if (i < total - 1) {
    resposta += "\n\n────────────────────\n\n";
  }
}

if (total === 0) {
  return "Não encontrei unidades para os critérios informados.";
}

return resposta;
```

## 8.2. Exemplo de resultado

```
🏥 MATERNIDADE BALBINA MESTRINHO

📍 RUA DUQUE DE CAXIAS, 1142 - Praca 14 De Janeiro - Manaus/AM - CEP 69020-140

📞 (92) 31824547

🩺 Especialidades:

• LAQUEADURA
• ACOMPANHAMENTO DO PRE-NATAL DE ALTO RISCO
• PARTO EM GESTACAO DE ALTO RISCO
• CENTRO DE PARTO NORMAL
• RADIOLOGIA
• ULTRASONOGRAFIA
• EXAME ELETROCARDIOGRAFICO
• FARMACIA HOSPITALAR
```

A apresentação continua seguindo a mesma lógica para os demais estabelecimentos.

**Importante:** o código pressupõe que `todas_especialidades` seja uma lista alinhada às demais variáveis, com uma string de especialidades por estabelecimento. Se o Typebot retornar uma única string agregada, será necessário ajustar o mapeamento.

---

# 9. Limitação de resultados

Durante o desenvolvimento, também foi necessário limitar a quantidade de estabelecimentos exibidos.

O objetivo é evitar respostas muito extensas.

Foi utilizada a seguinte expressão:

```
const total = Math.min(
  5,
  nomes.length,
  enderecos.length,
  telefones.length
);
```

Ela determina a quantidade de registros a serem exibidos.

Exemplos:

| Resultados encontrados | Resultados exibidos |
| ---------------------- | ------------------- |
| 1                      | 1                   |
| 2                      | 2                   |
| 3                      | 3                   |
| 5                      | 5                   |
| 10                     | 5                   |
| 20                     | 5                   |

Dessa forma, o chatbot apresenta no máximo cinco estabelecimentos por resposta.

---

# 10. Utilização de inteligência artificial

Foi considerada a possibilidade de utilizar IA para formatar os endereços retornados pelo DATASUS.

Entretanto, para o formato de XML identificado, a utilização de IA não é necessária.

O endereço já possui campos estruturados:

- Logradouro;
- Número;
- Bairro;
- CEP;
- Município;
- UF.

A extração por regras é mais adequada porque:

- Não depende de um modelo de IA;
- Não gera custos com chamadas de API;
- É mais previsível;
- Evita que a IA invente informações ausentes;
- Funciona mesmo sem conexão com serviços externos de IA.

A utilização de IA poderá ser considerada futuramente para interpretar endereços inconsistentes ou permitir pesquisas em linguagem natural.

---

# 11. Problemas encontrados e soluções

Durante a implementação, foram identificados alguns problemas.

| Problema                              | Causa                                              | Solução                                  |
| ------------------------------------- | -------------------------------------------------- | ---------------------------------------- |
| Endereços concatenados                | Extração de todos os elementos XML sem separadores | Extração individual dos campos           |
| Endereço incompleto                   | XPath apontando para o elemento errado             | Utilização da estrutura XML correta      |
| Telefone incompleto                   | Extração incorreta do DDD                          | Busca do DDD dentro de cada telefone     |
| Apenas uma especialidade              | Retorno antecipado dentro de um loop               | Processamento completo antes do `return` |
| Resultados aparecendo como caracteres | String interpretada como lista                     | Normalização com `Array.isArray()`       |
| Associação incorreta de dados         | Percorrer listas separadamente                     | Utilização do mesmo índice               |
| Excesso de resultados                 | Retorno de todos os registros encontrados          | Limitação com `Math.min()`               |
| Especialidades concatenadas           | Separador armazenado como texto                    | Divisão com \`.split("                   |

---

# 12. Atualização e manutenção da base

A base de dados deve ser atualizada periodicamente.

Uma rotina inicial recomendada:

```
1. Executar script Python
          |
          v
2. Consultar DATASUS
          |
          v
3. Gerar CSV atualizado
          |
          v
4. Atualizar Google Sheets
          |
          v
5. Testar consultas no Typebot
```

É importante registrar a data da última atualização.

Os dados do CNES podem sofrer alterações, incluindo:

- Mudança de endereço;
- Alteração de telefone;
- Inclusão de serviços;
- Exclusão de serviços;
- Alteração da situação cadastral.

Para o MVP, uma atualização mensal pode ser um ponto de partida, ajustável conforme a necessidade do projeto.

---

# 13. Cuidados para produção

Antes de disponibilizar o chatbot ao público, alguns cuidados devem ser observados.

### 13.1. Ambiente da API

Confirmar a utilização dos endpoints de produção do DATASUS, pois os utilizados no desenvolvimento são de homologação.

### 13.2. Credenciais

Não deixar senhas diretamente no código-fonte em ambientes compartilhados.

### 13.3. Qualidade dos dados

Realizar testes com diferentes estabelecimentos para verificar:

- Endereços;
- Telefones;
- Especialidades;
- Dados ausentes;
- Duplicidades.

### 13.4. Dados desatualizados

Informar ao usuário que os dados apresentados são provenientes do CNES e podem estar sujeitos a alterações.

### 13.5. Alinhamento das listas

Garantir que nome, endereço, telefone e especialidades mantenham a mesma ordenação na integração com Google Sheets.

Esse ponto é especialmente importante: se uma coluna retornar os registros em ordem diferente, o chatbot poderá apresentar o telefone de uma unidade associado ao nome de outra.

Uma evolução recomendada é utilizar o código CNES como identificador único de cada estabelecimento.

---

# 14. Possíveis melhorias futuras

A arquitetura atual atende ao objetivo de validar o MVP, mas pode evoluir.

## 14.1. Automatização do Google Sheets

Atualmente, a atualização pode ser realizada manualmente.

Uma melhoria seria utilizar Google Apps Script para importar automaticamente o CSV e atualizar a planilha.

## 14.2. API REST própria

Futuramente, pode ser interessante substituir a consulta direta ao Google Sheets por uma API REST.

A arquitetura seria:

```
DATASUS
   |
   v
PYTHON
   |
   v
BANCO DE DADOS
   |
   v
API REST
   |
   v
TYPEBOT
```

Isso permitiria:

- Consultas mais rápidas;
- Melhor controle dos filtros;
- Paginação;
- Maior escalabilidade;
- Melhor gerenciamento dos dados.

## 14.3. Pesquisa por linguagem natural

Outra melhoria seria permitir que o usuário faça perguntas como:

- Onde encontro atendimento para parto em Manaus?
- Quais unidades oferecem atendimento cardiológico?
- Onde existe atendimento para pessoas com deficiência?
- Quais unidades ficam próximas do bairro Aleixo?

A IA poderia interpretar a pergunta e convertê-la em filtros de pesquisa.

Entretanto, a resposta deveria continuar baseada nos dados oficiais do CNES, e não no conhecimento geral do modelo.

---

# 15. Checklist de funcionamento

### Extração

- Arquivo `municipios_am.csv` configurado.
- Credenciais SOAP configuradas.
- Script Python executando.
- Consulta por município funcionando.
- Consulta individual por CNES funcionando.
- Endereços formatados corretamente.
- Telefones extraídos corretamente.
- Especialidades extraídas corretamente.
- CSV gerado.

### Google Sheets

- CSV importado.
- Colunas identificadas corretamente.
- Cabeçalhos preservados.
- Dados sem duplicações indevidas.
- Integração com Typebot funcionando.

### Typebot

- Pesquisa por município.
- Pesquisa por bairro.
- Pesquisa por especialidade.
- Exibição de um único resultado.
- Exibição de múltiplos resultados.
- Limite de cinco resultados.
- Nome, endereço e telefone associados corretamente.
- Especialidades apresentadas individualmente.
- Mensagem para resultados vazios.

---

# 16. Resumo da implementação

O MVP utiliza uma arquitetura simples, com ferramentas acessíveis e pouca necessidade de infraestrutura.

| Etapa | Tecnologia    | Função                      |
| ----- | ------------- | --------------------------- |
| 1     | DATASUS/CNES  | Fonte dos dados             |
| 2     | SOAP          | Comunicação com o serviço   |
| 3     | Python        | Extração e processamento    |
| 4     | CSV           | Armazenamento intermediário |
| 5     | Google Sheets | Base consultável            |
| 6     | Typebot       | Interface conversacional    |
| 7     | JavaScript    | Formatação dos resultados   |

**Resultado esperado:** um chatbot capaz de localizar estabelecimentos de saúde e apresentar informações cadastrais e serviços disponíveis, utilizando dados extraídos do CNES.

A arquitetura permite validar a experiência do usuário com baixo custo e, posteriormente, evoluir para uma solução com banco de dados e API própria.