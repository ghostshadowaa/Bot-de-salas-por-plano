import hashlib
import os
import secrets
import time
from datetime import datetime, timezone

import requests
from flask import Flask, jsonify, redirect, render_template_string, request, session, url_for
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

LOGIN_HTML = """
<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Shadow API</title><style>
body{margin:0;background:#0b0712;color:#eee;font-family:Arial,sans-serif;display:grid;place-items:center;min-height:100vh}
.card{width:min(420px,90vw);background:#151020;border:1px solid #392450;border-radius:18px;padding:28px;box-shadow:0 20px 60px #0008}
h1{margin-top:0}.muted{color:#aaa}input,button{width:100%;box-sizing:border-box;padding:13px;margin-top:10px;border-radius:10px;border:1px solid #4b3564;background:#0f0b17;color:#fff}
button{background:#7c3aed;border:0;font-weight:bold}.err{color:#ff7b7b;margin-top:12px}
</style></head><body><div class="card"><h1>Shadow API</h1><p class="muted">Painel administrativo</p>
<form method="post"><input name="username" placeholder="Usuário" required><input name="password" type="password" placeholder="Senha" required><button>Entrar</button></form>
{% if error %}<div class="err">{{error}}</div>{% endif %}</div></body></html>
"""

DASHBOARD_HTML = """
<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Shadow API</title><style>
body{margin:0;background:#0b0712;color:#eee;font-family:Arial,sans-serif}.wrap{max-width:1100px;margin:auto;padding:22px}
header{display:flex;justify-content:space-between;align-items:center;gap:15px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:16px}
.card{background:#151020;border:1px solid #392450;border-radius:16px;padding:18px}.accent{color:#a78bfa}
input,button{box-sizing:border-box;padding:11px;border-radius:9px;border:1px solid #4b3564;background:#0f0b17;color:#fff}input{width:100%;margin:5px 0}button{background:#7c3aed;border:0;font-weight:bold;cursor:pointer}
table{width:100%;border-collapse:collapse;margin-top:10px}th,td{text-align:left;padding:10px;border-bottom:1px solid #2b2038;font-size:14px}.key{font-family:monospace;word-break:break-all}
.badge{padding:4px 8px;border-radius:999px;background:#261d35}.danger{background:#7f1d1d}.ok{background:#14532d}.top{display:flex;justify-content:space-between;align-items:center}
small{color:#aaa}.copy{margin-top:10px}
</style></head><body><div class="wrap"><header><div><h1>Shadow API</h1><small>Gerenciamento de chaves para sua API de salas</small></div><a href="/admin/logout" style="color:#c4b5fd">Sair</a></header>
<div class="grid" style="margin-top:18px"><div class="card"><h2>Nova chave</h2><form method="post" action="/admin/keys">
<input name="label" placeholder="Nome do cliente" required>
<input name="days" type="number" min="1" placeholder="Validade em dias" required>
<input name="max_rooms" type="number" min="0" placeholder="Limite de salas (0 = ilimitado)">
<input name="rate_limit" type="number" min="1" value="30" placeholder="Chamadas por minuto">
<button>Criar chave</button></form></div>
<div class="card"><h2>API</h2><p><span class="accent">POST /v1/rooms</span></p><p>O cliente envia a chave em <b>X-API-Key</b>. O servidor valida a chave e encaminha o JSON para a Nix sem revelar seu token Nix.</p><p><small>Chaves são exibidas integralmente somente no momento da criação.</small></p></div></div>
{% if new_key %}<div class="card" style="margin-top:16px"><h2>Chave criada</h2><p class="key">{{new_key}}</p><button class="copy" onclick="navigator.clipboard.writeText({{new_key|tojson}})">Copiar chave</button></div>{% endif %}
<div class="card" style="margin-top:16px"><div class="top"><h2>Chaves</h2><small>{{keys|length}} cadastradas</small></div>
<table><tr><th>Cliente</th><th>Chave</th><th>Status</th><th>Uso</th><th>Validade</th><th></th></tr>
{% for k in keys %}<tr><td>{{k.label}}</td><td class="key">{{k.key_prefix}}••••••</td><td><span class="badge {{'ok' if k.active else 'danger'}}">{{'Ativa' if k.active else 'Revogada'}}</span></td><td>{{k.rooms_used}}{{'' if not k.max_rooms else ' / '+k.max_rooms|string}}</td><td>{{k.expires_at or 'Sem validade'}}</td><td>{% if k.active %}<form method="post" action="/admin/keys/{{k.id}}/revoke"><button>Revogar</button></form>{% endif %}</td></tr>{% endfor %}
</table></div></div></body></html>
"""

def now_utc():
    return datetime.now(timezone.utc)

def sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()

def admin_required():
    return session.get("admin") is True

def valid_key(row):
    if not row.get("active"):
        return False, "Chave revogada."
    expires = row.get("expires_at")
    if expires:
        try:
            dt = datetime.fromisoformat(expires.replace("Z", "+00:00"))
            if dt <= now_utc():
                return False, "Chave expirada."
        except ValueError:
            return False, "Validade da chave inválida."
    max_rooms = row.get("max_rooms")
    if max_rooms is not None and int(max_rooms) > 0 and int(row.get("rooms_used", 0)) >= int(max_rooms):
        return False, "Limite de salas atingido."
    return True, ""

