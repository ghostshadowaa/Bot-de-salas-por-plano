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
NIX_ROOMS_URL = os.environ.get("NIX_ROOMS_URL", "https://salas.nixbot.vip/rooms")
NIX_AUTH_HEADER = os.environ.get("NIX_AUTH_HEADER", "Authorization")
NIX_AUTH_PREFIX = os.environ.get("NIX_AUTH_PREFIX", "Bearer ")
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
    db.table("api_key_events").insert({
        "api_key_id": key_id,
        "event_type": event_type,
        "endpoint": request.path,
        "status_code": status_code,
        "request_body": payload,
        "response_body": response,
    }).execute()


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
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Shadow API • Dashboard</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#08060d;color:#f5f3ff;font-family:Inter,system-ui,Arial}
.wrap{max-width:1200px;margin:auto;padding:22px}header{display:flex;justify-content:space-between;align-items:center;margin-bottom:18px}
a{color:#c4b5fd;text-decoration:none}.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.card{background:#110d1b;border:1px solid #292033;border-radius:18px;padding:18px;margin:12px 0}.grid>.card{margin:0}
input,select,button{width:100%;padding:11px 13px;margin-top:8px;border-radius:10px;background:#0b0710;color:#fff;border:1px solid #3a2d48}
button{background:#7c3aed;border:0;font-weight:800;cursor:pointer}.muted{color:#a49caf}.key{word-break:break-all;color:#c4b5fd;font-family:monospace}
.stats{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}.stat{background:#110d1b;border:1px solid #292033;border-radius:16px;padding:16px}.num{font-size:28px;font-weight:900}
.item{border-top:1px solid #292033;padding:15px 0}.item:first-child{border-top:0}.actions{display:flex;gap:8px;flex-wrap:wrap}.actions form{flex:1;min-width:110px}.secondary{background:#1b1425}.danger{background:#642236}.success{color:#8ef0b1}.warn{color:#f8d477}
nav{display:flex;gap:12px;flex-wrap:wrap;margin:12px 0 20px}nav a{padding:8px 12px;border:1px solid #30243e;border-radius:9px}
pre{white-space:pre-wrap;background:#0b0710;border:1px solid #292033;border-radius:12px;padding:14px;overflow:auto}
@media(max-width:750px){.grid{grid-template-columns:1fr}.stats{grid-template-columns:1fr}header{align-items:flex-start;gap:10px}}
</style></head>
<body><div class="wrap">
<header><div><h1>🟣 Shadow API</h1><div class="muted">Dashboard, chaves e documentação</div></div><a href="/admin/logout">Sair</a></header>
<nav><a href="/admin">Dashboard</a><a href="/docs">Documentação</a><a href="/health">Health</a></nav>

<div class="stats">
<div class="stat"><div class="muted">Total de chaves</div><div class="num">{{keys|length}}</div></div>
<div class="stat"><div class="muted">Ativas</div><div class="num">{{active_count}}</div></div>
<div class="stat"><div class="muted">Salas usadas</div><div class="num">{{rooms_used}}</div></div>
</div>

<div class="grid" style="margin-top:16px">
<div class="card"><h2>Criar API Key</h2><p class="muted">A chave completa aparece somente uma vez.</p>
<form method="post" action="/admin/keys">
<input name="label" placeholder="Nome do cliente" required>
<select name="days"><option value="1">1 dia</option><option value="7">7 dias</option><option value="30" selected>30 dias</option><option value="90">90 dias</option><option value="365">365 dias</option></select>
<input name="owner_user_id" placeholder="Discord User ID (opcional)">
<input name="max_rooms" type="number" min="0" placeholder="Limite de salas — 0 = ilimitado">
<input name="rate_limit" type="number" min="1" value="30" placeholder="Requests/min">
<button>Criar API Key</button></form></div>

<div class="card"><h2>Como usar</h2><p class="muted">Endpoint principal para criação de salas.</p>
<pre>POST /v1/rooms
X-API-Key: sk_sua_chave
Content-Type: application/json</pre>
<a href="/docs">Ver documentação completa →</a></div>
</div>

{% if new_key %}<div class="card"><h2 class="success">✓ API Key criada</h2><p class="muted">Guarde esta chave agora. Ela não pode ser recuperada depois.</p><div class="key">{{new_key}}</div><button onclick="navigator.clipboard.writeText({{new_key|tojson}})">Copiar chave</button></div>{% endif %}

<div class="card"><h2>Suas API Keys</h2>
{% for k in keys %}<div class="item">
<strong>{{k.label}}</strong> — {% if k.active %}<span class="success">ATIVA</span>{% else %}<span class="warn">PAUSADA</span>{% endif %}
<div class="muted">ID {{k.id}} · Dono: {{k.owner_user_id or "—"}} · Expira: {{k.expires_at or "sem expiração"}}</div>
<div class="muted">Uso: {{k.rooms_used}}{% if k.max_rooms is not none %} / {{k.max_rooms}} salas{% else %} salas{% endif %} · Limite: {{k.rate_limit_per_minute}} req/min</div>
<div class="key">{{k.key_prefix}}••••••••••••••••</div>
<div class="actions">
<form method="post" action="/admin/keys/{{k.id}}/renew"><button class="secondary">+30 dias</button></form>
<form method="post" action="/admin/keys/{{k.id}}/toggle"><button class="secondary">{{"Pausar" if k.active else "Ativar"}}</button></form>
<form method="post" action="/admin/keys/{{k.id}}/delete" onsubmit="return confirm('Excluir esta API Key?')"><button class="danger">Excluir</button></form>
</div></div>
{% else %}<p class="muted">Nenhuma API Key criada.</p>{% endfor %}
</div></div></body></html>
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
        upstream = requests.post(
            NIX_ROOMS_URL,
            json=payload,
            headers={NIX_AUTH_HEADER: NIX_AUTH_PREFIX + NIX_API_TOKEN},
            timeout=30,
        )
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

    return render_template_string(
        DASHBOARD_HTML,
        keys=keys,
        active_count=active,
        rooms_used=rooms_used,
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
