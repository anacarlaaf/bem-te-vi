-- =====================================================================
-- Bem-te-vi: base de unidades de saúde (CNES) e funções de busca do bot
--
-- Como aplicar: Supabase > SQL Editor > cole este arquivo inteiro > Run.
-- Pode rodar de novo sem problema (é idempotente).
--
-- Segurança:
--   - As tabelas têm RLS ligado e NENHUMA policy: a chave pública
--     (anon/publishable) não lê nem altera as tabelas diretamente.
--   - O bot só consegue chamar 3 funções: bt_resolver_bairro,
--     bt_buscar_unidades e bt_detalhar_unidade (SECURITY DEFINER).
--   - Quem grava é o pipeline, conectado com a senha do banco.
--
-- As regras de normalização (bt_sem_acento, bt_normalizar_busca) precisam
-- ser iguais às de pipeline/normalizacao.py. O pipeline confere isso antes
-- de cada carga e aborta se divergirem.
-- =====================================================================

create schema if not exists extensions;
create extension if not exists unaccent with schema extensions;
create extension if not exists pg_trgm with schema extensions;
create extension if not exists fuzzystrmatch with schema extensions;

-- ---------------------------------------------------------------------
-- Tabelas
-- ---------------------------------------------------------------------

create table if not exists public.bt_unidades (
    cnes                   text primary key,
    nome                   text not null default '',
    endereco               text not null default '',
    telefone               text not null default '',
    especialidades         text not null default '',
    municipio              text not null default '',
    bairro                 text not null default '',
    bairro_oficial         text not null default '',
    tipo_unidade           text not null default '',
    data_atualizacao_cnes  text not null default '',
    atende_sus             boolean not null default false,
    busca_nome             text not null default '',
    busca_servicos         text not null default '',
    busca_bairro           text not null default ''
);

create index if not exists bt_unidades_municipio_bairro
    on public.bt_unidades (municipio, busca_bairro);
create index if not exists bt_unidades_servicos_trgm
    on public.bt_unidades using gin (busca_servicos extensions.gin_trgm_ops);
create index if not exists bt_unidades_nome_trgm
    on public.bt_unidades using gin (busca_nome extensions.gin_trgm_ops);

create table if not exists public.bt_bairros (
    municipio     text not null,
    bairro        text not null,          -- nome oficial, para exibir
    busca_bairro  text not null,          -- sem acento, minúsculas
    variantes     text[] not null default '{}',
    unidades      integer not null default 0,
    primary key (municipio, busca_bairro)
);

create table if not exists public.bt_meta (
    chave  text primary key,
    valor  text not null
);

alter table public.bt_unidades enable row level security;
alter table public.bt_bairros  enable row level security;
alter table public.bt_meta     enable row level security;

-- ---------------------------------------------------------------------
-- Normalização (espelho de pipeline/normalizacao.py)
-- ---------------------------------------------------------------------

create or replace function public.bt_sem_acento(t text)
returns text language sql stable
set search_path = public, extensions
as $$
    select btrim(regexp_replace(lower(extensions.unaccent(coalesce(t, ''))), '\s+', ' ', 'g'))
$$;

create or replace function public.bt_radical(p text)
returns text language sql immutable
as $$
    select case
        when length(p) > 4 and p like '%oes' then left(p, -3) || 'ao'
        when length(p) > 4 and p like '%ais' then left(p, -3) || 'al'
        when length(p) > 3 and p like '%s' and p not like '%ss' then left(p, -1)
        else p
    end
$$;

create or replace function public.bt_normalizar_busca(t text)
returns text language sql stable
set search_path = public, extensions
as $$
    select coalesce(string_agg(public.bt_radical(w), ' ' order by ord), '')
    from unnest(regexp_split_to_array(
             btrim(regexp_replace(public.bt_sem_acento(t), '[^a-z0-9]+', ' ', 'g')), ' '
         )) with ordinality as x(w, ord)
    where w <> ''
      and w <> all (array[
          'a', 'o', 'as', 'os', 'um', 'uma', 'uns', 'umas', 'de', 'do', 'da',
          'dos', 'das', 'e', 'em', 'no', 'na', 'nos', 'nas', 'para', 'pra', 'pro',
          'com', 'por', 'que', 'quero', 'queria', 'preciso', 'procuro', 'gostaria',
          'meu', 'minha', 'bairro', 'unidade'
      ])
