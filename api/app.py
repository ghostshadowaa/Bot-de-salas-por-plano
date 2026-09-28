import hashlib
import os
import secrets
import urllib.parse
from datetime import datetime, timezone, timedelta

import requests
from flask import Flask, jsonify, redirect, render_template_string, request, session
from supabase import create_client
from werkzeug.security import check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-me-in-render")
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=30)
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SECURE"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
NIX_API_TOKEN = os.environ.get("NIX_API_TOKEN", "")
NIX_BASE_URL = os.environ.get("NIX_BASE_URL", "https://salas.nixbot.vip").rstrip("/")
NIX_ROOMS_URL = f"{NIX_BASE_URL}/rooms"
NIX_AUTH_HEADER = "Authorization"
NIX_AUTH_PREFIX = "Bearer "
NIX_PAYMENT_CREATE_URL = os.environ.get("NIX_PAYMENT_CREATE_URL", "")
NIX_PAYMENT_AUTH_HEADER = os.environ.get("NIX_PAYMENT_AUTH_HEADER", "")
NIX_PAYMENT_AUTH_VALUE = os.environ.get("NIX_PAYMENT_AUTH_VALUE", "")
ADMIN_USERNAME = os.environ.get("PANEL_USERNAME", os.environ.get("ADMIN_USERNAME", "Shadow"))
ADMIN_PASSWORD_HASH = os.environ.get("PANEL_PASSWORD_HASH", os.environ.get("ADMIN_PASSWORD_HASH", ""))
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
DISCORD_CLIENT_ID = os.environ.get("DISCORD_CLIENT_ID", "")
DISCORD_CLIENT_SECRET = os.environ.get("DISCORD_CLIENT_SECRET", "")
DISCORD_REDIRECT_URI = os.environ.get("DISCORD_REDIRECT_URI", "")
ADMIN_DISCORD_USER_IDS = {item.strip() for item in os.environ.get("ADMIN_DISCORD_USER_IDS", "").split(",") if item.strip()}

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


def discord_user():
    return session.get("discord_user")



def discord_account_type(discord_user_id):
    if discord_user_id and str(discord_user_id) in ADMIN_DISCORD_USER_IDS:
        return "admin"
    return "user"

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


def reserve_room_credit(key_id, owner_user_id=None):
    if owner_user_id:
        result = db.rpc("reserve_wallet_credit", {"p_user_id": str(owner_user_id), "p_amount_cents": 5}).execute()
        return bool(result.data)
    result = db.rpc("reserve_room_credit", {"p_key_id": int(key_id)}).execute()
    return bool(result.data)


def refund_room_credit(key_id, owner_user_id=None):
    if owner_user_id:
        db.rpc("refund_wallet_credit", {"p_user_id": str(owner_user_id), "p_amount_cents": 5}).execute()
        return
    db.rpc("refund_room_credit", {"p_key_id": int(key_id)}).execute()


def wallet_for_user(user_id):
    row = db.table("user_wallets").select("*").eq("user_id", str(user_id)).limit(1).execute().data
    if row:
        return row[0]
    db.table("user_wallets").insert({"user_id": str(user_id), "balance_cents": 0}).execute()
    return {"user_id": str(user_id), "balance_cents": 0}


