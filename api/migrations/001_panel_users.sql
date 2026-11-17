-- Execute no SQL Editor do Supabase antes de usar o novo cadastro do Shadow Panel.
-- A tabela só deve ser acessada pelo backend com SUPABASE_KEY (service role).
create extension if not exists pgcrypto;

create table if not exists public.panel_users (
    id uuid primary key default gen_random_uuid(),
    username text not null,
    email text not null,
    password_hash text not null,
    active boolean not null default true,
    is_admin boolean not null default false,
    created_at timestamptz not null default now()
);

create unique index if not exists panel_users_username_lower_uq
    on public.panel_users (lower(username));

create unique index if not exists panel_users_email_lower_uq
    on public.panel_users (lower(email));

alter table public.panel_users enable row level security;

-- Não crie policies públicas para esta tabela.
-- O backend usa a chave service-role e valida a sessão em cada rota.

-- Após o usuário autorizado concluir o cadastro, conceda acesso administrativo:
-- update public.panel_users set is_admin = true where lower(email) = lower('email-do-dono@exemplo.com');
-- Além disso, configure ADMIN_EMAILS no Render com esse mesmo endereço.
-- O painel administrativo exige as duas condições: is_admin=true e e-mail na allowlist.