$$;

-- Lista formatada para o chat (mesmo formato do fluxo antigo)
create or replace function public.bt_formatar_lista(p_unidades jsonb, p_total integer)
returns text language sql immutable
as $$
    select coalesce(string_agg(
               '🏥 ' || coalesce(nullif(u->>'nome', ''), 'Nome não informado') || E'\n' ||
               '📍 ' || coalesce(nullif(u->>'endereco', ''), 'Endereço não informado') || E'\n' ||
               '📞 ' || coalesce(nullif(u->>'telefone', ''), 'Telefone não informado'),
               E'\n\n' order by ord), '')
           || case when p_total > jsonb_array_length(p_unidades)
                   then E'\n\nMostrando ' || jsonb_array_length(p_unidades) || ' de '
                        || p_total || ' unidades encontradas.'
                   else '' end
    from jsonb_array_elements(p_unidades) with ordinality as x(u, ord)
$$;

-- ---------------------------------------------------------------------
-- 1) Reconhecer o bairro digitado
--    status: ok | escolher | nao_encontrado
-- ---------------------------------------------------------------------

create or replace function public.bt_resolver_bairro(p_municipio text, p_texto text)
returns jsonb language plpgsql stable security definer
set search_path = public, extensions
as $$
declare
    v_digitado  text;
    v_base      text;
    v_achado    record;
    v_qtd       integer;
    v_opcoes    jsonb;
    v_limite    integer;
begin
    v_digitado := regexp_replace(public.bt_sem_acento(p_texto), '^(bairro|conjunto|conj|cj)\s+', '');
    if v_digitado = '' then
        return jsonb_build_object('status', 'nao_encontrado', 'busca', '-', 'nome', '',
                                  'opcoes', '[]'::jsonb, 'pergunta', '');
    end if;
    v_base := regexp_replace(v_digitado, '\s+(i{1,3}|iv|[1-4])$', '');

    -- 1) nome exato ou variação conhecida ("cidade nova 2", "japiinlandia")
    select * into v_achado
    from public.bt_bairros b
    where b.municipio = p_municipio
      and (b.busca_bairro in (v_digitado, v_base) or b.variantes && array[v_digitado, v_base])
    order by b.unidades desc
    limit 1;
    if found then
        return jsonb_build_object('status', 'ok', 'busca', v_achado.busca_bairro,
                                  'nome', v_achado.bairro, 'opcoes', '[]'::jsonb, 'pergunta', '');
    end if;

    -- 2) parcial: cada palavra digitada é começo de uma palavra do bairro
    --    ("nova" -> Cidade Nova, Nova Cidade, Nova Esperança...)
    select coalesce(jsonb_agg(jsonb_build_object('bairro', c.bairro, 'busca', c.busca_bairro)
                              order by c.unidades desc, c.bairro), '[]'::jsonb)
      into v_opcoes
    from public.bt_bairros c
    where length(v_digitado) >= 3
      and c.municipio = p_municipio
      and exists (
          select 1 from unnest(c.busca_bairro || c.variantes) as nome
          where not exists (
              select 1 from unnest(string_to_array(v_digitado, ' ')) as p
              where not exists (
                  select 1 from unnest(string_to_array(nome, ' ')) as w
                  where w like p || '%'
              )
          )
      );
    v_qtd := jsonb_array_length(v_opcoes);

    if v_qtd = 1 then
        return jsonb_build_object('status', 'ok', 'busca', v_opcoes->0->>'busca',
                                  'nome', v_opcoes->0->>'bairro', 'opcoes', '[]'::jsonb, 'pergunta', '');
    end if;

    if v_qtd > 1 then
        return jsonb_build_object('status', 'escolher', 'busca', '-', 'nome', '',
            'opcoes', (select jsonb_agg(e->'bairro' order by ord)
                       from jsonb_array_elements(v_opcoes) with ordinality as x(e, ord)
                       where ord <= 6) || '["Nenhum desses"]'::jsonb,
            'pergunta', 'Encontrei mais de um bairro parecido com "' || btrim(p_texto) || '". Qual é o seu?');
    end if;

    -- 3) erro de digitação ("japim" -> Japiim)
    v_limite := case when length(v_digitado) <= 5 then 1 else 2 end;
    select jsonb_agg(bairro order by unidades desc, bairro) into v_opcoes
    from (
        select b.bairro, b.unidades
        from public.bt_bairros b
        where b.municipio = p_municipio
          and exists (select 1 from unnest(b.busca_bairro || b.variantes) as nome
                      where extensions.levenshtein(v_digitado, nome) <= v_limite)
        order by b.unidades desc, b.bairro
        limit 6
    ) t;

    if v_opcoes is null then
        return jsonb_build_object('status', 'nao_encontrado', 'busca', '-', 'nome', '',
                                  'opcoes', '[]'::jsonb, 'pergunta', '');
    end if;
    return jsonb_build_object('status', 'escolher', 'busca', '-', 'nome', '',
        'opcoes', v_opcoes || '["Nenhum desses"]'::jsonb,
        'pergunta', 'Não achei o bairro "' || btrim(p_texto) || '". Você quis dizer:');
