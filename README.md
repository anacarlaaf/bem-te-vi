# Bem-te-vi: base de unidades de saúde do bot

```
CNES (SOAP) ──> pipeline/ ──> Supabase (tabelas + funções de busca) ──> Typebot (chamadas HTTP)
             todo dia às 05:00      └──> Google Sheets (opcional, cópia para a equipe)
```

O pipeline coleta diariamente os estabelecimentos do Amazonas no CNES e grava no Supabase.
O bot (Typebot) não lê tabelas: ele chama três funções do banco, que fazem a busca e devolvem a
resposta já formatada. Hoje o bot responde só sobre **Manaus** (variável `municipio_busca` no
primeiro bloco do fluxo), embora a base tenha o estado inteiro.

```
bem-te-vi/
├── pipeline/                    atualização diária (Python)
│   ├── atualizar.py             ponto de entrada: coleta + travas + grava nos destinos
│   ├── coletar_cnes_am.py       consulta o CNES (62 municípios do AM)
│   ├── normalizacao.py          regras de busca: acento, plural, sinônimos, bairro oficial
│   ├── destino_supabase.py      grava no Supabase (uma transação)
│   └── destino_sheets.py        grava no Google Sheets (opcional)
├── supabase/
│   ├── 001_bemtevi.sql          tabelas, funções de busca e permissões (rodar no SQL Editor)
│   └── teste_local_bootstrap.sql  só para o banco de teste local
├── dados/                       listas editáveis, sem programar
│   ├── municipios_am.csv
│   ├── sinonimos_termos.csv     termo do CNES -> palavras do cidadão ("saude bucal" -> "dentista")
│   └── sinonimos_bairros.csv    grafia/variação -> bairro oficial ("Japiinlandia" -> "Japiim")
├── typebot/
│   ├── typebot-bem-te-vi-supabase.json   fluxo ATUAL: importar no Typebot
│   ├── typebot-bem-te-vi.json            fluxo antigo, lendo a planilha (reserva)
│   ├── export-original/                  export do Typebot usado como base pelos geradores
│   ├── gerar_typebot_supabase.py         gera o fluxo atual
│   ├── gerar_typebot.py                  gera o fluxo de planilha
│   └── simular_bot.py                    simula conversas sem publicar nada
├── scripts/
│   ├── atualizar.sh             alternativa ao GitHub Actions (cron)
│   └── banco_teste.sh           Postgres local para testes
├── docs/                        documentação do MVP e da integração original
└── .github/workflows/           agendamento diário

Gerados na execução (fora do git): saida/ (CSV), logs/ (cron), .cache/ (base e banco de teste)
```

Todos os comandos abaixo são rodados **na raiz do projeto**.

## Colocar no ar (uma vez)

### 1. Criar as tabelas e funções no Supabase

1. Abra o projeto no Supabase. Pode ser o mesmo que já guarda a tabela `interacoes`, porque tudo daqui usa o prefixo `bt_`.
2. **SQL Editor → New query**: cole o conteúdo de `supabase/001_bemtevi.sql` e clique em **Run**.
   O arquivo pode ser rodado de novo sem problema.

Segurança: as tabelas ficam com RLS ligado e sem policies. A chave pública do bot **não lê as
tabelas**; só executa `bt_resolver_bairro`, `bt_buscar_unidades`, `bt_detalhar_unidade` e
`bt_ultima_atualizacao`.

