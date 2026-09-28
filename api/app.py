import hashlib
import os
import secrets
from datetime import datetime, timezone, timedelta

import requests
from flask import Flask, jsonify, redirect, render_template_string, request, session
from supabase import create_client
from werkzeug.security import check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-me-in-render")

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
NIX_API_TOKEN = os.environ.get("NIX_API_TOKEN", "")
NIX_BASE_URL = os.environ.get("NIX_BASE_URL", "https://salas.nixbot.vip").rstrip("/")
NIX_ROOMS_URL = f"{NIX_BASE_URL}/rooms"
NIX_AUTH_HEADER = "Authorization"
NIX_AUTH_PREFIX = "Bearer "
ADMIN_USERNAME = os.environ.get("PANEL_USERNAME", os.environ.get("ADMIN_USERNAME", "Shadow"))
ADMIN_PASSWORD_HASH = os.environ.get("PANEL_PASSWORD_HASH", os.environ.get("ADMIN_PASSWORD_HASH", ""))
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("SUPABASE_URL e SUPABASE_KEY precisam estar configurados.")

db = create_client(SUPABASE_URL, SUPABASE_KEY)


def now():
    return datetime.now(timezone.utc)


def iso(value):
    return value.isoformat()


def hash_key(value):
    return hashlib.sha256(value.encode()).hexdigest()


def make_key():
    return "sk_" + secrets.token_urlsafe(30)


def valid_key(row):
    if not row or not row.get("active"):
        return False
    expires = row.get("expires_at")
    if not expires:
        return True
    try:
        return datetime.fromisoformat(expires.replace("Z", "+00:00")) > now()
    except ValueError:
        return False


def admin():
    return session.get("admin") is True


def create_key(label, days, owner=None, max_rooms=None, rate_limit=30):
    raw = make_key()
    created = now()
    row = {
        "label": label,
        "key_prefix": raw[:12],
        "key_hash": hash_key(raw),
        "active": True,
        "created_at": iso(created),
        "expires_at": iso(created + timedelta(days=days)),
        "max_rooms": max_rooms,
        "rooms_used": 0,
        "rate_limit_per_minute": rate_limit,
        "owner_user_id": str(owner) if owner else None,
    }
    result = db.table("api_keys").insert(row).execute()
    return raw, result.data[0]


def log_event(key_id, event_type, status_code, payload, response):
    client_ip = request.headers.get("X-Forwarded-For", request.remote_addr or "").split(",")[0].strip()
    client_ip_hash = hashlib.sha256(client_ip.encode()).hexdigest() if client_ip else None
    db.table("api_key_events").insert({
        "api_key_id": key_id,
        "event_type": event_type,
        "endpoint": request.path,
        "status_code": status_code,
        "request_body": payload,
        "response_body": response,
        "client_ip_hash": client_ip_hash,
        "user_agent": request.headers.get("User-Agent", "")[:500],
        "client_id": request.headers.get("X-Client-ID", "")[:200] or None,
    }).execute()


def find_key_by_raw(raw):
    if not raw:
        return None
    result = db.table("api_keys").select("*").eq("key_hash", hash_key(str(raw).strip())).limit(1).execute()
    return (result.data or [None])[0]


def register_delivery(payload):
    if not isinstance(payload, dict):
        return None

    raw_key = (
        payload.get("api_key") or payload.get("key") or payload.get("license_key")
        or payload.get("access_key") or payload.get("token")
    )
    key = find_key_by_raw(raw_key)

    customer = payload.get("customer") if isinstance(payload.get("customer"), dict) else {}
    user = payload.get("user") if isinstance(payload.get("user"), dict) else {}
    buyer = payload.get("buyer") if isinstance(payload.get("buyer"), dict) else {}

    external_user_id = (
        payload.get("user_id") or payload.get("discord_user_id")
        or customer.get("id") or user.get("id") or buyer.get("id")
    )
    external_username = (
        payload.get("username") or payload.get("user_name")
        or payload.get("customer_name") or payload.get("name")
        or customer.get("username") or customer.get("name")
        or user.get("username") or user.get("name")
        or buyer.get("username") or buyer.get("name")
    )
    sale_id = (
        payload.get("sale_id") or payload.get("order_id")
        or payload.get("transaction_id") or payload.get("id")
    )
    product_name = (
        payload.get("product") if isinstance(payload.get("product"), str) else
        payload.get("product_name") or payload.get("item") or payload.get("plan")
    )

    row = {
        "api_key_id": key.get("id") if key else None,
        "external_sale_id": str(sale_id) if sale_id is not None else None,
        "external_user_id": str(external_user_id) if external_user_id is not None else None,
        "external_username": str(external_username) if external_username is not None else None,
        "product_name": str(product_name) if product_name is not None else None,
        "source": "ag_solutions",
        "payload": payload,
    }
    saved = db.table("api_key_deliveries").insert(row).execute()
    return saved.data[0] if saved.data else row