end;
$$;

-- ---------------------------------------------------------------------
-- 2) Buscar unidades
--    p_bairro: busca_bairro vindo de bt_resolver_bairro ('-' ou vazio = sem bairro)
--    p_termo:  texto livre da especialidade (vazio = qualquer serviço)
--    p_so_sus: 'sim' para só SUS
--    modo: bairro | sem_bairro | nenhum
-- ---------------------------------------------------------------------

create or replace function public.bt_buscar_unidades(
    p_municipio text,
    p_bairro    text default '',
    p_termo     text default '',
    p_so_sus    text default 'nao',
    p_limite    integer default 5
)
returns jsonb language plpgsql stable security definer
set search_path = public, extensions
as $$
declare
    v_termo   text := public.bt_normalizar_busca(p_termo);
    v_bairro  text := nullif(nullif(btrim(coalesce(p_bairro, '')), '-'), '');
    v_sus     boolean := lower(coalesce(p_so_sus, '')) in ('sim', 'true', '1', 's');
    v_tem_termo boolean := btrim(coalesce(p_termo, '')) <> '';
    v_limite  integer := least(greatest(coalesce(p_limite, 5), 1), 20);
    v_fuzzy   boolean;
    v_modo    text;
    v_total   integer;
    v_lista   jsonb;
begin
    -- termo digitado que só tinha palavras ignoradas ("quero")
    if v_tem_termo and v_termo = '' then
        return jsonb_build_object('modo', 'nenhum', 'total', 0, 'texto', '', 'unidades', '[]'::jsonb);
    end if;

    -- 1ª passada: todas as palavras do termo; 2ª: tolerando erro de digitação
    foreach v_fuzzy in array array[false, true] loop
        exit when v_fuzzy and not v_tem_termo;
        foreach v_modo in array array['bairro', 'sem_bairro'] loop
            continue when v_modo = 'bairro' and v_bairro is null;
            continue when v_modo = 'sem_bairro' and not v_tem_termo;   -- posto sem bairro: não lista a cidade toda

            with achados as (
                select u.*
                from public.bt_unidades u
                where u.municipio = p_municipio
                  and (not v_sus or u.atende_sus)
                  and (v_modo = 'sem_bairro' or u.busca_bairro = v_bairro)
                  and (not v_tem_termo
                       -- cada palavra do termo aparece, em qualquer ordem
                       or (not v_fuzzy and not exists (
                               select 1 from unnest(string_to_array(v_termo, ' ')) as w
                               where u.busca_servicos not like '%' || w || '%'))
                       or (v_fuzzy and extensions.word_similarity(v_termo, u.busca_servicos) >= 0.75))
            )
            select count(*),
                   (select coalesce(jsonb_agg(jsonb_build_object(
                               'cnes', a.cnes, 'nome', a.nome, 'endereco', a.endereco,
                               'telefone', a.telefone, 'bairro', a.bairro_oficial,
                               'atende_sus', a.atende_sus) order by a.nome), '[]'::jsonb)
                    from (select * from achados order by nome limit v_limite) a)
              into v_total, v_lista
            from achados;

            if v_total > 0 then
                return jsonb_build_object('modo', v_modo, 'total', v_total,
                    'aproximado', v_fuzzy, 'unidades', v_lista,
                    'texto', public.bt_formatar_lista(v_lista, v_total));
            end if;
        end loop;
    end loop;

    return jsonb_build_object('modo', 'nenhum', 'total', 0, 'texto', '', 'unidades', '[]'::jsonb);
