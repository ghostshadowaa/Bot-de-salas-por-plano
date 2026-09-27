# Shadow Salas API

API direta para receber eventos do bot.

## Endpoints

- POST /api/v1/venda
- POST /api/v1/cargo
- GET /health

## Autenticação

Defina SHADOW_API_KEY no Render. O bot deverá enviar:

Authorization: Bearer SUA_CHAVE

## Exemplo de venda

{
  "evento": "venda",
  "id": "123456",
  "produto": "Plano Mensal",
  "valor": 39.00,
  "cliente": {
    "id": "987654",
    "nome": "Cliente"
  },
  "quantidade": 1,
  "status": "aprovado"
}

## Exemplo de cargo

{
  "evento": "cargo",
  "usuario_id": "987654",
  "cargo_id": "123456789",
  "cargo_nome": "Cliente Mensal",
  "acao": "adicionado"
}