LOGIN_HTML = """
<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Shadow API • Login</title>
<style>
*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;background:#08060d;color:#f5f3ff;font-family:Inter,system-ui,Arial}
.card{width:min(420px,92vw);background:#110d1b;border:1px solid #30243e;border-radius:20px;padding:28px;box-shadow:0 20px 60px #0008}
h1{margin:0 0 6px}.muted{color:#a49caf}input,button{width:100%;padding:12px;border-radius:10px;margin-top:10px;background:#0b0710;color:#fff;border:1px solid #3b2d49}button{background:#7c3aed;border:0;font-weight:800;cursor:pointer}.err{color:#ff8c9c;margin-top:12px}
</style></head><body><div class="card"><h1>🟣 Shadow API</h1><p class="muted">Painel administrativo da API</p>
<form method="post"><input name="username" placeholder="Usuário" required><input name="password" type="password" placeholder="Senha" required><button>Entrar</button></form>
{% if error %}<div class="err">{{error}}</div>{% endif %}</div></body></html>
"""

DASHBOARD_HTML = """
<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Shadow API • Dashboard</title>
<style>
*{box-sizing:border-box}
:root{--bg:#07050b;--panel:#100c17;--panel2:#151020;--border:#292035;--text:#f8f7fb;--muted:#9d95aa;--purple:#8b5cf6;--purple2:#6d28d9;--green:#70e0a0;--yellow:#f6d477;--red:#f87171}
body{margin:0;background:radial-gradient(circle at 15% 0%,#25113e 0,transparent 32%),radial-gradient(circle at 90% 10%,#17102a 0,transparent 28%),var(--bg);color:var(--text);font-family:Inter,system-ui,-apple-system,Segoe UI,Arial,sans-serif}
.wrap{max-width:1240px;margin:auto;padding:28px}
.topbar{display:flex;justify-content:space-between;align-items:center;gap:18px;margin-bottom:26px}
.brand{display:flex;align-items:center;gap:13px}.logo{width:44px;height:44px;display:grid;place-items:center;border-radius:14px;background:linear-gradient(135deg,#a78bfa,#6d28d9);box-shadow:0 10px 30px #7c3aed44;font-size:22px}
h1,h2,h3,p{margin-top:0}.brand h1{font-size:22px;margin:0}.muted{color:var(--muted)}
.top-actions{display:flex;gap:9px;flex-wrap:wrap}.top-actions a,.nav a{color:#d8ccf7;text-decoration:none;border:1px solid var(--border);background:#0e0a15;padding:9px 13px;border-radius:10px;font-size:14px}.top-actions a:hover,.nav a:hover{border-color:#60448a}
.nav{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:22px}.nav a.active{background:#24153b;border-color:#7045a5;color:#fff}
.hero{padding:26px;border:1px solid #352649;border-radius:22px;background:linear-gradient(135deg,#171020cc,#0f0b16dd);box-shadow:0 18px 55px #0005;margin-bottom:18px}.hero h2{font-size:28px;margin-bottom:7px}.hero p{margin-bottom:0;max-width:700px}
.stats{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:18px}.stat{padding:18px;border:1px solid var(--border);border-radius:16px;background:var(--panel);}.stat-head{display:flex;justify-content:space-between;align-items:center}.stat-icon{font-size:18px;opacity:.8}.num{font-size:30px;font-weight:900;margin-top:8px}
.grid{display:grid;grid-template-columns:minmax(0,1.1fr) minmax(0,.9fr);gap:18px}.card{background:#100c17e8;border:1px solid var(--border);border-radius:18px;padding:20px;box-shadow:0 10px 35px #0003}.card h2{font-size:18px;margin-bottom:5px}.card .desc{font-size:13px;color:var(--muted);margin-bottom:16px}
input,select,button{width:100%;padding:12px 13px;margin-top:8px;border-radius:10px;background:#0a0710;color:#fff;border:1px solid #342842;font:inherit}input:focus,select:focus{outline:2px solid #7c3aed55;border-color:#8054b9}button{background:linear-gradient(135deg,var(--purple),var(--purple2));border:0;font-weight:800;cursor:pointer;box-shadow:0 8px 22px #7c3aed2b}button:hover{filter:brightness(1.08)}
.form-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px}.full{grid-column:1/-1}.hint{font-size:12px;color:var(--muted);margin-top:8px}
pre{white-space:pre-wrap;background:#09070d;border:1px solid var(--border);border-radius:12px;padding:13px;overflow:auto;color:#d9d0eb;font-size:12px}
.link{display:inline-flex;margin-top:13px;color:#c4b5fd;text-decoration:none;font-weight:700}.link:hover{text-decoration:underline}
.key-alert{margin:18px 0;padding:18px;border:1px solid #3e6a51;border-radius:16px;background:#0d1a13}.success{color:var(--green)}.key{word-break:break-all;color:#c4b5fd;font-family:ui-monospace,SFMono-Regular,Consolas,monospace;background:#08060d;border:1px solid #26352b;padding:12px;border-radius:10px;margin:10px 0}
.keys-card{margin-top:18px}.item{padding:17px 0;border-top:1px solid var(--border)}.item:first-child{border-top:0}.item-title{display:flex;justify-content:space-between;gap:10px;align-items:center}.status{font-size:11px;font-weight:900;padding:5px 8px;border-radius:999px}.on{background:#123521;color:var(--green)}.off{background:#342b13;color:var(--yellow)}.meta{display:flex;flex-wrap:wrap;gap:8px 14px;color:var(--muted);font-size:12px;margin:7px 0 10px}.actions{display:flex;gap:8px;flex-wrap:wrap}.actions form{flex:1;min-width:105px}.actions button{background:#1b1425;box-shadow:none}.actions .danger{background:#431c27}.empty{padding:28px;text-align:center;border:1px dashed #3a3045;border-radius:13px;color:var(--muted)}
.footer{text-align:center;color:#71697b;font-size:12px;padding:25px 0 5px}
@media(max-width:800px){.grid{grid-template-columns:1fr}.stats{grid-template-columns:1fr}.wrap{padding:18px}.topbar{align-items:flex-start}.hero h2{font-size:23px}.form-grid{grid-template-columns:1fr}.full{grid-column:auto}.item-title{align-items:flex-start;flex-direction:column}}
</style>
</head>
<body>
<div class="wrap">
<header class="topbar">
  <div class="brand"><div class="logo">S</div><div><h1>Shadow API</h1><div class="muted">Central de gerenciamento</div></div></div>
  <div class="top-actions"><a href="/docs">Documentação</a><a href="/admin/logout">Sair</a></div>
</header>

<nav class="nav"><a class="active" href="/admin">Dashboard</a><a href="/docs">API Docs</a><a href="/health">Status</a></nav>

<section class="hero">
  <h2>Olá, Shadow 👋</h2>
  <p class="muted">Gerencie suas API Keys, acompanhe o uso e mantenha sua API de salas organizada em um só lugar.</p>
</section>

<section class="stats">
  <div class="stat"><div class="stat-head"><span class="muted">Total de chaves</span><span class="stat-icon">🔑</span></div><div class="num">{{keys|length}}</div></div>
  <div class="stat"><div class="stat-head"><span class="muted">Chaves ativas</span><span class="stat-icon">✓</span></div><div class="num">{{active_count}}</div></div>
  <div class="stat"><div class="stat-head"><span class="muted">Salas utilizadas</span><span class="stat-icon">◈</span></div><div class="num">{{rooms_used}}</div></div>
</section>

<section class="grid">
  <div class="card">
    <h2>Nova API Key</h2>
    <p class="desc">Crie uma chave para um cliente ou integração. A chave completa será mostrada somente uma vez.</p>
    <form method="post" action="/admin/keys">
      <div class="form-grid">
        <div class="full"><input name="label" placeholder="Nome do cliente / integração" required></div>
        <div><select name="days"><option value="1">1 dia</option><option value="7">7 dias</option><option value="30" selected>30 dias</option><option value="90">90 dias</option><option value="365">365 dias</option></select></div>
        <div><input name="owner_user_id" placeholder="Discord User ID (opcional)"></div>
        <div><input name="max_rooms" type="number" min="0" placeholder="Limite de salas"></div>
        <div><input name="rate_limit" type="number" min="1" value="30" placeholder="Requests/min"></div>
        <div class="full"><button>+ Criar API Key</button></div>
      </div>
      <div class="hint">Limite de salas vazio ou 0 = ilimitado.</div>
    </form>
  </div>

  <div class="card">
    <h2>Comece por aqui</h2>
    <p class="desc">Integre sua aplicação em poucos passos.</p>
    <pre>POST /v1/rooms
X-API-Key: sk_sua_chave
Content-Type: application/json</pre>
    <a class="link" href="/docs">Abrir documentação completa →</a>
  </div>
</section>

{% if new_key %}
<section class="key-alert">
  <h3 class="success">✓ API Key criada com sucesso</h3>
  <p class="muted">Copie e guarde agora. Por segurança, a chave completa não será exibida novamente.</p>
  <div class="key">{{new_key}}</div>
  <button onclick="navigator.clipboard.writeText({{new_key|tojson}})">Copiar chave</button>
</section>
{% endif %}

<section class="card keys-card">
  <div class="item-title"><div><h2>Entregas recebidas</h2><p class="desc">Vendas/webhooks recebidos e associados às API Keys.</p></div><span class="muted">{{deliveries|length}} recentes</span></div>
  {% for d in deliveries %}
  <div class="item">
    <div class="item-title"><strong>{{d.external_username or d.external_user_id or "Cliente não informado"}}</strong><span class="status on">RECEBIDA</span></div>
    <div class="meta">
      <span>Venda: {{d.external_sale_id or "—"}}</span>
      <span>Produto: {{d.product_name or "—"}}</span>
      <span>Key ID: {{d.api_key_id or "não vinculada"}}</span>
      <span>{{d.delivered_at or "—"}}</span>
    </div>
  </div>
  {% else %}
  <div class="empty">Nenhuma entrega recebida ainda.</div>
  {% endfor %}
</section>

<section class="card keys-card">
  <div class="item-title"><div><h2>API Keys</h2><p class="desc">Chaves criadas neste painel e seus limites.</p></div><span class="muted">{{keys|length}} cadastradas</span></div>
  {% for k in keys %}
  <div class="item">
    <div class="item-title">
      <strong>{{k.label}}</strong>
      {% if k.active %}<span class="status on">ATIVA</span>{% else %}<span class="status off">PAUSADA</span>{% endif %}
    </div>
    <div class="meta">
      <span>ID {{k.id}}</span><span>Dono: {{k.owner_user_id or "—"}}</span><span>Expira: {{k.expires_at or "sem expiração"}}</span>
      <span>Uso: {{k.rooms_used}}{% if k.max_rooms is not none %} / {{k.max_rooms}} salas{% else %} salas{% endif %}</span><span>{{k.rate_limit_per_minute}} req/min</span>
    </div>
    <div class="key">{{k.key_prefix}}••••••••••••••••</div>
    <div class="actions">
      <form method="post" action="/admin/keys/{{k.id}}/renew"><button>+30 dias</button></form>
      <form method="post" action="/admin/keys/{{k.id}}/toggle"><button>{{"Pausar" if k.active else "Ativar"}}</button></form>
      <form method="post" action="/admin/keys/{{k.id}}/delete" onsubmit="return confirm('Excluir esta API Key?')"><button class="danger">Excluir</button></form>
    </div>
  </div>
  {% else %}
  <div class="empty">Nenhuma API Key criada ainda.<br>Crie a primeira usando o formulário acima.</div>
  {% endfor %}
</section>

<div class="footer">Shadow API • Painel administrativo</div>
</div>
</body>
</html>
"""

