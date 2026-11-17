# Shadow API — documentação de criação de salas

A Shadow API é a única API que o cliente precisa chamar. O backend recebe a requisição, valida a chave Shadow, reserva o crédito e escolhe automaticamente o provedor de salas. **Nunca envie token Nix ou Lest Nort no cliente.**

## 1. Endpoint público

```http
POST https://shadow-panel-web.onrender.com/v1/rooms
X-API-Key: SUA_CHAVE_SHADOW
Content-Type: application/json
```

- Método: `POST`
- Autenticação: chave Shadow no header `X-API-Key`
- Corpo: JSON
- Custo atual: R$ 0,05 por criação concluída com sucesso.
- O crédito é reservado antes da chamada ao provedor e devolvido quando a criação falha.

A chave Shadow é diferente dos tokens privados das APIs externas. O cliente usa somente a chave Shadow.

## 2. Como o backend escolhe o provedor

O backend observa o campo `config_type`:

| Requisição recebida | Roteamento atual da Shadow API |
| --- | --- |
| `br_padrao` | Lest Nort |
| Modo AP compatível | Nix primeiro |
| Modo AP compatível, se a Nix responder com HTTP 4xx | Lest Nort como alternativa, se configurada |

Modos AP reconhecidos no roteamento: `ap_padrao`, `gelo_inf`, `tatico`, `ap_fullcapa`, `capa_3`, `ap_uxd` e `ap_7r`.

**Observação importante sobre BR:** a documentação pública da Nix também descreve criação com `br_padrao`, mas a regra atualmente implementada na Shadow API encaminha esse modo diretamente para a Lest Nort. Portanto, para usar BR pelo painel, envie `config_type: "br_padrao"` ao endpoint Shadow; não chame a Nix diretamente.

### Fallback e prevenção de duplicidade

- Resposta HTTP 2xx: a criação é considerada concluída e o backend devolve a resposta com `provider`.
- Resposta HTTP 4xx da Nix em modo AP: o backend pode tentar a Lest Nort.
- Timeout, falha de conexão ou resposta HTTP 5xx: o backend não tenta criar novamente em outro provedor, porque a primeira API pode ter criado a sala antes da falha de resposta.
- Se nenhum provedor estiver configurado para o modo, a API retorna `503`.

## 3. Comparação dos campos de criação

As duas integrações usam a operação de criação `POST /rooms` nas respectivas APIs externas. Na interface pública da Shadow, o cliente não chama essas rotas externas: envia o JSON para `POST /v1/rooms`.

| Campo | Uso | Observação |
| --- | --- | --- |
| `config_type` | Seleciona o modo | Ex.: `ap_padrao`, `gelo_inf`, `br_padrao` |
| `password` | Senha da sala | Campo obrigatório no contrato de criação da Nix |
| `start_delay_minutes` | Tempo até o início automático | Nix: AP/custom de 1 a 10; BR de 1 a 20 |
| `room_name` | Nome personalizado | Opcional |
| `map_name` | Mapa | Opções dependem do modo |
| `carregamento` | Ativa carregamento | Opção de modos AP/custom; não tem efeito no BR |
| `1500_ouro` | Ativa 1500 de ouro no primeiro round | Opção AP/custom; não tem efeito no BR |
| `equipe` | Formato de equipe BR | `solo`, `duo` ou `squad` |
| `espectadores` | Vagas de espectador BR | `30`, `16`, `8`, `6`, `4`, `2` ou `1` |

O backend encaminha o JSON recebido sem converter nomes de campos. Por isso, envie os campos no formato mostrado nos exemplos e não inclua campos que não se aplicam ao modo escolhido.

### O que é igual e o que muda

- **Igual na chamada externa:** criação por `POST /rooms`, envio de JSON e uso de `config_type` para indicar o modo.
- **Muda conforme o modo:** BR usa `equipe` e `espectadores`; AP/custom pode usar `carregamento` e `1500_ouro`.
- **Muda internamente:** autenticação e URL do provedor são gerenciadas pelo backend. O cliente não recebe nem utiliza os tokens dos provedores.
- **Roteamento específico da Shadow:** `br_padrao` vai para Lest Nort; AP tenta Nix e pode usar Lest Nort como alternativa em respostas HTTP 4xx.

