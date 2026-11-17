# Shadow API

API central do painel Shadow Salas para criação de salas. O cliente faz **uma única requisição ao Shadow API**; o backend seleciona automaticamente o provedor de acordo com o modo enviado. Os tokens das APIs externas ficam configurados somente no ambiente do servidor e nunca precisam ser enviados pelo cliente.

## Como funciona a seleção do provedor

O backend usa o campo `config_type` do JSON recebido:

| Modo solicitado | Provedor inicial |
| --- | --- |
| `br_padrao` | Lest Nort |
| Modos AP compatíveis | Nix |
| Modos AP compatíveis, se a Nix responder com erro HTTP 4xx | Lest Nort como alternativa, se configurada |

Modos reconhecidos para roteamento pela Lest Nort: `ap_padrao`, `gelo_inf`, `tatico`, `ap_fullcapa`, `capa_3`, `ap_uxd`, `ap_7r` e `br_padrao`.

Para os modos AP, a Nix é tentada primeiro. Se a resposta for um erro HTTP 4xx (incluindo 429), o backend pode tentar a Lest Nort. Para o modo `br_padrao`, a requisição vai diretamente para a Lest Nort.

**Proteção contra salas duplicadas:** se ocorrer timeout/falha de conexão ou resposta HTTP 5xx, o backend não repete a criação em outro provedor, pois a primeira API pode ter criado a sala antes da falha de resposta. Nesses casos, a API retorna o erro para o cliente.

A resposta inclui o campo `provider`, indicando qual provedor respondeu à tentativa de criação.

## Configuração no Render

Configure os tokens somente nas Environment Variables do serviço:

**Obrigatórias para os provedores:**
- `NIX_API_TOKEN`: token privado da Nix.
- `LESTNORT_API_TOKEN`: token privado da Lest Nort.

**URLs (opcionais, com estes padrões):**
- `NIX_BASE_URL=https://salas.nixbot.vip`
- `LESTNORT_BASE_URL=https://lestnortff.shardweb.app/api/v1`

Não coloque tokens em arquivos públicos, no frontend, em exemplos de requisição ou no Discord. O cliente autentica apenas com sua chave Shadow (`X-API-Key`).

Outras variáveis necessárias ao funcionamento do painel/API:
- `SUPABASE_URL`
- `SUPABASE_KEY` (service role/secret key, somente no servidor)
- `SECRET_KEY`
- `PANEL_USERNAME`
- `PANEL_PASSWORD_HASH`
- `DISCORD_CLIENT_ID`
- `DISCORD_CLIENT_SECRET`
- `DISCORD_REDIRECT_URI=https://shadow-panel-web.onrender.com/auth/discord/callback`

Opcional:
- `ADMIN_DISCORD_USER_IDS`: IDs numéricos dos usuários Discord autorizados como administradores, separados por vírgula.

Start command do Render:

```bash
gunicorn api.app:app
```

## Requisição do cliente

Endpoint:

```http
POST /v1/rooms
X-API-Key: sh_SUA_CHAVE
Content-Type: application/json
```

O cliente envia o modo e os parâmetros da sala. Não envia token Nix nem token Lest Nort.

Exemplo de sala BR:

```json
{
  "config_type": "br_padrao",
  "equipe": "squad",
  "espectadores": 30
}
```

A Lest Nort também aceita os campos opcionais `carregamento` e `1500_ouro`, quando aplicáveis ao modo solicitado.

Exemplo de modo AP:

```json
{
  "config_type": "ap_padrao"
}
```

Use os demais campos exigidos pelo modo escolhido. O backend encaminha o JSON ao provedor selecionado e devolve a resposta, incluindo `provider`.

## Respostas e erros

- Sucesso: resposta do provedor com o campo `provider`.
- `503`: nenhum provedor configurado/compatível para o modo solicitado.
- `502`: falha de conexão ou timeout com o provedor; a criação não é repetida automaticamente para evitar duplicidade.
- Erros HTTP do provedor: devolvidos conforme a resposta recebida, respeitando a regra de fallback descrita acima.

Envie uma única requisição por criação. Não repita automaticamente uma chamada que terminou em timeout ou erro 5xx; confirme o estado da sala no provedor/painel antes de tentar novamente.