DOCS_HTML = """
<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Shadow API • Documentação</title><style>
*{box-sizing:border-box}body{margin:0;background:#08060d;color:#f5f3ff;font-family:Inter,system-ui,Arial}.wrap{max-width:1000px;margin:auto;padding:22px}
.card{background:#110d1b;border:1px solid #292033;border-radius:18px;padding:20px;margin:14px 0}.muted{color:#a49caf}a{color:#c4b5fd;text-decoration:none}code,pre{background:#0b0710;border:1px solid #292033;border-radius:10px}code{padding:2px 5px}pre{padding:14px;overflow:auto;white-space:pre-wrap}.method{color:#a78bfa;font-weight:900}
</style></head><body><div class="wrap"><a href="/admin">← Dashboard</a><h1>Shadow API — Documentação</h1>
<p class="muted">API própria da Shadow para criação de salas. Não depende de plataforma de vendas ou automação externa.</p>
<div class="card"><h2>Base URL</h2><pre>{{base_url}}</pre></div>
<div class="card"><h2>Autenticação</h2><p>Envie sua chave em todas as requisições protegidas:</p><pre>X-API-Key: sk_sua_chave
Content-Type: application/json</pre><p class="muted">A chave é armazenada no banco somente como hash.</p></div>
<div class="card"><h2><span class="method">POST</span> /v1/rooms</h2><p>Cria uma sala usando o provedor configurado no servidor.</p>
<pre>curl -X POST "{{base_url}}/v1/rooms" \
  -H "X-API-Key: sk_sua_chave" \
  -H "Content-Type: application/json" \
  -d '{
    "config_type": "ap_padrao",
    "password": "00",
    "start_delay_minutes": 1,
    "map_name": "Bermuda",
    "room_name": "Shadow Salas"
  }'</pre></div>
<div class="card"><h2>Resposta</h2><p>A resposta do provedor é repassada em JSON. Em erro de autenticação:</p><pre>{
  "error": "API key inválida, pausada ou expirada"
}</pre></div>
<div class="card"><h2>Códigos HTTP</h2><ul><li><b>200–299</b> — requisição aceita pelo provedor.</li><li><b>401</b> — chave ausente, inválida, pausada ou expirada.</li><li><b>403</b> — limite de salas atingido.</li><li><b>502</b> — falha na comunicação com o provedor.</li></ul></div>
<div class="card"><h2>Health</h2><pre>GET {{base_url}}/health</pre></div>
</div></body></html>
"""