## 4. Exemplos de requisição pelo endpoint Shadow

### Modo AP padrão

```bash
curl -X POST "https://shadow-panel-web.onrender.com/v1/rooms" \
  -H "X-API-Key: SUA_CHAVE_SHADOW" \
  -H "Content-Type: application/json" \
  -d '{
    "config_type": "ap_padrao",
    "password": "123456",
    "start_delay_minutes": 10,
    "room_name": "Sala de Treino",
    "map_name": "Bermuda",
    "carregamento": false,
    "1500_ouro": false
  }'
```

### Modo BR — Solo

```bash
curl -X POST "https://shadow-panel-web.onrender.com/v1/rooms" \
  -H "X-API-Key: SUA_CHAVE_SHADOW" \
  -H "Content-Type: application/json" \
  -d '{
    "config_type": "br_padrao",
    "password": "123456",
    "start_delay_minutes": 20,
    "room_name": "Sala BR",
    "map_name": "Bermuda",
    "equipe": "solo",
    "espectadores": 30
  }'
```

### Modo BR — Duo

Altere somente o campo `equipe`:

```json
{
  "config_type": "br_padrao",
  "password": "123456",
  "start_delay_minutes": 20,
  "room_name": "Sala BR Duo",
  "map_name": "Bermuda",
  "equipe": "duo",
  "espectadores": 16
}
```

### Modo BR — Squad

Altere somente o campo `equipe`:

```json
{
  "config_type": "br_padrao",
  "password": "123456",
  "start_delay_minutes": 20,
  "room_name": "Sala BR Squad",
  "map_name": "Bermuda",
  "equipe": "squad",
  "espectadores": 8
}
```

## 5. Resposta

Em caso de sucesso, a Shadow API repassa o JSON de resposta do provedor e acrescenta o campo `provider`, por exemplo:

```json
{
  "session_id": "ID_DA_SESSAO",
  "room_id": 123456,
  "status": "active",
  "provider": "Lest Nort"
}
```

Os campos exatos retornados dependem do provedor e da resposta real da criação.

## 6. Erros HTTP da Shadow API

| Código | Significado |
| --- | --- |
| `400` | Corpo ausente ou não enviado como JSON |
| `401` | Header `X-API-Key` ausente, inválido, pausado ou expirado |
| `402` | Saldo insuficiente |
| `403` | Limite de salas da chave atingido |
| `502` | Falha ao comunicar com o provedor ou erro interno |
| `503` | Nenhum provedor configurado/compatível para o modo |

Não repita automaticamente uma criação que terminou em timeout ou erro 5xx. A API pode ter criado a sala mesmo sem conseguir devolver a resposta; verifique o painel antes de tentar novamente.

## 7. Configuração privada do servidor

Somente o administrador configura estas variáveis nas Environment Variables do Render:

- `NIX_API_TOKEN`
- `LESTNORT_API_TOKEN`
- `NIX_BASE_URL` (padrão: `https://salas.nixbot.vip`)
- `LESTNORT_BASE_URL` (padrão: `https://lestnortff.shardweb.app/api/v1`)

Não coloque esses tokens neste repositório, em exemplos, no frontend ou em mensagens. O cliente usa exclusivamente `X-API-Key`.

Outras variáveis necessárias ao serviço:
- `SUPABASE_URL`
- `SUPABASE_KEY` (chave secreta/service role, somente no servidor)
- `SECRET_KEY`
- `PANEL_USERNAME`
- `PANEL_PASSWORD_HASH`
- `DISCORD_CLIENT_ID`
- `DISCORD_CLIENT_SECRET`
- `DISCORD_REDIRECT_URI=https://shadow-panel-web.onrender.com/auth/discord/callback`

Opcional:
- `ADMIN_DISCORD_USER_IDS`: IDs Discord autorizados como administradores, separados por vírgula.

Start command:

```bash
gunicorn api.app:app
```

## 8. Limite desta documentação

Esta documentação descreve os endpoints que a Shadow API expõe atualmente para clientes. Embora os provedores externos possam oferecer consultas de membros, resultados, edição e início de partida, essas rotas não devem ser chamadas pelo cliente através da Shadow API enquanto não forem implementadas e documentadas como endpoints Shadow próprios.
