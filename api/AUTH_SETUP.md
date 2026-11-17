# Configuração do login do Shadow Panel

O painel usa cadastro e login próprios com usuário/e-mail e senha. O Discord OAuth e o login administrativo antigo por senha global foram desativados.

## 1. Criar a tabela

No Supabase, abra **SQL Editor** e execute o conteúdo de `migrations/001_panel_users.sql`.

A tabela `panel_users` guarda usuário, e-mail e hash da senha. A senha original não é armazenada. Não crie políticas RLS públicas para essa tabela: o backend acessa com a chave privada `SUPABASE_KEY`.

## 2. Variáveis no Render

Mantenha `SUPABASE_URL`, `SUPABASE_KEY` e `SECRET_KEY` configuradas. Adicione:

- `ADMIN_EMAILS`: e-mails autorizados a entrar no painel administrativo, separados por vírgula.

Exemplo:
```text
ADMIN_EMAILS=proprietario@exemplo.com
```

Use a chave service-role/secret do Supabase somente no Render. Nunca a coloque no navegador ou no repositório.

## 3. Autorizar o proprietário

1. Acesse `/register` e crie a conta com o e-mail que será o administrador.
2. No Supabase SQL Editor, execute, substituindo pelo e-mail cadastrado:

```sql
update public.panel_users
set is_admin = true
where lower(email) = lower('proprietario@exemplo.com');
```

3. Confirme que o mesmo endereço está em `ADMIN_EMAILS` no Render.
4. Faça logout e entre novamente.

**Segurança:** uma conta só recebe acesso administrativo se o registro tiver `is_admin = true` e o e-mail também estiver na allowlist `ADMIN_EMAILS`. Contas comuns criadas no cadastro acessam somente o dashboard de usuário; não podem abrir `/admin`.

## 4. Criar contas comuns

O usuário pode acessar `/register` e informar nome de usuário, e-mail e senha com pelo menos 8 caracteres. O login aceita nome de usuário ou e-mail.

## 5. Sessão

A sessão usa cookie HTTP-only, Secure e SameSite=Lax, com duração de até 30 dias. O botão de sair encerra a sessão.