@app.get("/")
def home():
    if admin():
        return redirect("/admin")
    return redirect("/admin/login")


@app.post("/")
def ag_webhook_root():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"ok": False, "error": "O corpo do webhook deve ser JSON"}), 400
    try:
        delivery = register_delivery(payload)
        return jsonify({
            "ok": True,
            "received": True,
            "delivery_id": delivery.get("id") if delivery else None,
            "api_key_linked": bool(delivery and delivery.get("api_key_id")),
        }), 200
    except Exception:
        return jsonify({"ok": False, "error": "Falha ao registrar webhook"}), 500


@app.post("/webhook/ag-solutions")
def ag_webhook():
    return ag_webhook_root()


@app.get("/health")
def health():
    return jsonify({
        "ok": True,
        "service": "shadow-api",
        "supabase": "configured",
        "provider": "configured" if NIX_API_TOKEN else "missing",
    })


@app.get("/docs")
def docs():
    return render_template_string(DOCS_HTML, base_url=request.host_url.rstrip("/"))


@app.post("/v1/rooms")
def rooms():
    raw = request.headers.get("X-API-Key", "").strip()
    if not raw:
        return jsonify({"error": "X-API-Key ausente"}), 401

    result = db.table("api_keys").select("*").eq("key_hash", hash_key(raw)).limit(1).execute()
    key = (result.data or [None])[0]

    if not valid_key(key):
        return jsonify({"error": "API key inválida, pausada ou expirada"}), 401

    max_rooms = key.get("max_rooms")
    if max_rooms is not None and key.get("rooms_used", 0) >= max_rooms:
        response = {"error": "Limite de salas atingido", "limit": max_rooms}
        log_event(key["id"], "room_request", 403, request.get_json(silent=True) or {}, response)
        return jsonify(response), 403

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "O corpo deve ser JSON"}), 400

    try:
        # A API Key Shadow nunca é enviada para a Nix.
        # O cliente fala somente com a Shadow API; a Shadow usa o token
        # privado do Render para chamar diretamente POST /rooms da Nix.
        headers = {
            "Authorization": f"Bearer {NIX_API_TOKEN}",
            "Content-Type": "application/json",
        }

        upstream = None
        last_error = None

        # Mesmo comportamento do bot original: retry limitado apenas
        # para erros de servidor/infraestrutura da Nix.
        for attempt in range(1, 5):
            try:
                upstream = requests.post(
                    NIX_ROOMS_URL,
                    json=payload,
                    headers=headers,
                    timeout=15,
                )

                if upstream.status_code not in (502, 503, 504, 524):
                    break

                if attempt < 4:
                    import time
                    time.sleep(min(5 * attempt, 20))

            except requests.RequestException as exc:
                last_error = exc
                if attempt < 4:
                    import time
                    time.sleep(min(5 * attempt, 20))

        if upstream is None:
            response = {"error": "Não foi possível conectar à API da Nix"}
            log_event(key["id"], "room_request", 502, payload, response)
            return jsonify(response), 502

        try:
            response = upstream.json()
        except ValueError:
            response = {"raw": upstream.text[:4000]}

        log_event(key["id"], "room_request", upstream.status_code, payload, response)

        if 200 <= upstream.status_code < 300:
            db.table("api_keys").update({
                "rooms_used": int(key.get("rooms_used") or 0) + 1,
                "last_used_at": iso(now()),
            }).eq("id", key["id"]).execute()

        return jsonify(response), upstream.status_code
    except requests.RequestException:
        response = {"error": "Falha ao comunicar com o provedor"}
        log_event(key["id"], "room_request", 502, payload, response)
        return jsonify(response), 502