### 2. Configurar e rodar o pipeline

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
```

No `.env`, preencha:

| Variável | Onde achar | Secreta? |
|---|---|---|
| `CNES_SENHA` | manual de integração do CNES (credencial pública `CNES.PUBLICO`) | não |
| `SUPABASE_DB_URL` | *Project Settings → Database → Connection string → **Session pooler*** (troque `[YOUR-PASSWORD]` pela senha do banco) | **sim** |
| `SUPABASE_URL` | *Project Settings → API → Project URL* | não |
| `SUPABASE_PUBLISHABLE_KEY` | *Project Settings → API Keys → publishable* (ou `anon`) | não, vai no fluxo do bot |

```bash
.venv/bin/python -m pipeline.atualizar --simular   # coleta e valida, não grava
.venv/bin/python -m pipeline.atualizar             # grava no Supabase (~3 min)
```

Use o **Session pooler**, não a conexão direta: a conexão direta do Supabase só funciona em IPv6,
e o GitHub Actions não tem IPv6.

### 3. Gerar e importar o fluxo do bot

```bash
.venv/bin/python typebot/gerar_typebot_supabase.py
```

Importe `typebot/typebot-bem-te-vi-supabase.json` no Typebot **como um bot novo**, teste e publique.
O script imprime de onde tirou a URL e a chave. Sem as variáveis no `.env`, ele reaproveita as do
bloco que grava `interacoes` no seu export.

### 4. Agendar no GitHub Actions

1. Suba o projeto para um repositório **privado** no GitHub.
2. *Settings → Secrets and variables → Actions*:
   - **Secrets**: `CNES_SENHA` e `SUPABASE_DB_URL`. Se também for usar a planilha: `GOOGLE_CREDENTIALS_JSON`.
   - **Variables**, só se for usar a planilha: `GOOGLE_SHEET_ID` e `GOOGLE_SHEET_ABA`.
3. *Actions → Atualizar base CNES → Run workflow*: rode uma vez com "Só simular" marcado e depois sem marcar.

O job roda todo dia às 05:00 de Manaus e guarda o CSV como artefato por 14 dias.

> **Risco a verificar no primeiro teste:** alguns serviços `gov.br` bloqueiam IPs de fora do Brasil,
> e os runners do GitHub ficam nos EUA. Se o job falhar com timeout ao consultar o CNES, use o cron.

**Alternativa: cron numa máquina no Brasil.** Adicione ao `crontab -e`:

```
0 5 * * * /caminho/para/bem-te-vi/scripts/atualizar.sh
```

Os logs ficam em `logs/AAAA-MM-DD.log`.

## Segurança da atualização

O pipeline **não grava nada** se:
- algum município não respondeu;
- mais de 5% dos estabelecimentos falharam (`MAX_PERCENT_ERROS`);
- a base nova tem menos de 80% das unidades da atual (`PROPORCAO_MINIMA`);
- as funções SQL normalizam texto diferente do Python. Isso acontece se o `001_bemtevi.sql` estiver desatualizado no Supabase.

Nesses casos o bot continua com os dados do dia anterior, o job falha e o GitHub manda um e-mail.
Quando só alguns estabelecimentos falham, **a linha do dia anterior é reaproveitada**.
No Supabase, a troca acontece numa única transação: quem está consultando vê a base antiga até o
último instante, e se algo falhar no meio nada muda.

Se o Supabase não responder durante uma conversa, o bot diz *"Desculpe, não consegui consultar as
unidades agora..."* e volta ao menu.

## Como a busca funciona

### Bairros: `bt_resolver_bairro`

O pipeline converte o bairro do CNES no **bairro oficial**. Ele corrige as grafias listadas em
`dados/sinonimos_bairros.csv` e junta subdivisões: "Cidade Nova I/II/1" vira "Cidade Nova". O sufixo
só é removido se o que sobra também é um bairro, então "Parque 10" não vira "Parque".

| O que a pessoa digita | O que o bot faz |
|---|---|
| Nome exato ou variação conhecida ("Cidade Nova", "cidade nova 2", "Japiinlândia") | Usa esse bairro, com comparação **exata** |
| Começo de palavra que bate com um só bairro ("japi") | Usa esse bairro |
| Texto que bate com vários bairros ("nova", "são") | **Botões** com até 6 bairros, os com mais unidades primeiro, e "Nenhum desses" |
| Erro de digitação ("japim") | "Não achei o bairro... Você quis dizer:" com botões |
| Nada parecido | Busca de posto: "bairro não encontrado". Busca de especialidade: procura sem bairro |

Como a comparação final é exata, **"Cidade Nova" nunca traz "Nova Cidade"**.

### Termos: `bt_buscar_unidades`

O texto digitado é normalizado assim: minúsculas, sem acento e sem pontuação. Palavras como "quero",
"de" e "um" são ignoradas, e plurais simples são reduzidos ("psicólogos" vira "psicologo").
Uma unidade é encontrada se **todas as palavras** aparecem, em qualquer ordem, no conjunto de
nome + especialidades + tipo de unidade + **sinônimos** de `dados/sinonimos_termos.csv`.
Se nada for encontrado, uma segunda tentativa tolera erro de digitação ("dentsta" acha dentistas).

Ordem de tentativa: no bairro → sem bairro (só na busca por especialidade) → nada encontrado.

### Unidade pelo nome: `bt_detalhar_unidade`

Procura pelo nome normalizado, com tolerância a erro de digitação ("maternidade balbna").

### Editar sinônimos

Edite `dados/sinonimos_termos.csv` ou `dados/sinonimos_bairros.csv`. A próxima atualização diária
aplica a mudança. **Não precisa mexer no Typebot nem no SQL.** As linhas marcadas como
`popular (conferir)` são palpites que alguém que conhece Manaus deve validar.

### Mudar as regras de normalização

As regras estão em dois lugares que precisam ficar iguais: `pipeline/normalizacao.py` e as funções
`bt_sem_acento` e `bt_normalizar_busca` em `supabase/001_bemtevi.sql`. Se mudar um, mude o outro e
reaplique o SQL. O pipeline confere a equivalência antes de cada carga.

## Testar sem publicar

```bash
scripts/banco_teste.sh iniciar                     # Postgres local com o SQL aplicado
SUPABASE_DB_URL=postgresql://postgres@localhost:54329/bemtevi GOOGLE_SHEET_ID= \
    .venv/bin/python -m pipeline.atualizar         # carga real do CNES no banco local
.venv/bin/python typebot/simular_bot.py "Encontrar um posto" "nova" "Nova Cidade"
scripts/banco_teste.sh parar
```

O simulador percorre o fluxo como o Typebot e executa as chamadas no banco local, com as mesmas
permissões da chave pública. Para simular o fluxo antigo de planilha:
`SIMULADOR_FLUXO=planilha .venv/bin/python typebot/simular_bot.py ...`, que usa `.cache/base.csv`.

## Atualizar o fluxo depois de editar o bot no Typebot

Exporte o bot, salve em `typebot/export-original/` com o mesmo nome de arquivo e rode
`typebot/gerar_typebot_supabase.py`. Os seus textos e mudanças são preservados. Só os blocos de
busca são substituídos.

## Google Sheets (opcional)

Para manter uma cópia legível para a equipe, configure `GOOGLE_SHEET_ID` e as credenciais da conta de serviço:
1. Ative a Google Sheets API num projeto do Google Cloud.
2. Crie uma conta de serviço e gere a chave JSON.
3. Compartilhe a planilha com o e-mail da conta como Editor.

O pipeline grava os dois destinos. A aba `bairros` é criada com gid fixo **7001**, porque o fluxo
antigo depende disso.

## Pendências

- Os endpoints do CNES são os de **homologação** (`servicoshm`). Para trocar, defina
  `CNES_URL_MUNICIPIO` e `CNES_URL_ESTABELECIMENTO`.
- Horário de funcionamento e salas de vacina não são retornados por esses serviços.
- `bt_detalhar_unidade` devolve só a unidade mais parecida. Se houver várias com nomes parecidos,
  a pessoa não escolhe.
# bem-te-vi
