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
│   ├── atualizar.sh             roda a atualização e grava o log (usado pelo agendamento)
│   ├── vm/                      instalação e agendamento numa VM (systemd)
│   └── banco_teste.sh           Postgres local para testes
└── docs/                        documentação do MVP e da integração original

Gerados na execução (fora do git): saida/ (CSV), logs/, .cache/ (base e banco de teste)
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
e VMs na nuvem (inclusive a da Oracle) normalmente só têm IPv4.

### 3. Gerar e importar o fluxo do bot

```bash
.venv/bin/python typebot/gerar_typebot_supabase.py
```

Importe `typebot/typebot-bem-te-vi-supabase.json` no Typebot **como um bot novo**, teste e publique.
O script imprime de onde tirou a URL e a chave. Sem as variáveis no `.env`, ele reaproveita as do
bloco que grava `interacoes` no seu export.

### 4. Agendar numa VM da Oracle Cloud

**Criar a VM** (console da Oracle Cloud → *Compute → Instances → Create instance*):
- **Região no Brasil** (São Paulo ou Vinhedo). Isso evita bloqueio de IP estrangeiro pelos serviços `gov.br`.
- **Imagem:** Ubuntu 22.04 ou 24.04.
- **Formato:** qualquer um do *Always Free* serve. O pipeline usa pouca memória e roda cerca de 3 minutos por dia.
- **Chave SSH:** use a sua ou baixe a gerada. Não precisa abrir nenhuma porta além da 22 (SSH), porque
  a VM só faz conexões de saída (CNES e Supabase).

> **Atenção:** a Oracle pode recuperar VMs *Always Free* que ficam ociosas por muito tempo, e um job
> de 3 minutos por dia parece ocioso. Para evitar isso, converta a conta para *Pay As You Go*. Os
> recursos *Always Free* continuam gratuitos; confirme as regras atuais no site da Oracle.

**Instalar o projeto na VM** (no seu computador, troque `IP_DA_VM`):

```bash
ssh ubuntu@IP_DA_VM
git clone https://github.com/anacarlaaf/bem-te-vi.git   # repositório privado: use um token ou deploy key
exit
scp .env ubuntu@IP_DA_VM:bem-te-vi/.env                  # leva as credenciais sem passar pelo git
```

No `.env` da VM, a `SUPABASE_DB_URL` **precisa ser a do Session pooler** (veja o passo 2).

```bash
ssh ubuntu@IP_DA_VM
cd bem-te-vi
bash scripts/vm/instalar.sh            # pacotes, Python, agendamento diário às 05:00 de Manaus
scripts/atualizar.sh --simular         # teste: coleta e valida, não grava
sudo systemctl start bemtevi-atualizar.service   # primeira carga de verdade
```

**Acompanhar:**

| Para | Comando na VM |
|---|---|
| Ver a próxima execução | `systemctl list-timers bemtevi-atualizar.timer` |
| Ver o resultado da última | `journalctl -u bemtevi-atualizar.service -n 50 --no-pager` |
| Ver o log de um dia | `cat logs/AAAA-MM-DD.log` |
| Atualizar o código ou os sinônimos | `git pull && bash scripts/vm/instalar.sh` |

**Aviso de falha (recomendado):** a VM não manda e-mail sozinha. Crie um check gratuito no
[healthchecks.io](https://healthchecks.io) com período de 1 dia e coloque a URL dele em
`HEALTHCHECK_URL` no `.env` da VM. Ele avisa por e-mail se a atualização falhar ou não rodar.

Sem a VM, o mesmo script roda via cron em qualquer máquina Linux:
`0 5 * * * /caminho/para/bem-te-vi/scripts/atualizar.sh`.

### Com que frequência rodar

Os dados do CNES mudam devagar e chegam em lotes. Na análise de 11/11/2026, considerando a data de
atualização de cada estabelecimento:
- cerca de 14 atualizações por dia útil no estado inteiro, e quase nenhuma no fim de semana;
- 0,3% da base atualizada na última semana, 9,5% no último mês;
- nenhuma data posterior a 05/11, mesmo com dias úteis depois. Ou seja, o serviço publica mudanças
  em lotes, não em tempo real.

**Recomendação: uma vez por dia.** O custo é baixo (cerca de 3 minutos), e uma mudança publicada chega ao bot em
no máximo 24 horas. O serviço não permite buscar só o que mudou, então cada execução consulta todos
os estabelecimentos. Rodar de hora em hora sobrecarregaria o serviço do Ministério sem ganho real.

Cada execução registra no log e na tabela `bt_meta` (`unidades_novas`, `unidades_removidas`,
`unidades_alteradas`) o que mudou de fato. Depois de algumas semanas, esse histórico mostra o ritmo
real. Se quase todos os dias registrarem zero, dá para passar para segunda a sexta (no
`scripts/vm/bemtevi-atualizar.timer`, use `OnCalendar=Mon..Fri *-*-* 05:00:00 America/Manaus`).

## Segurança da atualização

O pipeline **não grava nada** se:
- algum município não respondeu;
- mais de 5% dos estabelecimentos falharam (`MAX_PERCENT_ERROS`);
- a base nova tem menos de 80% das unidades da atual (`PROPORCAO_MINIMA`);
- as funções SQL normalizam texto diferente do Python. Isso acontece se o `001_bemtevi.sql` estiver desatualizado no Supabase.

Nesses casos o bot continua com os dados do dia anterior e a execução termina com erro, que fica no
log e dispara o aviso do healthchecks.io, se configurado.
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