end;
$$;

-- ---------------------------------------------------------------------
-- 3) Detalhar uma unidade pelo nome (com especialidades)
-- ---------------------------------------------------------------------

create or replace function public.bt_detalhar_unidade(p_municipio text, p_nome text)
returns jsonb language plpgsql stable security definer
set search_path = public, extensions
as $$
declare
    v_nome  text := public.bt_normalizar_busca(p_nome);
    v_u     public.bt_unidades;
    v_esp   text;
begin
    if v_nome = '' then
        return jsonb_build_object('encontrado', 'nao', 'texto', '');
    end if;

    select * into v_u from public.bt_unidades u
    where u.municipio = p_municipio and u.busca_nome like '%' || v_nome || '%'
    order by (u.busca_nome = v_nome) desc, length(u.nome), u.nome
    limit 1;

    if not found then
        select * into v_u from public.bt_unidades u
        where u.municipio = p_municipio
          and extensions.word_similarity(v_nome, u.busca_nome) >= 0.6
        order by extensions.word_similarity(v_nome, u.busca_nome) desc, u.nome
        limit 1;
    end if;

    if not found then
        return jsonb_build_object('encontrado', 'nao', 'texto', '');
    end if;

    select coalesce(string_agg('• ' || btrim(e), E'\n'), 'Não informado') into v_esp
    from unnest(string_to_array(v_u.especialidades, '|')) as e
    where btrim(e) <> '';

    return jsonb_build_object(
        'encontrado', 'sim',
        'cnes', v_u.cnes,
        'texto', '🏥 ' || coalesce(nullif(v_u.nome, ''), 'Nome não informado') || E'\n' ||
                 '📍 ' || coalesce(nullif(v_u.endereco, ''), 'Endereço não informado') || E'\n' ||
                 '📞 ' || coalesce(nullif(v_u.telefone, ''), 'Telefone não informado') ||
                 E'\n\n🩺 Especialidades:\n' || v_esp
    );
end;
$$;

-- ---------------------------------------------------------------------
-- 4) Data da última atualização (para o bot exibir)
-- ---------------------------------------------------------------------

create or replace function public.bt_ultima_atualizacao()
returns jsonb language sql stable security definer
set search_path = public
as $$
    select coalesce(jsonb_object_agg(chave, valor), '{}'::jsonb) from public.bt_meta
$$;

-- ---------------------------------------------------------------------
-- Permissões: o bot (anon) só executa as funções públicas
-- ---------------------------------------------------------------------

revoke all on public.bt_unidades, public.bt_bairros, public.bt_meta from anon, authenticated;

revoke execute on function
    public.bt_sem_acento(text), public.bt_radical(text), public.bt_normalizar_busca(text),
    public.bt_formatar_lista(jsonb, integer),
    public.bt_resolver_bairro(text, text),
    public.bt_buscar_unidades(text, text, text, text, integer),
    public.bt_detalhar_unidade(text, text),
    public.bt_ultima_atualizacao()
from public, anon, authenticated;

grant execute on function
    public.bt_resolver_bairro(text, text),
    public.bt_buscar_unidades(text, text, text, text, integer),
    public.bt_detalhar_unidade(text, text),
    public.bt_ultima_atualizacao()
to anon, authenticated;