def find_api_key(raw_key):
    result = db.table("api_keys").select("*").eq("key_hash", sha256(raw_key)).limit(1).execute()
    rows = result.data or []
    return rows[0] if rows else None

def rate_limit_ok(row):
    window_start = time.time() - 60
    events = db.table("api_key_events").select("id", count="exact").eq("api_key_id", row["id"]).eq("event_type", "room").gte("created_at", datetime.fromtimestamp(window_start, timezone.utc).isoformat()).execute()
    count = events.count or 0
    return count < int(row.get("rate_limit_per_minute") or 30)

@app.get("/")
def index():
    return jsonify({"name": "Shadow API", "status": "online", "endpoint": "/v1/rooms"})

@app.get("/v1")
def api_info():
    return jsonify({
        "name": "Shadow API",
        "version": "1.0",
        "authentication": "X-API-Key",
        "endpoints": {"create_room": "POST /v1/rooms"},
        "upstream": "Nix"
    })

@app.post("/v1/rooms")
def create_room():
    raw_key = request.headers.get("X-API-Key", "").strip()
    if not raw_key:
        return jsonify({"error": "missing_api_key"}), 401

    key = find_api_key(raw_key)
    if not key:
        return jsonify({"error": "invalid_api_key"}), 401

    ok, reason = valid_key(key)
    if not ok:
        return jsonify({"error": "api_key_unavailable", "message": reason}), 403

    if not rate_limit_ok(key):
        return jsonify({"error": "rate_limit_exceeded"}), 429

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "invalid_json", "message": "Envie um objeto JSON."}), 400

    headers = {"Content-Type": "application/json"}
    if NIX_API_TOKEN:
        headers[NIX_AUTH_HEADER] = NIX_AUTH_PREFIX + NIX_API_TOKEN

    try:
        upstream = requests.post(NIX_ROOMS_URL, json=payload, headers=headers, timeout=30)
        try:
            response_body = upstream.json()
        except ValueError:
            response_body = {"raw": upstream.text[:4000]}
    except requests.RequestException as exc:
        db.table("api_key_events").insert({"api_key_id": key["id"], "event_type":"room", "endpoint":"/v1/rooms", "status_code":502, "request_body":payload, "response_body":{"error":str(exc)}}).execute()
        return jsonify({"error":"upstream_unavailable"}), 502

    new_uses = int(key.get("rooms_used") or 0) + 1
    db.table("api_keys").update({"rooms_used":new_uses, "last_used_at":now_utc().isoformat()}).eq("id", key["id"]).execute()
    db.table("api_key_events").insert({"api_key_id":key["id"], "event_type":"room", "endpoint":"/v1/rooms", "status_code":upstream.status_code, "request_body":payload, "response_body":response_body}).execute()

    return jsonify(response_body), upstream.status_code

@app.get("/admin/login")
def login_page():
    return render_template_string(LOGIN_HTML, error=None)

@app.post("/admin/login")
def login():
    username = request.form.get("username", "")
    password = request.form.get("password", "")
    password_ok = (ADMIN_PASSWORD_HASH and check_password_hash(ADMIN_PASSWORD_HASH, password)) or (ADMIN_PASSWORD and secrets.compare_digest(password, ADMIN_PASSWORD))
    if username == ADMIN_USERNAME and password_ok:
        session["admin"] = True
        return redirect(url_for("dashboard"))
    return render_template_string(LOGIN_HTML, error="Usuário ou senha inválidos."), 401

@app.get("/admin/logout")
def logout():
    session.clear()
    return redirect(url_for("login_page"))

@app.get("/admin")
def dashboard():
    if not admin_required():
        return redirect(url_for("login_page"))
    rows = db.table("api_keys").select("*").order("created_at", desc=True).execute().data or []
    return render_template_string(DASHBOARD_HTML, keys=rows, new_key=request.args.get("new_key"))

@app.post("/admin/keys")
def create_api_key():
    if not admin_required():
        return redirect(url_for("login_page"))

    label = (request.form.get("label") or "Cliente").strip()[:80]
    days = max(1, int(request.form.get("days") or 1))
    max_rooms_raw = request.form.get("max_rooms", "").strip()
    max_rooms = int(max_rooms_raw) if max_rooms_raw else None
    if max_rooms is not None and max_rooms <= 0:
        max_rooms = None
    rate_limit = max(1, min(1000, int(request.form.get("rate_limit") or 30)))

    raw = "sh_" + secrets.token_urlsafe(32)
    created = now_utc()
    expires = created.replace(microsecond=0) + __import__("datetime").timedelta(days=days)

    db.table("api_keys").insert({
        "label": label,
        "key_prefix": raw[:10],
        "key_hash": sha256(raw),
        "expires_at": expires.isoformat(),
        "max_rooms": max_rooms,
        "rate_limit_per_minute": rate_limit
    }).execute()

    return redirect(url_for("dashboard", new_key=raw))

@app.post("/admin/keys/<int:key_id>/revoke")
def revoke_key(key_id):
    if not admin_required():
        return redirect(url_for("login_page"))
    db.table("api_keys").update({"active": False}).eq("id", key_id).execute()
    return redirect(url_for("dashboard"))

@app.get("/health")
def health():
    return jsonify({"status":"ok"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
