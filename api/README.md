# Shadow API — documentação para usuários

A Shadow API permite criar salas de Free Fire usando uma única chave de acesso. O sistema cuida automaticamente do processamento da solicitação.

## 1. Criar uma sala

**Endpoint**

```http
POST https://shadow-panel-web.onrender.com/v1/rooms
```

**Headers**

```http
X-API-Key: SUA_CHAVE_SHADOW
Content-Type: application/json
```

A autenticação é feita exclusivamente com sua chave Shadow. Não é necessário informar credenciais de serviços externos.

## 2. Parâmetros

| Campo | Descrição |
| --- | --- |
| `config_type` | Tipo de sala solicitado |
| `password` | Senha da sala |
| `start_delay_minutes` | Tempo para início automático |
| `room_name` | Nome personalizado da sala |
| `map_name` | Mapa escolhido |
| `carregamento` | Ativa o carregamento, quando aplicável |
| `1500_ouro` | Ativa 1500 de ouro, quando aplicável |
| `equipe` | Modalidade BR: `solo`, `duo` ou `squad` |
| `espectadores` | Quantidade de espectadores no BR: `30`, `16`, `8`, `6`, `4`, `2` ou `1` |

Os campos opcionais dependem do tipo de sala. Para BR, informe `equipe` e `espectadores`. Os campos de carregamento e ouro são destinados aos modos em que essas opções se aplicam.

## 3. Exemplos

### Sala AP

```bash
curl -X POST "https://shadow-panel-web.onrender.com/v1/rooms" \
  -H "X-API-Key: SUA_CHAVE_SHADOW" \
  -H "Content-Type: application/json" \
  -d '{
    "config_type": "ap_padrao",
    "password": "123456",
    "start_delay_minutes": 5,
    "room_name": "Sala de Treino",
    "map_name": "Bermuda"
  }'
```

### Sala BR — Solo

```bash
curl -X POST "https://shadow-panel-web.onrender.com/v1/rooms" \
  -H "X-API-Key: SUA_CHAVE_SHADOW" \
  -H "Content-Type: application/json" \
  -d '{
    "config_type": "br_padrao",
    "password": "123456",
    "start_delay_minutes": 10,
    "room_name": "Sala BR",
    "map_name": "Bermuda",
    "equipe": "solo",
    "espectadores": 30
  }'
```

### Sala BR — Duo

```json
{
  "config_type": "br_padrao",
  "password": "123456",
  "start_delay_minutes": 10,
  "room_name": "Sala BR Duo",
  "map_name": "Bermuda",
  "equipe": "duo",
  "espectadores": 16
}
```

### Sala BR — Squad

```json
{
  "config_type": "br_padrao",
  "password": "123456",
  "start_delay_minutes": 10,
  "room_name": "Sala BR Squad",
  "map_name": "Bermuda",
  "equipe": "squad",
  "espectadores": 8
}
```

Para os exemplos JSON de Duo e Squad, use os mesmos headers e endpoint do exemplo Solo, alterando o corpo da requisição.

## 4. Resposta

Em caso de sucesso, a API retorna os dados da sala disponibilizados no processamento da criação. Os campos podem variar conforme a modalidade solicitada.

Exemplo ilustrativo:

```json
{
  "session_id": "ID_DA_SESSAO",
  "room_id": 123456,
  "password": "123456",
  "status": "active"
}
```

## 5. Erros HTTP

| Código | Significado |
| --- | --- |
| `400` | Requisição inválida ou JSON incorreto |
| `401` | Chave Shadow ausente ou inválida |
| `402` | Saldo insuficiente |
| `403` | Limite de uso da chave atingido |
| `502` | Falha temporária ao processar a criação |
| `503` | Serviço temporariamente indisponível para a solicitação |

Se ocorrer timeout ou erro 5xx, confira o painel antes de enviar outra criação, para evitar solicitações duplicadas.

## 6. Crédito e utilização

- O custo atual por criação concluída é de R$ 0,05.
- É necessário ter saldo disponível na carteira vinculada à sua conta.
- Em caso de falha na criação, o crédito reservado é devolvido conforme o processamento da API.

## 7. Observações

- Use sempre sua chave Shadow no header `X-API-Key`.
- Não compartilhe sua chave de acesso.
- Envie os campos de acordo com a modalidade escolhida.
- O processamento e a seleção do serviço responsável pela criação são automáticos.
- Esta documentação cobre somente a criação de salas disponível no endpoint público atual.