@app.get("/admin/login")
def login():
    if admin():
        return redirect("/admin")
    return render_template_string(LOGIN_HTML, error=None)


@app.post("/admin/login")
def login_post():
    username = request.form.get("username", "")
    password = request.form.get("password", "")
    valid_password = False

    if ADMIN_PASSWORD_HASH:
        valid_password = check_password_hash(ADMIN_PASSWORD_HASH, password)
    elif ADMIN_PASSWORD:
        valid_password = secrets.compare_digest(password, ADMIN_PASSWORD)

    if username == ADMIN_USERNAME and valid_password:
        session["admin"] = True
        return redirect("/admin")

    return render_template_string(LOGIN_HTML, error="Usuário ou senha inválidos."), 401


@app.get("/admin/logout")
def logout():
    session.clear()
    return redirect("/admin/login")


@app.get("/admin")
def dashboard():
    if not admin():
        return redirect("/admin/login")

    keys = db.table("api_keys").select("*").order("created_at", desc=True).execute().data or []
    active = sum(1 for item in keys if valid_key(item))
    rooms_used = sum(int(item.get("rooms_used") or 0) for item in keys)
    deliveries = db.table("api_key_deliveries").select("*").order("delivered_at", desc=True).limit(50).execute().data or []

    return render_template_string(
        DASHBOARD_HTML,
        keys=keys,
        active_count=active,
        rooms_used=rooms_used,
        deliveries=deliveries,
        new_key=session.pop("new_key", None),
    )