def create_deposit_payment(user_id, amount_cents):
    if not NIX_PAYMENT_CREATE_URL:
        raise RuntimeError("Pagamento Pix ainda não configurado no Render.")
    headers = {"Content-Type": "application/json"}
    if NIX_PAYMENT_AUTH_HEADER and NIX_PAYMENT_AUTH_VALUE:
        headers[NIX_PAYMENT_AUTH_HEADER] = NIX_PAYMENT_AUTH_VALUE
    payload = {
        "amount": amount_cents,
        "externalReference": f"shadow:{user_id}:{secrets.token_hex(8)}",
        "description": "Crédito Shadow API",
    }
    response = requests.post(NIX_PAYMENT_CREATE_URL, json=payload, headers=headers, timeout=20)
    try:
        data = response.json()
    except ValueError:
        data = {"raw": response.text[:4000]}
    if not 200 <= response.status_code < 300:
        raise RuntimeError(data.get("error") or data.get("message") or f"HTTP {response.status_code}")
    return data


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
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Shadow API • Painel</title>
<style>
:root{--bg:#070b16;--panel:#0d1426;--panel2:#101a31;--line:rgba(148,163,184,.16);--text:#e5eefc;--muted:#93a4bd;--brand:#7c3aed;--brand2:#22d3ee;--ok:#22c55e;--warn:#f59e0b;--bad:#ef4444;--shadow:0 20px 60px rgba(0,0,0,.45);--radius:18px}
*{box-sizing:border-box}html,body{height:100%;scroll-behavior:smooth}body{margin:0;font-family:Inter,ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,Arial;background:radial-gradient(circle at 20% 0%,rgba(124,58,237,.22),transparent 34%),radial-gradient(circle at 80% 10%,rgba(34,211,238,.12),transparent 28%),var(--bg);color:var(--text)}a{color:inherit;text-decoration:none}button{font:inherit}
.shell{display:grid;grid-template-columns:292px 1fr;min-height:100vh}.sidebar{position:sticky;top:0;height:100vh;padding:22px 16px;background:linear-gradient(180deg,rgba(13,20,38,.96),rgba(9,14,27,.96));border-right:1px solid var(--line);backdrop-filter:blur(14px);z-index:30;transition:.25s;overflow:hidden}
.brand{display:flex;align-items:center;gap:12px;padding:10px 12px 18px;border-bottom:1px solid var(--line)}.logo{width:42px;height:42px;border-radius:14px;background:linear-gradient(135deg,var(--brand),#4f46e5 55%,var(--brand2));box-shadow:0 12px 35px rgba(124,58,237,.35);display:grid;place-items:center;font-weight:900;letter-spacing:-.06em}.brand small{display:block;color:var(--muted);font-size:12px;margin-top:2px}
.nav{margin-top:18px;display:grid;gap:8px}.nav button,.nav a{width:100%;display:flex;align-items:center;gap:12px;padding:12px 13px;border:1px solid transparent;border-radius:14px;background:transparent;color:var(--muted);cursor:pointer;text-align:left;transition:.18s}.nav button:hover,.nav a:hover{background:rgba(148,163,184,.08);color:var(--text)}.nav .active{background:linear-gradient(135deg,rgba(124,58,237,.28),rgba(34,211,238,.10));border-color:rgba(124,58,237,.38);color:var(--text);box-shadow:inset 0 1px 0 rgba(255,255,255,.05)}.icon{width:22px;height:22px;display:grid;place-items:center;flex:0 0 auto}.label{white-space:nowrap}.side-foot{margin-top:auto;padding:14px;border:1px solid var(--line);border-radius:16px;background:rgba(255,255,255,.03)}
.pill{display:inline-flex;align-items:center;gap:8px;padding:6px 10px;border-radius:999px;font-size:12px;font-weight:700}.dot{width:8px;height:8px;border-radius:50%;background:var(--ok);box-shadow:0 0 0 6px rgba(34,197,94,.12)}.pill.ok{color:#86efac;background:rgba(34,197,94,.12);border:1px solid rgba(34,197,94,.25)}
.main{min-width:0;padding:24px;position:relative}.topbar{position:sticky;top:0;z-index:20;display:flex;align-items:center;justify-content:space-between;gap:16px;padding:14px 16px;border:1px solid var(--line);border-radius:20px;background:rgba(7,11,22,.72);backdrop-filter:blur(16px);box-shadow:0 10px 30px rgba(0,0,0,.20)}.left{display:flex;align-items:center;gap:12px;min-width:0}.hamburger{width:42px;height:42px;border:1px solid var(--line);border-radius:14px;background:rgba(255,255,255,.04);color:var(--text);cursor:pointer;display:grid;place-items:center}.title{min-width:0}.title h1{margin:0;font-size:18px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.title p{margin:2px 0 0;color:var(--muted);font-size:13px}.actions{display:flex;gap:10px;align-items:center}.btn{border:1px solid var(--line);border-radius:14px;padding:11px 14px;background:rgba(255,255,255,.04);color:var(--text);cursor:pointer}.btn.primary{background:linear-gradient(135deg,var(--brand),#4f46e5);border-color:rgba(124,58,237,.55);font-weight:800}
.grid{display:grid;gap:16px;margin-top:18px}.cards{grid-template-columns:repeat(4,minmax(0,1fr))}.card,.panel{border:1px solid var(--line);border-radius:var(--radius);background:linear-gradient(180deg,rgba(255,255,255,.045),rgba(255,255,255,.02));box-shadow:var(--shadow);padding:18px;min-width:0}.card h3{margin:0;color:var(--muted);font-size:13px}.metric{font-size:34px;font-weight:900;margin-top:8px;letter-spacing:-.05em}.sub{color:var(--muted);font-size:13px;margin-top:6px}.two{grid-template-columns:1.35fr .85fr}.section{display:none;animation:fade .22s ease}.section.active{display:block}@keyframes fade{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
.panel-head{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;margin-bottom:16px}.panel h2{margin:0;font-size:17px}.panel p{margin:6px 0 0;color:var(--muted);line-height:1.55}.form{display:grid;grid-template-columns:1fr 1fr;gap:14px}.field{display:grid;gap:7px}.field.full{grid-column:1/-1}label{font-size:13px;color:#cbd5e1;font-weight:800}input,select,textarea{width:100%;border:1px solid var(--line);border-radius:14px;background:rgba(2,6,23,.42);color:var(--text);padding:12px 13px;outline:none}.hint{font-size:12px;color:var(--muted)}
.code{position:relative;margin-top:14px;border:1px solid rgba(34,211,238,.25);background:#020617;border-radius:18px;padding:16px;overflow:auto}.code pre{margin:0;color:#c4b5fd;font-size:13px;line-height:1.7}.copy{position:absolute;right:12px;top:12px}
.list{display:grid;gap:12px}.row{display:flex;align-items:center;justify-content:space-between;gap:14px;border:1px solid var(--line);border-radius:16px;padding:14px;background:rgba(255,255,255,.03)}.row b{display:block}.row span{color:var(--muted);font-size:13px}.tag{font-size:12px;font-weight:900;padding:6px 10px;border-radius:999px}.tag.ok{color:#86efac;background:rgba(34,197,94,.12)}.tag.warn{color:#fcd34d;background:rgba(245,158,11,.12)}.tag.lock{color:#fca5a5;background:rgba(239,68,68,.12)}.empty{padding:28px;text-align:center;color:var(--muted);border:1px dashed rgba(148,163,184,.26);border-radius:18px;background:rgba(255,255,255,.02)}
.toast{position:fixed;right:20px;bottom:20px;z-index:80;padding:12px 14px;border-radius:14px;background:#0f172a;border:1px solid rgba(34,197,94,.35);color:#bbf7d0;box-shadow:var(--shadow);opacity:0;transform:translateY(12px);pointer-events:none;transition:.25s}.toast.show{opacity:1;transform:none}.shell.collapsed .sidebar{width:92px}.shell.collapsed .label,.shell.collapsed .brand small,.shell.collapsed .side-foot{display:none}.shell.collapsed .nav button,.shell.collapsed .nav a{justify-content:center;padding:12px}.shell.collapsed .brand{justify-content:center;padding-bottom:14px}
@media(max-width:1150px){.cards{grid-template-columns:repeat(2,minmax(0,1fr))}.two{grid-template-columns:1fr}}@media(max-width:860px){.shell{grid-template-columns:1fr}.sidebar{position:fixed;left:0;transform:translateX(-105%);width:292px}.shell.mobile-open .sidebar{transform:none}.shell.collapsed .sidebar{width:292px}.shell.collapsed .label,.shell.collapsed .brand small,.shell.collapsed .side-foot{display:block}.shell.collapsed .nav button,.shell.collapsed .nav a{justify-content:flex-start}.overlay.show{display:block}.main{padding:16px}.actions .btn:not(.primary){display:none}.cards{grid-template-columns:1fr}.form{grid-template-columns:1fr}.topbar{align-items:flex-start}.title p{display:none}}.overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,.52);z-index:25;backdrop-filter:blur(3px)}
</style></head>
<body>
<div class="overlay" id="overlay"></div><div class="shell" id="shell">
<aside class="sidebar"><div class="brand"><div class="logo">S</div><div><strong>Shadow API</strong><small>Central de gerenciamento</small></div></div>
<nav class="nav">
<button class="active" data-target="overview"><span class="icon">⌂</span><span class="label">Visão Geral</span></button>
<button data-target="api"><span class="icon">◈</span><span class="label">API</span></button>
<button data-target="bot"><span class="icon">◆</span><span class="label">Bot</span></button>
<button data-target="rooms"><span class="icon">◉</span><span class="label">Salas</span></button>
<button data-target="hosting"><span class="icon">▣</span><span class="label">Hospedagem de Bots 🔒</span></button>
<button data-target="mediator"><span class="icon">♢</span><span class="label">Auto Mediador 🔒</span></button>
<button data-target="docs"><span class="icon">▤</span><span class="label">Documentação</span></button>
<button data-target="status"><span class="icon">●</span><span class="label">Status</span></button></nav>
<div class="side-foot"><span class="pill ok"><span class="dot"></span> API online</span></div></aside>
<main class="main"><header class="topbar"><div class="left"><button class="hamburger" id="hamburger">☰</button><div class="title"><h1 id="pageTitle">Painel / Visão Geral</h1><p>Gerencie suas chaves e acompanhe a operação da Shadow API.</p></div></div><div class="actions"><a class="btn" href="/health">Status</a><button class="btn primary" data-goto="api">+ Nova API Key</button></div></header>
<div class="grid">
<section id="overview" class="section active"><div class="grid cards">
<div class="card"><h3>Serviço operacional</h3><div class="metric">Online</div><div class="sub">API respondendo normalmente</div></div>
<div class="card"><h3>Total de chaves</h3><div class="metric">{{keys|length}}</div><div class="sub">Chaves cadastradas</div></div>
<div class="card"><h3>Chaves ativas</h3><div class="metric">{{active_count}}</div><div class="sub">Prontas para requisições</div></div>
<div class="card"><h3>Salas utilizadas</h3><div class="metric">{{rooms_used}}</div><div class="sub">Cada sala bem-sucedida custa R$ 0,05</div></div></div>
<div class="grid two"><div class="panel"><div class="panel-head"><div><h2>Integração rápida</h2><p>Sua aplicação usa a Shadow API. O token privado da Nix nunca é enviado ao cliente.</p></div><button class="btn" data-goto="docs">Documentação →</button></div><div class="code"><button class="btn copy" data-copy>Copiar</button><pre>POST /v1/rooms
X-API-Key: sk_sua_chave
Content-Type: application/json</pre></div></div>
<div class="panel"><div class="panel-head"><div><h2>Entregas recebidas</h2><p>Vendas e webhooks recebidos pela API.</p></div><span class="tag ok">{{deliveries|length}} recentes</span></div>{% if deliveries %}<div class="list">{% for d in deliveries[:3] %}<div class="row"><div><b>{{d.external_username or d.external_user_id or "Cliente não informado"}}</b><span>Venda: {{d.external_sale_id or "—"}} · {{d.product_name or "—"}}</span></div><span class="tag ok">Recebida</span></div>{% endfor %}</div>{% else %}<div class="empty">Nenhuma entrega recebida ainda.</div>{% endif %}</div></div></section>

<section id="api" class="section"><div class="grid two"><div class="panel"><div class="panel-head"><div><h2>Criar nova API Key</h2><p>Crie uma credencial para um cliente ou integração. A chave completa será exibida apenas uma vez.</p></div></div>
<form class="form" method="post" action="/admin/keys"><div class="field full"><label>Nome do cliente ou integração</label><input name="label" placeholder="Ex.: app-mobile, gateway-pagamentos, bot-discord" required></div><div class="field"><label>Validade</label><select name="days"><option value="1">1 dia</option><option value="7">7 dias</option><option value="30" selected>30 dias</option><option value="90">90 dias</option><option value="365">365 dias</option></select></div><div class="field"><label>Discord User ID — opcional</label><input name="owner_user_id" placeholder="123456789012345678"></div><div class="field"><label>Limite de salas</label><input name="max_rooms" type="number" min="0" placeholder="Ilimitado"></div><div class="field"><label>Requests por minuto</label><input name="rate_limit" type="number" min="1" value="30"></div><div class="field full"><button class="btn primary" type="submit">+ Criar API Key</button></div></form><div class="hint">Deixe o limite de salas vazio ou 0 para permitir uso ilimitado.</div></div>
<div class="panel"><div class="panel-head"><div><h2>Chaves cadastradas</h2><p>Gerencie limites, status e revogação.</p></div><span class="tag warn">{{keys|length}} cadastradas</span></div><div class="list">{% for k in keys[:6] %}<div class="row"><div><b>{{k.label}}</b><span>{{k.key_prefix}}•••• · Saldo R$ {{"%.2f"|format((k.balance_cents or 0)/100)}}</span></div>{% if k.active %}<span class="tag ok">Ativa</span>{% else %}<span class="tag lock">Pausada</span>{% endif %}</div>{% else %}<div class="empty">Nenhuma API Key criada ainda.</div>{% endfor %}</div></div></div>
{% if new_key %}<div class="panel" style="margin-top:16px;border-color:rgba(34,197,94,.35)"><h2 style="margin:0;color:#86efac">✓ API Key criada com sucesso</h2><p>Guarde esta chave agora. Ela não será exibida novamente.</p><div class="code"><pre>{{new_key}}</pre></div><button class="btn primary" onclick="navigator.clipboard.writeText({{new_key|tojson}});flash('Chave copiada!')">Copiar chave</button></div>{% endif %}</section>

<section id="bot" class="section"><div class="panel"><div class="panel-head"><div><h2>Bot</h2><p>Estrutura preparada para integrar os recursos do Bot da Nix ao Shadow Panel.</p></div><span class="tag warn">EM PREPARAÇÃO</span></div><div class="list"><div class="row"><div><b>Visão Geral</b><span>Indicadores e atividade do bot</span></div><span class="tag ok">Planejado</span></div><div class="row"><div><b>Seu Bot</b><span>Gerenciamento e integração</span></div><span class="tag ok">Planejado</span></div><div class="row"><div><b>Configurações</b><span>Preferências do servidor</span></div><span class="tag ok">Planejado</span></div><div class="row"><div><b>Membros</b><span>Dados e gerenciamento</span></div><span class="tag ok">Planejado</span></div></div></div></section>

<section id="rooms" class="section"><div class="grid two"><div class="panel"><div class="panel-head"><div><h2>Criar sala personalizada</h2><p>Crie uma sala diretamente pelo Shadow Panel. A autenticação é feita pela sessão do painel e o token da Nix permanece privado no servidor.</p></div><span class="tag ok">AUTENTICADO</span></div><form class="form" method="post" action="/admin/rooms"><div class="field full"><label>Nome da sala</label><input name="room_name" value="Shadow Salas" maxlength="100" required></div><div class="field"><label>Tipo de configuração</label><select name="config_type"><option value="ap_padrao">AP Padrão</option><option value="gelo_inf">Gelo Infinito</option><option value="tatico">Tático</option><option value="ap_fullcapa">AP Full Capa</option><option value="capa_3">Capa 3</option><option value="ap_uxd">AP UXD</option><option value="ap_7r">AP 7R</option><option value="br_padrao">BR Padrão</option></select></div><div class="field"><label>Senha</label><input name="password" value="00" maxlength="20" required></div><div class="field"><label>Delay inicial (minutos)</label><input name="start_delay_minutes" type="number" min="1" max="20" value="1" required></div><div class="field"><label>Mapa</label><select name="map_name"><option>Bermuda</option><option>Purgatory</option><option>Kalahari</option><option>Nextera</option><option>Nova Terra</option><option>Solara</option></select></div><div class="field full"><button class="btn primary" type="submit">Criar sala</button></div></form>{% if room_result %}<div class="code"><pre>{{room_result|tojson(indent=2)}}</pre></div>{% endif %}</div><div class="panel"><div class="panel-head"><div><h2>Como funciona</h2><p>O navegador nunca recebe o token privado da Nix.</p></div></div><div class="list"><div class="row"><div><b>1. Login</b><span>O acesso exige a autenticação do Shadow Panel.</span></div><span class="tag ok">Auth</span></div><div class="row"><div><b>2. Shadow API</b><span>O painel envia a configuração para o servidor.</span></div><span class="tag ok">Seguro</span></div><div class="row"><div><b>3. Nix API</b><span>O servidor chama POST /rooms usando NIX_API_TOKEN.</span></div><span class="tag ok">Privado</span></div></div></div></div></section>

<section id="hosting" class="section"><div class="panel"><div class="panel-head"><div><h2>Hospedagem de Bots</h2><p>Este módulo está reservado para uma futura etapa do Shadow Panel.</p></div><span class="tag lock">INDISPONÍVEL 🔒</span></div><div class="list"><div class="row"><div><b>Criar hospedagem</b><span>Indisponível</span></div><span class="tag lock">Bloqueado</span></div><div class="row"><div><b>Seus bots</b><span>Indisponível</span></div><span class="tag lock">Bloqueado</span></div><div class="row"><div><b>Planos</b><span>Indisponível</span></div><span class="tag lock">Bloqueado</span></div></div></div></section>

<section id="mediator" class="section"><div class="panel"><div class="panel-head"><div><h2>Auto Mediador</h2><p>Este módulo permanece bloqueado enquanto a integração dos recursos da Nix está sendo construída.</p></div><span class="tag lock">INDISPONÍVEL 🔒</span></div><div class="list"><div class="row"><div><b>Visão Geral</b><span>Resumo do módulo</span></div><span class="tag warn">Em desenvolvimento</span></div><div class="row"><div><b>Como Funciona</b><span>Fluxo de mediação</span></div><span class="tag warn">Em desenvolvimento</span></div><div class="row"><div><b>Estatísticas</b><span>Métricas de uso</span></div><span class="tag warn">Em desenvolvimento</span></div></div></div></section>

<section id="docs" class="section"><div class="panel"><div class="panel-head"><div><h2>Documentação</h2><p>Referência rápida para autenticação e criação de salas.</p></div><span class="pill ok"><span class="dot"></span> Online</span></div><div class="code"><button class="btn copy" data-copy>Copiar</button><pre>POST /v1/rooms
X-API-Key: sk_sua_chave
Content-Type: application/json

{
  "config_type": "ap_padrao",
  "password": "00",
  "start_delay_minutes": 1,
  "map_name": "Bermuda",
  "room_name": "Shadow Salas"
}</pre></div><p class="sub">Cada criação de sala bem-sucedida consome R$ 0,05 do saldo da API Key.</p></div></section>

<section id="status" class="section"><div class="grid cards"><div class="card"><h3>API</h3><div class="metric">Online</div><div class="sub">Serviço respondendo</div></div><div class="card"><h3>Supabase</h3><div class="metric">OK</div><div class="sub">Banco configurado</div></div><div class="card"><h3>Provedor</h3><div class="metric">{{"OK" if config_provider else "—"}}</div><div class="sub">Nix API configurada no servidor</div></div><div class="card"><h3>Região</h3><div class="metric">OR</div><div class="sub">Render Oregon</div></div></div></section>
</div></main></div>
<div class="toast" id="toast"></div>
<script>
const shell=document.getElementById('shell'),overlay=document.getElementById('overlay'),burger=document.getElementById('hamburger'),toast=document.getElementById('toast');
const mobile=()=>matchMedia('(max-width:860px)').matches;
burger.addEventListener('click',()=>{if(mobile()){shell.classList.toggle('mobile-open');overlay.classList.toggle('show',shell.classList.contains('mobile-open'))}else shell.classList.toggle('collapsed')});
overlay.addEventListener('click',()=>{shell.classList.remove('mobile-open');overlay.classList.remove('show')});
function show(id){document.querySelectorAll('.section').forEach(s=>s.classList.toggle('active',s.id===id));document.querySelectorAll('.nav [data-target]').forEach(b=>b.classList.toggle('active',b.dataset.target===id));const names={overview:'Visão Geral',api:'API',bot:'Bot',rooms:'Salas',hosting:'Hospedagem de Bots',mediator:'Auto Mediador',docs:'Documentação',status:'Status'};document.getElementById('pageTitle').textContent='Painel / '+names[id];if(mobile()){shell.classList.remove('mobile-open');overlay.classList.remove('show')}window.scrollTo({top:0,behavior:'smooth'})}
document.querySelectorAll('[data-target]').forEach(el=>el.addEventListener('click',e=>{e.preventDefault();show(el.dataset.target)}));
document.querySelectorAll('[data-goto]').forEach(el=>el.addEventListener('click',()=>show(el.dataset.goto)));
function flash(msg){toast.textContent=msg;toast.classList.add('show');clearTimeout(flash.t);flash.t=setTimeout(()=>toast.classList.remove('show'),1800)}
document.querySelectorAll('[data-copy]').forEach(btn=>btn.addEventListener('click',async()=>{const pre=btn.parentElement.querySelector('pre').innerText;try{await navigator.clipboard.writeText(pre);flash('Copiado para a área de transferência.')}catch{flash('Não foi possível copiar automaticamente.')}}));
</script></body></html>
"""

HOME_HTML = """
<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Shadow API</title><style>
*{box-sizing:border-box}body{margin:0;background:#070b16;color:#e8eefc;font-family:Inter,system-ui,Arial}.wrap{max-width:1100px;margin:auto;padding:28px}.nav{display:flex;justify-content:space-between;align-items:center;padding:14px 0}.logo{font-weight:900;font-size:22px}.btn{display:inline-block;padding:11px 16px;border-radius:12px;text-decoration:none;color:#fff;background:linear-gradient(135deg,#7c3aed,#4f46e5);font-weight:800}.ghost{background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.12)}.hero{padding:70px 0 40px;max-width:780px}.badge{display:inline-block;padding:7px 11px;border-radius:999px;background:rgba(124,58,237,.14);border:1px solid rgba(124,58,237,.3);color:#c4b5fd;font-size:13px}.hero h1{font-size:clamp(38px,7vw,70px);line-height:1.02;margin:18px 0}.muted{color:#94a3b8;line-height:1.65}.actions{display:flex;gap:10px;flex-wrap:wrap;margin-top:24px}.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin-top:35px}.card{padding:22px;border:1px solid rgba(148,163,184,.15);border-radius:18px;background:#0d1426}.card h3{margin-top:0}.code{margin-top:10px;padding:12px;border-radius:10px;background:#080c16;color:#c4b5fd;overflow:auto}.footer{margin-top:45px;padding:22px 0;border-top:1px solid rgba(148,163,184,.12);color:#64748b}@media(max-width:750px){.grid{grid-template-columns:1fr}.hero{padding-top:45px}}</style></head>
<body><div class="wrap"><nav class="nav"><div class="logo">🟣 Shadow API</div><div class="actions"><a class="btn ghost" href="/docs">Documentação</a><a class="btn" href="/login">Dashboard</a></div></nav>
<section class="hero"><span class="badge">API para criação de salas</span><h1>Uma prévia do seu painel Shadow.</h1><p class="muted">Depois do login você terá acesso ao Dashboard, gerenciamento de API Keys, criação de salas, saldo, histórico de requisições, webhook e documentação completa da integração.</p><div class="actions"><a class="btn" href="/login">Entrar com Discord</a><a class="btn ghost" href="/docs">Ver documentação</a></div></section>
<section class="grid"><div class="card"><h3>🔑 API Keys</h3><p class="muted">Crie e gerencie chaves para integrar seu sistema à Shadow API.</p></div><div class="card"><h3>🎮 Salas</h3><p class="muted">Envie requisições para criar salas sem expor o token privado do provedor.</p></div><div class="card"><h3>💰 Saldo</h3><p class="muted">Acompanhe o saldo disponível e o consumo por criação de sala.</p></div><div class="card"><h3>📡 Webhook</h3><p class="muted">Receba eventos do seu sistema de vendas e acompanhe as entregas no painel.</p></div><div class="card"><h3>📚 Documentação</h3><p class="muted">Exemplos de integração com cURL, Python, autenticação e respostas HTTP.</p></div><div class="card"><h3>🛡️ Segurança</h3><p class="muted">API Keys ficam protegidas por hash e o token do provedor permanece somente no servidor.</p></div></section>
<div class="footer">Shadow API • Acesse o Dashboard usando sua conta do Discord.</div></div></body></html>
"""

DOCS_HTML = """
<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Shadow API • Documentação</title>
<style>*{box-sizing:border-box}body{margin:0;background:#070b16;color:#e5eefc;font-family:Inter,system-ui,Arial}.wrap{max-width:1050px;margin:auto;padding:24px}.top{display:flex;justify-content:space-between;gap:12px;align-items:center}.brand{font-size:21px;font-weight:900}.actions{display:flex;gap:9px}.btn{display:inline-block;padding:10px 14px;border-radius:12px;border:1px solid #334155;background:#111827;color:#fff;text-decoration:none;cursor:pointer}.primary,.tab.active{background:#7c3aed;border-color:#7c3aed}.card{margin-top:16px;padding:20px;border:1px solid #1e293b;border-radius:18px;background:#0d1426}.muted{color:#94a3b8;line-height:1.6}.method{color:#c4b5fd;font-weight:900}.code{margin-top:12px;background:#020617;border:1px solid #1e293b;border-radius:14px;overflow:auto}.code pre{margin:0;padding:16px;color:#c4b5fd;font-size:13px;line-height:1.65;white-space:pre-wrap}.tabs{display:flex;gap:8px;flex-wrap:wrap;margin:15px 0}.tab{color:#fff}.lang{display:none}.lang.active{display:block}.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}.tag{display:inline-block;padding:5px 9px;border-radius:999px;background:#14532d;color:#bbf7d0;font-size:12px;font-weight:800}li{margin:8px 0;color:#cbd5e1}@media(max-width:700px){.top{align-items:flex-start;flex-direction:column}.grid{grid-template-columns:1fr}}</style></head>
<body><div class="wrap"><header class="top"><div class="brand">🟣 Shadow API</div><div class="actions"><a class="btn" href="/">Início</a><a class="btn primary" href="/dashboard">Dashboard</a></div></header>
<section class="card"><span class="tag">API v1</span><h1>Documentação</h1><p class="muted">Integre sua aplicação para criar salas através da Shadow API. A API Key é enviada em <b>X-API-Key</b> e o token privado do provedor permanece somente no servidor.</p><div class="code"><pre>Base URL: {{base_url}}</pre></div></section>
<section class="card"><h2>Autenticação</h2><p class="muted">Todas as chamadas para criação de salas precisam da sua API Key.</p><div class="code"><pre>X-API-Key: sk_sua_chave
Content-Type: application/json</pre></div><p class="muted">Não coloque a chave em frontend público, HTML, aplicativo distribuído ou repositório público. Prefira o backend.</p></section>
<section class="card"><h2><span class="method">POST</span> /v1/rooms</h2><p class="muted">Cria uma sala e repassa a resposta do provedor.</p><div class="code"><pre>{
  "config_type": "ap_padrao",
  "password": "00",
  "start_delay_minutes": 1,
  "map_name": "Bermuda",
  "room_name": "Shadow Salas"
}</pre></div><h3>Configurações</h3><p class="muted"><b>config_type:</b> ap_padrao, gelo_inf, tatico, ap_fullcapa, capa_3, ap_uxd, ap_7r ou br_padrao.</p><p class="muted"><b>password:</b> senha da sala. <b>start_delay_minutes:</b> delay inicial. <b>map_name:</b> mapa. <b>room_name:</b> nome da sala.</p></section>
<section class="card"><h2>Exemplos por linguagem</h2><div class="tabs"><button class="btn tab active" data-l="curl">cURL</button><button class="btn tab" data-l="python">Python</button><button class="btn tab" data-l="node">Node.js</button><button class="btn tab" data-l="php">PHP</button><button class="btn tab" data-l="java">Java</button><button class="btn tab" data-l="csharp">C#</button><button class="btn tab" data-l="go">Go</button></div>
<div id="curl" class="lang active"><div class="code"><pre>curl -X POST "{{base_url}}/v1/rooms" \
  -H "X-API-Key: sk_sua_chave" \
  -H "Content-Type: application/json" \
  -d '{"config_type":"ap_padrao","password":"00","start_delay_minutes":1,"map_name":"Bermuda","room_name":"Shadow Salas"}'</pre></div></div>
<div id="python" class="lang"><div class="code"><pre>import requests

response = requests.post(
    "{{base_url}}/v1/rooms",
    headers={"X-API-Key": "sk_sua_chave"},
    json={
        "config_type": "ap_padrao",
        "password": "00",
        "start_delay_minutes": 1,
        "map_name": "Bermuda",
        "room_name": "Shadow Salas"
    },
    timeout=20
)

print(response.status_code)
print(response.json())</pre></div><p class="muted">Instalação: pip install requests</p></div>
<div id="node" class="lang"><div class="code"><pre>const response = await fetch("{{base_url}}/v1/rooms", {
  method: "POST",
  headers: {
    "X-API-Key": "sk_sua_chave",
    "Content-Type": "application/json"
  },
  body: JSON.stringify({
    config_type: "ap_padrao",
    password: "00",
    start_delay_minutes: 1,
    map_name: "Bermuda",
    room_name: "Shadow Salas"
  })
});

console.log(response.status);
console.log(await response.json());</pre></div><p class="muted">Node.js moderno possui fetch nativo.</p></div>
<div id="php" class="lang"><div class="code"><pre>&lt;?php
$ch = curl_init("{{base_url}}/v1/rooms");
curl_setopt_array($ch, [
  CURLOPT_POST =&gt; true,
  CURLOPT_HTTPHEADER =&gt; ["X-API-Key: sk_sua_chave", "Content-Type: application/json"],
  CURLOPT_POSTFIELDS =&gt; json_encode([
    "config_type" =&gt; "ap_padrao",
    "password" =&gt; "00",
    "start_delay_minutes" =&gt; 1,
    "map_name" =&gt; "Bermuda",
    "room_name" =&gt; "Shadow Salas"
  ]),
  CURLOPT_RETURNTRANSFER =&gt; true
]);
echo curl_exec($ch);
curl_close($ch);</pre></div></div>
<div id="java" class="lang"><div class="code"><pre>String json = "{\"config_type\":\"ap_padrao\",\"password\":\"00\",\"start_delay_minutes\":1,\"map_name\":\"Bermuda\",\"room_name\":\"Shadow Salas\"}";

HttpRequest request = HttpRequest.newBuilder()
  .uri(URI.create("{{base_url}}/v1/rooms"))
  .header("X-API-Key", "sk_sua_chave")
  .header("Content-Type", "application/json")
  .POST(HttpRequest.BodyPublishers.ofString(json))
  .build();

HttpResponse&lt;String&gt; response = HttpClient.newHttpClient()
  .send(request, HttpResponse.BodyHandlers.ofString());

System.out.println(response.body());</pre></div></div>
<div id="csharp" class="lang"><div class="code"><pre>using System.Net.Http.Json;

var client = new HttpClient();
client.DefaultRequestHeaders.Add("X-API-Key", "sk_sua_chave");

var payload = new {
  config_type = "ap_padrao",
  password = "00",
  start_delay_minutes = 1,
  map_name = "Bermuda",
  room_name = "Shadow Salas"
};

var response = await client.PostAsJsonAsync("{{base_url}}/v1/rooms", payload);
Console.WriteLine(await response.Content.ReadAsStringAsync());</pre></div></div>
<div id="go" class="lang"><div class="code"><pre>package main

import (
  "bytes"
  "net/http"
)

func main() {
  body := []byte(`{"config_type":"ap_padrao","password":"00","start_delay_minutes":1,"map_name":"Bermuda","room_name":"Shadow Salas"}`)
  req, _ := http.NewRequest("POST", "{{base_url}}/v1/rooms", bytes.NewBuffer(body))
  req.Header.Set("X-API-Key", "sk_sua_chave")
  req.Header.Set("Content-Type", "application/json")
  res, _ := http.DefaultClient.Do(req)
  defer res.Body.Close()
}</pre></div></div>
</section>
<div class="grid"><section class="card"><h2>Respostas</h2><p class="muted">Em sucesso, a resposta JSON do provedor é repassada pela Shadow API. Ela pode conter dados como ID da sala, senha e link de convite.</p></section><section class="card"><h2>Códigos HTTP</h2><ul><li><b>400</b> — JSON inválido ou ausente.</li><li><b>401</b> — API Key ausente, inválida, pausada ou expirada.</li><li><b>402</b> — saldo insuficiente.</li><li><b>403</b> — limite de salas atingido.</li><li><b>502</b> — falha ao comunicar com o provedor.</li></ul></section><section class="card"><h2>Consumo</h2><p class="muted">Cada criação de sala bem-sucedida consome <b>R$ 0,05</b>. Em falhas, o valor reservado é devolvido.</p></section><section class="card"><h2>Segurança</h2><ul><li>Mantenha a API Key no backend.</li><li>Não publique a chave no GitHub.</li><li>Use HTTPS.</li><li>Se uma chave vazar, solicite ao administrador a pausa ou remoção.</li></ul></section></div>
</div><script>
document.querySelectorAll(".tab").forEach(b=>b.addEventListener("click",()=>{document.querySelectorAll(".tab").forEach(x=>x.classList.remove("active"));document.querySelectorAll(".lang").forEach(x=>x.classList.remove("active"));b.classList.add("active");document.getElementById(b.dataset.l).classList.add("active")}));
</script></body></html>
"""


@app.get("/")
def home():
    return render_template_string(HOME_HTML)

@app.post("/")
def ag_webhook_root():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"ok": False, "error": "O corpo do webhook deve ser JSON"}), 400
    try:
        delivery = register_delivery(payload)
        discord_user_id = (payload.get("discord_user_id") or payload.get("discordId"))
        if not discord_user_id:
            for key in ("user", "customer", "buyer"):
                obj = payload.get(key)
                if isinstance(obj, dict):
                    discord_user_id = obj.get("discord_user_id") or obj.get("discordId")
                    if discord_user_id:
                        break
        return jsonify({
            "ok": True,
            "received": True,
            "delivery_id": delivery.get("id") if delivery else None,
            "api_key_linked": bool(delivery and delivery.get("api_key_id")),
            "discord_user_id": str(discord_user_id) if discord_user_id else None,
            "account_type": discord_account_type(discord_user_id),
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

    # Cada criação de sala custa R$ 0,05.
    # O valor é reservado antes da chamada para impedir que duas requisições
    # concorrentes criem salas sem saldo. Se a Nix não criar a sala,
    # o valor é devolvido automaticamente.
    try:
        if not reserve_room_credit(key["id"], key.get("owner_user_id")):
            response = {
                "error": "Saldo insuficiente",
                "required_cents": 5,
                "balance_cents": int(key.get("balance_cents") or 0),
            }
            log_event(key["id"], "room_request", 402, payload, response)
            return jsonify(response), 402

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
            refund_room_credit(key["id"], key.get("owner_user_id"))
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
        else:
            # A sala não foi criada com sucesso: devolve os R$ 0,05 reservados.
            refund_room_credit(key["id"])

        return jsonify(response), upstream.status_code
    except requests.RequestException:
        refund_room_credit(key["id"])
        response = {"error": "Falha ao comunicar com o provedor"}
        log_event(key["id"], "room_request", 502, payload, response)
        return jsonify(response), 502


@app.post("/admin/rooms")
def admin_create_room():
    if not admin():
        return redirect("/admin/login")

    room_name = request.form.get("room_name", "Shadow Salas").strip() or "Shadow Salas"
    config_type = request.form.get("config_type", "ap_padrao").strip() or "ap_padrao"
    password = request.form.get("password", "00").strip() or "00"

    try:
        delay = max(1, min(20, int(request.form.get("start_delay_minutes", "1"))))
    except ValueError:
        delay = 1

    map_name = request.form.get("map_name", "Bermuda").strip() or "Bermuda"
    payload = {
        "password": password,
        "start_delay_minutes": delay,
        "config_type": config_type,
        "room_name": room_name,
        "map_name": map_name,
    }

    try:
        upstream = requests.post(
            NIX_ROOMS_URL,
            json=payload,
            headers={
                "Authorization": f"Bearer {NIX_API_TOKEN}",
                "Content-Type": "application/json",
            },
            timeout=15,
        )
        try:
            result = upstream.json()
        except ValueError:
            result = {"raw": upstream.text[:4000]}
        session["room_result"] = {
            "ok": 200 <= upstream.status_code < 300,
            "status": upstream.status_code,
            "response": result,
        }
    except requests.RequestException as exc:
        session["room_result"] = {
            "ok": False,
            "status": 502,
            "error": "Não foi possível conectar à API da Nix",
        }

    return redirect("/admin#rooms")


@app.get("/login")
def login():
    if discord_user():
        return redirect("/dashboard")
    if admin():
        return redirect("/admin")
    if not (DISCORD_CLIENT_ID and DISCORD_CLIENT_SECRET and DISCORD_REDIRECT_URI):
        return render_template_string(LOGIN_HTML, error="Login com Discord ainda não foi configurado no servidor."), 503
    params = urllib.parse.urlencode({
        "client_id": DISCORD_CLIENT_ID,
        "redirect_uri": DISCORD_REDIRECT_URI,
        "response_type": "code",
        "scope": "identify",
    })
    session["oauth_state"] = secrets.token_urlsafe(24)
    params += "&state=" + urllib.parse.quote(session["oauth_state"])
    return redirect("https://discord.com/oauth2/authorize?" + params)


@app.get("/auth/discord/callback")
def discord_callback():
    if request.args.get("state") != session.pop("oauth_state", None):
        return render_template_string(LOGIN_HTML, error="Sessão de autenticação inválida."), 400
    code = request.args.get("code", "")
    if not code:
        return render_template_string(LOGIN_HTML, error="Autorização do Discord não concluída."), 400
    try:
        token = requests.post("https://discord.com/api/oauth2/token", data={
            "client_id": DISCORD_CLIENT_ID,
            "client_secret": DISCORD_CLIENT_SECRET,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": DISCORD_REDIRECT_URI,
        }, timeout=15)
        token.raise_for_status()
        access_token = token.json()["access_token"]
        user = requests.get("https://discord.com/api/v10/users/@me", headers={
            "Authorization": f"Bearer {access_token}"
        }, timeout=15)
        user.raise_for_status()
        session.clear()
        session.permanent = True
        session["discord_user"] = user.json()
        session["login_at"] = iso(now())
        return redirect("/dashboard")
    except (requests.RequestException, KeyError, ValueError):
        return render_template_string(LOGIN_HTML, error="Não foi possível concluir o login com Discord."), 502


@app.get("/admin/login")
def admin_login():
    if admin():
        return redirect("/admin")
    return render_template_string(LOGIN_HTML, error=request.args.get("error"))

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
        session.clear()
        session.permanent = True
        session["admin"] = True
        session["login_at"] = iso(now())
        return redirect("/admin")

    return render_template_string(LOGIN_HTML, error="Usuário ou senha inválidos."), 401


@app.get("/logout")
def user_logout():
    session.clear()
    return redirect("/")

@app.get("/admin/logout")
def logout():
    session.clear()
    return redirect("/")



USER_DASHBOARD_HTML = """
<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Shadow API • Painel</title>
<style>
:root{--bg:#070b16;--panel:#0d1426;--line:rgba(148,163,184,.16);--text:#e5eefc;--muted:#93a4bd;--brand:#7c3aed;--cyan:#22d3ee;--ok:#22c55e;--warn:#f59e0b;--bad:#ef4444;--shadow:0 20px 60px rgba(0,0,0,.45);--radius:18px}
*{box-sizing:border-box}html,body{height:100%;scroll-behavior:smooth}body{margin:0;font-family:Inter,ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,Arial;background:radial-gradient(circle at 20% 0%,rgba(124,58,237,.22),transparent 34%),radial-gradient(circle at 80% 10%,rgba(34,211,238,.12),transparent 28%),var(--bg);color:var(--text)}a{color:inherit;text-decoration:none}button{font:inherit}
.shell{display:grid;grid-template-columns:292px 1fr;min-height:100vh}.sidebar{position:sticky;top:0;height:100vh;padding:22px 16px;background:linear-gradient(180deg,rgba(13,20,38,.96),rgba(9,14,27,.96));border-right:1px solid var(--line);backdrop-filter:blur(14px);z-index:30;overflow:hidden}
.brand{display:flex;align-items:center;gap:12px;padding:10px 12px 18px;border-bottom:1px solid var(--line)}.logo{width:42px;height:42px;border-radius:14px;background:linear-gradient(135deg,var(--brand),#4f46e5 55%,var(--cyan));box-shadow:0 12px 35px rgba(124,58,237,.35);display:grid;place-items:center;font-weight:900}.brand small{display:block;color:var(--muted);font-size:12px;margin-top:2px}
.nav{margin-top:18px;display:grid;gap:8px}.nav a{display:flex;align-items:center;gap:12px;padding:12px 13px;border:1px solid transparent;border-radius:14px;color:var(--muted);transition:.18s}.nav a:hover,.nav a.active{background:linear-gradient(135deg,rgba(124,58,237,.28),rgba(34,211,238,.10));border-color:rgba(124,58,237,.38);color:var(--text)}.icon{width:22px;text-align:center;flex:0 0 auto}
.side-foot{margin-top:18px;padding:14px;border:1px solid var(--line);border-radius:16px;background:rgba(255,255,255,.03)}.pill{display:inline-flex;align-items:center;gap:8px;padding:6px 10px;border-radius:999px;font-size:12px;font-weight:700}.dot{width:8px;height:8px;border-radius:50%;background:var(--ok);box-shadow:0 0 0 6px rgba(34,197,94,.12)}.pill.ok{color:#86efac;background:rgba(34,197,94,.12);border:1px solid rgba(34,197,94,.25)}
.main{min-width:0;padding:24px}.topbar{position:sticky;top:0;z-index:20;display:flex;align-items:center;justify-content:space-between;gap:16px;padding:14px 16px;border:1px solid var(--line);border-radius:20px;background:rgba(7,11,22,.72);backdrop-filter:blur(16px);box-shadow:0 10px 30px rgba(0,0,0,.20)}.title h1{margin:0;font-size:19px;letter-spacing:-.03em}.title p{margin:3px 0 0;color:var(--muted);font-size:13px}.actions{display:flex;gap:10px}.btn{display:inline-flex;align-items:center;justify-content:center;border:1px solid var(--line);border-radius:14px;padding:11px 14px;background:rgba(255,255,255,.04);color:var(--text);cursor:pointer}.btn.primary{background:linear-gradient(135deg,var(--brand),#4f46e5);border-color:rgba(124,58,237,.55);box-shadow:0 14px 35px rgba(124,58,237,.24);font-weight:800}.btn.danger{color:#fca5a5;border-color:rgba(239,68,68,.3)}
.grid{display:grid;gap:16px;margin-top:18px}.cards{grid-template-columns:repeat(4,minmax(0,1fr))}.card,.panel{border:1px solid var(--line);border-radius:var(--radius);background:linear-gradient(180deg,rgba(255,255,255,.045),rgba(255,255,255,.018));box-shadow:var(--shadow);padding:18px;min-width:0}.card h3{margin:0;color:var(--muted);font-size:13px}.metric{font-size:32px;font-weight:900;margin-top:8px;letter-spacing:-.05em}.muted{color:var(--muted);font-size:13px;line-height:1.55}.two{grid-template-columns:1.25fr .9fr}.head{display:flex;justify-content:space-between;align-items:flex-start;gap:16px}.head h2{margin:0;font-size:17px;letter-spacing:-.03em}.head p{margin:6px 0 0;color:var(--muted);line-height:1.55}
.list{display:grid;gap:11px;margin-top:15px}.row{display:flex;align-items:center;justify-content:space-between;gap:14px;border:1px solid var(--line);border-radius:16px;padding:14px;background:rgba(255,255,255,.03)}.row b{display:block}.row span{display:block;color:var(--muted);font-size:12px;margin-top:4px}.tag{font-size:11px;font-weight:900;padding:6px 10px;border-radius:999px;white-space:nowrap}.tag.ok{color:#86efac;background:rgba(34,197,94,.12)}.tag.warn{color:#fcd34d;background:rgba(245,158,11,.12)}.tag.lock{color:#fca5a5;background:rgba(239,68,68,.12)}.empty{padding:28px;text-align:center;color:var(--muted);border:1px dashed rgba(148,163,184,.26);border-radius:18px;background:rgba(255,255,255,.02)}
.form{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:16px}.field{display:grid;gap:7px}.field.full{grid-column:1/-1}label{font-size:13px;color:#cbd5e1;font-weight:800}input,select,textarea{width:100%;border:1px solid var(--line);border-radius:14px;background:rgba(2,6,23,.48);color:var(--text);padding:12px 13px;outline:none}input:focus,select:focus{border-color:rgba(34,211,238,.55);box-shadow:0 0 0 4px rgba(34,211,238,.1)}.hint{font-size:12px;color:var(--muted)}
.code{position:relative;margin-top:14px;border:1px solid rgba(34,211,238,.25);background:#020617;border-radius:18px;padding:16px;overflow:auto}.code pre{margin:0;color:#c4b5fd;font-size:12px;line-height:1.7}.code .copy{position:absolute;right:10px;top:10px}.result{margin-top:14px;padding:14px;border-radius:15px;border:1px solid rgba(34,211,238,.22);background:rgba(34,211,238,.05)}.result pre{margin:8px 0 0;white-space:pre-wrap;word-break:break-word;color:#bae6fd;font-size:12px}
.overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,.52);z-index:25;backdrop-filter:blur(3px)}
@media(max-width:1150px){.cards{grid-template-columns:repeat(2,minmax(0,1fr))}.two{grid-template-columns:1fr}}@media(max-width:860px){.shell{display:block}.sidebar{position:static;height:auto;border-right:0;border-bottom:1px solid var(--line)}.nav{grid-template-columns:repeat(2,1fr)}.main{padding:16px}.cards{grid-template-columns:1fr}.form{grid-template-columns:1fr}.field.full{grid-column:auto}.topbar{align-items:flex-start;flex-direction:column}.actions{width:100%}.actions .btn{flex:1}}
</style>
</head>
<body>
<div class="shell">
<aside class="sidebar">
  <div class="brand"><div class="logo">S</div><div><strong>Shadow API</strong><small>Área do cliente</small></div></div>
  <nav class="nav">
    <a class="active" href="/dashboard"><span class="icon">⌂</span>Visão Geral</a>
    <a href="#keys"><span class="icon">◈</span>Minhas API Keys</a>
    <a href="#rooms"><span class="icon">◉</span>Salas</a>
    <a href="#usage"><span class="icon">◌</span>Uso da API</a>
    <a href="/docs"><span class="icon">▤</span>Documentação</a>
    <a href="/health"><span class="icon">●</span>Status</a>
  </nav>
  <div class="side-foot"><span class="pill ok"><span class="dot"></span> API online</span><div class="muted" style="margin-top:9px;font-size:12px">Login protegido pelo Discord</div></div>
</aside>
<main class="main">
<header class="topbar"><div class="title"><h1>Dashboard / Visão Geral</h1><p>Gerencie suas chaves, crie salas e acompanhe sua operação.</p></div><div class="actions"><a class="btn" href="/docs">Documentação</a><a class="btn danger" href="/logout">↪ Sair</a></div></header>

<div class="grid cards">
  <div class="card"><h3>Conta Discord</h3><div class="metric">{{ user.get("global_name") or user.get("username") or "Usuário" }}</div><div class="muted">ID: {{ user.get("id","—") }}</div></div>
  <div class="card"><h3>API Keys</h3><div class="metric">{{ keys|length }}</div><div class="muted">Vinculadas à sua conta</div></div>
  <div class="card"><h3>Keys ativas</h3><div class="metric">{{ active_count }}</div><div class="muted">Disponíveis para uso</div></div>
  <div class="card"><h3>Salas utilizadas</h3><div class="metric">{{ rooms_used }}</div><div class="muted">Criações bem-sucedidas</div></div><div class="card"><h3>Saldo</h3><div class="metric">R$ {{ "%.2f"|format((wallet.balance_cents or 0)/100) }}</div><div class="muted"><a href="#deposit">Adicionar crédito →</a></div></div>
</div>

<section class="panel" style="margin-top:18px"><div class="head"><div><h2>Bem-vindo ao Shadow API</h2><p>Seu painel de cliente com o mesmo visual do painel principal, mas mostrando somente recursos liberados para sua conta.</p></div><span class="tag ok">CLIENTE</span></div>
<div class="grid" style="grid-template-columns:repeat(3,1fr);margin-top:15px">
<div class="row"><div><b>🔑 Credencial</b><span>Use X-API-Key no backend.</span></div></div>
<div class="row"><div><b>🎮 Salas</b><span>Criar salas diretamente pelo painel.</span></div></div>
<div class="row"><div><b>💳 Consumo</b><span>R$ 0,05 por sala bem-sucedida.</span></div></div>
</div></section>

<section id="deposit" class="panel" style="margin-top:18px">
<div class="head"><div><h2>💰 Adicionar crédito</h2><p>O saldo pertence à sua conta Discord e pode ser usado pelas suas API Keys.</p></div><span class="tag ok">SALDO R$ {{ "%.2f"|format((wallet.balance_cents or 0)/100) }}</span></div>
<form class="form" method="post" action="/dashboard/deposit">
<div class="field"><label>Valor do depósito</label><input name="amount" type="number" min="5" max="500" step="0.01" value="10.00" required><div class="hint">Mínimo R$ 5,00 · máximo R$ 500,00.</div></div>
<div class="field"><label>Pagamento</label><div class="row"><div><b>Pix</b><span>O crédito só será liberado após confirmação do provedor.</span></div><span class="tag warn">AUTOMÁTICO</span></div></div>
<div class="field full"><button class="btn primary" type="submit">＋ Gerar pagamento Pix</button></div>
</form>
{% if deposit_result %}<div class="result"><b>{% if deposit_result.ok %}Pagamento criado{% else %}Não foi possível criar o pagamento{% endif %}</b>{% if deposit_result.error %}<pre>{{deposit_result.error}}</pre>{% elif deposit_result.payment %}<pre>{{deposit_result.payment|tojson(indent=2)}}</pre>{% endif %}</div>{% endif %}
<div class="list"><div class="row"><div><b>Histórico de crédito</b><span>Depósitos, cobranças e estornos da sua carteira.</span></div><span class="tag ok">{{transactions|length}} registros</span></div>
{% for t in transactions[:8] %}<div class="row"><div><b>{{t.type|replace("_"," ")|title}}</b><span>{{t.created_at}}</span></div><strong>{% if t.amount_cents >= 0 %}+{% endif %}R$ {{ "%.2f"|format((t.amount_cents or 0)/100) }}</strong></div>{% endfor %}</div>
</section>

<section id="rooms" class="panel" style="margin-top:18px">
<div class="head"><div><h2>Salas</h2><p>Crie uma sala diretamente pelo painel usando uma das suas API Keys. O token privado da Nix permanece somente no servidor.</p></div><span class="tag ok">NIX ONLINE</span></div>
{% if not keys %}<div class="empty" style="margin-top:15px">Você ainda não possui uma API Key vinculada à sua conta.</div>{% else %}
<form class="form" method="post" action="/dashboard/rooms">
<div class="field"><label>API Key</label><select name="key_id" required>{% for k in keys %}<option value="{{k.id}}" {% if not valid_key(k) %}disabled{% endif %}>{{k.label}} · {{k.key_prefix}}•••• · R$ {{ "%.2f"|format((k.balance_cents or 0)/100) }}{% if not valid_key(k) %} · INATIVA{% endif %}</option>{% endfor %}</select></div>
<div class="field"><label>Tipo de configuração</label><select name="config_type"><option value="ap_padrao">AP Padrão</option><option value="gelo_inf">Gelo Infinito</option><option value="tatico">Tático</option><option value="ap_fullcapa">AP Full Capa</option><option value="capa_3">Capa 3</option><option value="ap_uxd">AP UXD</option><option value="ap_7r">AP 7R</option><option value="br_padrao">BR Padrão</option></select></div>
<div class="field"><label>Senha da sala</label><input name="password" value="00" maxlength="20"></div>
<div class="field"><label>Delay inicial (minutos)</label><input name="start_delay_minutes" type="number" min="1" max="20" value="1" required></div>
<div class="field"><label>Mapa</label><select name="map_name"><option>Bermuda</option><option>Purgatory</option><option>Kalahari</option><option>Nextera</option><option>Nova Terra</option><option>Solara</option></select></div>
<div class="field"><label>Nome da sala</label><input name="room_name" value="Shadow Salas" maxlength="80"></div>
<div class="field full"><button class="btn primary" type="submit">🎮 Criar sala · R$ 0,05</button><div class="hint">O valor só é consumido quando a criação for aceita com sucesso. Em caso de falha, o crédito é devolvido.</div></div>
</form>
{% endif %}
{% if room_result %}<div class="result"><b>{% if room_result.ok %}Sala criada com sucesso{% else %}Falha ao criar sala{% endif %}</b><div class="muted">HTTP {{room_result.status}}</div>{% if room_result.response %}<pre>{{ room_result.response | tojson(indent=2) }}</pre>{% elif room_result.error %}<pre>{{ room_result.error }}</pre>{% endif %}</div>{% endif %}
</section>

<div class="grid two">
<section class="panel" id="keys"><div class="head"><div><h2>Minhas API Keys</h2><p>Somente chaves vinculadas ao seu Discord aparecem aqui.</p></div><span class="tag warn">{{ keys|length }} cadastradas</span></div>
{% if keys %}<div class="list">{% for k in keys %}<div class="row"><div><b>{{k.label}}</b><span>{{k.key_prefix}}•••• · Saldo R$ {{ "%.2f"|format((k.balance_cents or 0)/100) }}</span><span>Salas: {{k.rooms_used or 0}}{% if k.max_rooms %} / {{k.max_rooms}}{% else %} / ilimitado{% endif %} · Expira: {{k.expires_at or "sem expiração"}}</span></div>{% if valid_key(k) %}<span class="tag ok">ATIVA</span>{% else %}<span class="tag lock">INATIVA</span>{% endif %}</div>{% endfor %}</div>{% else %}<div class="empty">Nenhuma API Key vinculada à sua conta ainda.</div>{% endif %}
</section>
<section class="panel" id="usage"><div class="head"><div><h2>Uso da API</h2><p>Resumo do consumo das suas credenciais.</p></div><span class="tag ok">R$ 0,05 / sala</span></div>
<div class="list"><div class="row"><div><b>Salas criadas</b><span>Total entre suas chaves</span></div><b>{{rooms_used}}</b></div><div class="row"><div><b>Saldo disponível</b><span>Total das suas chaves</span></div><b>R$ {{ "%.2f"|format((keys|sum(attribute="balance_cents") or 0)/100) }}</b></div><div class="row"><div><b>Endpoint</b><span>POST /v1/rooms</span></div><span class="tag ok">ONLINE</span></div></div>
<div class="code"><pre>X-API-Key: sk_sua_chave
Content-Type: application/json

{
  "config_type": "ap_padrao",
  "password": "00",
  "start_delay_minutes": 1,
  "map_name": "Bermuda",
  "room_name": "Shadow Salas"
}</pre></div><a class="btn primary" href="/docs" style="margin-top:14px">Abrir documentação completa →</a></section>
</div>

<section class="panel" style="margin-top:18px"><div class="head"><div><h2>Como começar</h2><p>Use a API Key no backend ou crie salas diretamente por esta tela.</p></div></div>
<div class="list"><div class="row"><div><b>1. Selecione uma API Key</b><span>Ela precisa estar ativa e ter saldo suficiente.</span></div><span class="tag ok">API</span></div><div class="row"><div><b>2. Configure a sala</b><span>Escolha configuração, mapa, senha e delay.</span></div><span class="tag ok">SALAS</span></div><div class="row"><div><b>3. Crie a sala</b><span>A API encaminha a solicitação ao provedor sem expor o token privado.</span></div><span class="tag warn">R$ 0,05</span></div></div></section>
</main></div>
</body></html>
"""

@app.post("/dashboard/rooms")
def user_create_room():
    user = discord_user()
    if not user:
        return redirect("/login")

    discord_id = str(user.get("id", ""))
    try:
        key_id = int(request.form.get("key_id", "0"))
    except ValueError:
        return redirect("/dashboard#rooms")

    result = db.table("api_keys").select("*").eq("id", key_id).eq("owner_user_id", discord_id).limit(1).execute()
    key = (result.data or [None])[0]

    if not key or not valid_key(key):
        session["room_result"] = {"ok": False, "status": 403, "error": "API Key inválida, expirada ou inativa."}
        return redirect("/dashboard#rooms")

    if not reserve_room_credit(key["id"]):
        session["room_result"] = {"ok": False, "status": 402, "error": "Saldo insuficiente. Adicione crédito antes de criar a sala."}
        return redirect("/dashboard#rooms")

    try:
        delay = max(1, min(20, int(request.form.get("start_delay_minutes", "1"))))
    except ValueError:
        delay = 1

    payload = {
        "password": request.form.get("password", "00").strip() or "00",
        "start_delay_minutes": delay,
        "config_type": request.form.get("config_type", "ap_padrao").strip() or "ap_padrao",
        "room_name": request.form.get("room_name", "Shadow Salas").strip() or "Shadow Salas",
        "map_name": request.form.get("map_name", "Bermuda").strip() or "Bermuda",
    }

    try:
        upstream = None
        for attempt in range(1, 5):
            try:
                upstream = requests.post(
                    NIX_ROOMS_URL,
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {NIX_API_TOKEN}",
                        "Content-Type": "application/json",
                    },
                    timeout=15,
                )
                if upstream.status_code not in (502, 503, 504, 524) or attempt == 4:
                    break
                import time
                time.sleep(min(5 * attempt, 20))
            except requests.RequestException:
                if attempt == 4:
                    raise
                import time
                time.sleep(min(5 * attempt, 20))

        if upstream is None:
            raise requests.RequestException("no response")

        try:
            response = upstream.json()
        except ValueError:
            response = {"raw": upstream.text[:4000]}

        if 200 <= upstream.status_code < 300:
            db.table("api_keys").update({
                "rooms_used": int(key.get("rooms_used") or 0) + 1,
                "last_used_at": iso(now()),
            }).eq("id", key["id"]).execute()
        else:
            refund_room_credit(key["id"])

        session["room_result"] = {
            "ok": 200 <= upstream.status_code < 300,
            "status": upstream.status_code,
            "response": response,
        }
    except requests.RequestException:
        refund_room_credit(key["id"])
        session["room_result"] = {"ok": False, "status": 502, "error": "Não foi possível conectar à API da Nix."}

    return redirect("/dashboard#rooms")
@app.post("/dashboard/deposit")
def user_deposit():
    user = discord_user()
    if not user:
        return redirect("/login")
    try:
        amount_cents = int(round(float(request.form.get("amount", "0").replace(",", ".")) * 100))
    except ValueError:
        amount_cents = 0
    if amount_cents < 500 or amount_cents > 50000:
        session["deposit_result"] = {"ok": False, "error": "Escolha um valor entre R$ 5,00 e R$ 500,00."}
        return redirect("/dashboard#deposit")
    try:
        data = create_deposit_payment(str(user["id"]), amount_cents)
        session["deposit_result"] = {"ok": True, "payment": data}
    except (requests.RequestException, RuntimeError) as exc:
        session["deposit_result"] = {"ok": False, "error": str(exc)}
    return redirect("/dashboard#deposit")


@app.get("/dashboard")
def user_dashboard():
    user = discord_user()
    if not user:
        return redirect("/login")
    discord_id = str(user.get("id", ""))
    keys = db.table("api_keys").select("*").eq("owner_user_id", discord_id).order("created_at", desc=True).execute().data or []
    active_count = sum(1 for item in keys if valid_key(item))
    rooms_used = sum(int(item.get("rooms_used") or 0) for item in keys)
    wallet = wallet_for_user(discord_id)
    transactions = db.table("wallet_transactions").select("*").eq("user_id", discord_id).order("created_at", desc=True).limit(20).execute().data or []
    return render_template_string(
        USER_DASHBOARD_HTML,
        user=user,
        keys=keys,
        active_count=active_count,
        rooms_used=rooms_used,
        wallet=wallet,
        transactions=transactions,
        deposit_result=session.pop("deposit_result", None),
    )

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
        total_balance_cents=sum(int(item.get("balance_cents") or 0) for item in keys),
        new_key=session.pop("new_key", None),
        room_result=session.pop("room_result", None),
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
