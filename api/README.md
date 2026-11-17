# Shadow API

# Shadow API

Camada de API para clientes criarem salas através das APIs Nix e Lest Nort sem receber tokens privados.

## Render

Start command:

gunicorn api.app:app

Variáveis obrigatórias:

- SUPABASE_URL
- SUPABASE_KEY (service role/secret key, somente no Render)
- NIX_API_TOKEN
- LESTNORT_API_TOKEN (token pessoal de Minha API no painel Lest Nort)
- SECRET_KEY
- PANEL_USERNAME
- PANEL_PASSWORD_HASH

Opcionais:

- NIX_ROOMS_URL=https://salas.nixbot.vip/rooms
- LESTNORT_BASE_URL=https://lestnortff.shardweb.app/api/v1
- NIX_AUTH_HEADER=Authorization
- NIX_AUTH_PREFIX=Bearer 

## Uso do cliente

POST /v1/rooms

Header:
X-API-Key: sh_...

Body:
o mesmo JSON aceito pelo endpoint /rooms da Nix.

A resposta do provedor escolhido é devolvida ao cliente, incluindo o campo `provider`.