@app.post("/admin/keys")
def admin_key():
    if not admin():
        return redirect("/admin/login")

    try:
        days = max(1, int(request.form.get("days", "30")))
        rate_limit = max(1, int(request.form.get("rate_limit", "30")))
    except ValueError:
        return redirect("/admin")

    label = request.form.get("label", "Cliente").strip() or "Cliente"
    owner = request.form.get("owner_user_id", "").strip() or None
    raw_limit = request.form.get("max_rooms", "").strip()

    try:
        max_rooms = int(raw_limit) if raw_limit else None
    except ValueError:
        max_rooms = None

    if max_rooms is not None and max_rooms <= 0:
        max_rooms = None

    raw, _ = create_key(label, days, owner, max_rooms, rate_limit)
    session["new_key"] = raw
    return redirect("/admin")


@app.post("/admin/keys/<int:key_id>/renew")
def renew(key_id):
    if not admin():
        return redirect("/admin/login")

    result = db.table("api_keys").select("expires_at").eq("id", key_id).limit(1).execute()
    row = (result.data or [None])[0]

    if row:
        base = now()
        if row.get("expires_at"):
            try:
                base = max(base, datetime.fromisoformat(row["expires_at"].replace("Z", "+00:00")))
            except ValueError:
                pass

        db.table("api_keys").update({
            "expires_at": iso(base + timedelta(days=30)),
            "active": True,
        }).eq("id", key_id).execute()

    return redirect("/admin")


@app.post("/admin/keys/<int:key_id>/toggle")
def toggle_key(key_id):
    if not admin():
        return redirect("/admin/login")

    result = db.table("api_keys").select("active").eq("id", key_id).limit(1).execute()
    row = (result.data or [None])[0]

    if row:
        db.table("api_keys").update({"active": not row["active"]}).eq("id", key_id).execute()

    return redirect("/admin")


@app.post("/admin/keys/<int:key_id>/delete")
def delete_key(key_id):
    if not admin():
        return redirect("/admin/login")

    db.table("api_key_events").delete().eq("api_key_id", key_id).execute()
    db.table("api_keys").delete().eq("id", key_id).execute()
    return redirect("/admin")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
