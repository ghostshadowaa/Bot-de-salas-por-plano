# Shadow API

Camada de API para clientes criarem salas através da API Nix sem receber o token Nix.

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

Opcionais:

- NIX_ROOMS_URL=https://salas.nixbot.vip/rooms
- NIX_AUTH_HEADER=Authorization
- NIX_AUTH_PREFIX=Bearer 

## Uso do cliente

POST /v1/rooms

Header:
X-API-Key: sh_...

Body:
o mesmo JSON aceito pelo endpoint /rooms da Nix.

A resposta da Nix é devolvida ao cliente.
