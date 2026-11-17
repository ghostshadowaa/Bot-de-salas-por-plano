# Shadow API

Camada de API para clientes criarem salas através das APIs Nix e Lest Nort sem receber tokens privados.

## Render

Start command:

gunicorn api.app:app

Variáveis obrigatórias:

- SUPABASE_URL
- SUPABASE_KEY (service role/secret key, somente no Render)
- NIX_API_TOKEN
- SECRET_KEY
- PANEL_USERNAME
- PANEL_PASSWORD_HASH
- DISCORD_CLIENT_ID
- DISCORD_CLIENT_SECRET
- DISCORD_REDIRECT_URI=https://shadow-panel-web.onrender.com/auth/discord/callback

Opcionais:
- ADMIN_DISCORD_USER_IDS (IDs de usuário Discord autorizados como administradores, separados por vírgula; inclua o ID da conta proprietária do painel)
- NIX_ROOMS_URL=https://salas.nixbot.vip/rooms
- LESTNORT_BASE_URL=https://lestnortff.shardweb.app/api/v1
- LESTNORT_API_TOKEN (opcional; token pessoal de Minha API no painel Lest Nort)
- NIX_AUTH_HEADER=Authorization
- NIX_AUTH_PREFIX=Bearer 

## Uso do cliente

POST /v1/rooms

Header:
X-API-Key: sh_...

Body:
JSON compatível com o modo selecionado. A Lest Nort também aceita `equipe`, `espectadores`, `carregamento` e `1500_ouro`.

A resposta do provedor escolhido é devolvida ao cliente, incluindo o campo `provider`.
