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


def reserve_room_credit(key_id):
    result = db.rpc("reserve_room_credit", {"p_key_id": int(key_id)}).execute()
    return bool(result.data)


def refund_room_credit(key_id):
    db.rpc("refund_room_credit", {"p_key_id": int(key_id)}).execute()


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
:root{--bg:#08070c;--panel:#0f0d15;--panel2:#14101d;--line:#26212f;--text:#f7f5fb;--muted:#9891a5;--purple:#8b5cf6;--purple2:#6d28d9;--green:#55d98b;--yellow:#e8c76b;--red:#ef6b78}
html{scroll-behavior:smooth}body{margin:0;background:var(--bg);color:var(--text);font-family:Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}
.app{min-height:100vh;display:flex}.sidebar{position:fixed;left:0;top:0;bottom:0;width:248px;background:#0b0910;border-right:1px solid var(--line);padding:20px 14px;display:flex;flex-direction:column;z-index:5}
.brand{display:flex;align-items:center;gap:11px;padding:4px 8px 24px}.logo{width:40px;height:40px;border-radius:12px;background:linear-gradient(135deg,#a78bfa,#6d28d9);display:grid;place-items:center;font-weight:900;font-size:19px;box-shadow:0 10px 30px #7c3aed33}.brand strong{font-size:16px}.brand span{display:block;color:var(--muted);font-size:11px;margin-top:2px}
.section-label{font-size:10px;text-transform:uppercase;letter-spacing:.12em;color:#655e70;font-weight:800;padding:14px 10px 7px}.side-nav{display:grid;gap:3px}.side-nav a{display:flex;align-items:center;gap:10px;padding:10px 11px;border-radius:9px;color:#aaa3b5;text-decoration:none;font-size:13px}.side-nav a:hover,.side-nav a.active{background:#181220;color:#fff}.side-nav a.active{box-shadow:inset 2px 0 var(--purple)}.ico{width:19px;text-align:center;opacity:.85}
.side-bottom{margin-top:auto;border-top:1px solid var(--line);padding-top:14px}.account{display:flex;align-items:center;gap:9px;padding:9px}.avatar{width:30px;height:30px;border-radius:9px;background:#21162f;display:grid;place-items:center;color:#c4b5fd;font-weight:800}.account small{display:block;color:var(--muted);font-size:10px}.logout{margin-left:auto;color:#777080;text-decoration:none;font-size:12px}
.main{margin-left:248px;width:calc(100% - 248px);min-width:0}.top{height:68px;border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between;padding:0 34px;background:#0b0910cc;backdrop-filter:blur(12px);position:sticky;top:0;z-index:4}.crumb{font-size:13px;color:var(--muted)}.crumb b{color:#eee}.top-links{display:flex;gap:8px}.top-links a{color:#aaa3b5;text-decoration:none;font-size:12px;border:1px solid var(--line);padding:8px 11px;border-radius:8px}.top-links a:hover{color:#fff;border-color:#443552}
.content{max-width:1180px;margin:auto;padding:32px}.eyebrow{color:#a78bfa;font-size:11px;text-transform:uppercase;letter-spacing:.12em;font-weight:800;margin-bottom:8px}.title-row{display:flex;justify-content:space-between;gap:20px;align-items:flex-end;margin-bottom:24px}.title-row h1{font-size:29px;margin:0 0 7px;letter-spacing:-.03em}.title-row p{margin:0;color:var(--muted);font-size:13px}.status-pill{display:flex;align-items:center;gap:7px;border:1px solid #254332;background:#0c1711;color:#83dda5;border-radius:999px;padding:8px 11px;font-size:11px;font-weight:800}.dot{width:6px;height:6px;border-radius:50%;background:var(--green);box-shadow:0 0 10px var(--green)}
.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:20px}.stat{background:var(--panel);border:1px solid var(--line);border-radius:13px;padding:18px}.stat-top{display:flex;justify-content:space-between;color:var(--muted);font-size:12px}.stat-icon{color:#bba1ee}.num{font-size:27px;font-weight:850;margin-top:13px;letter-spacing:-.03em}.stat-foot{font-size:10px;color:#625b6c;margin-top:5px}
.grid{display:grid;grid-template-columns:minmax(0,1.15fr) minmax(320px,.85fr);gap:16px}.card{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:20px}.card h2{font-size:15px;margin:0 0 5px}.desc{font-size:12px;color:var(--muted);line-height:1.55;margin:0 0 16px}
.form-grid{display:grid;grid-template-columns:1fr 1fr;gap:9px}input,select,button{width:100%;min-height:42px;padding:10px 12px;border-radius:9px;background:#0a080e;color:#fff;border:1px solid #2c2635;font:inherit;font-size:12px}input:focus,select:focus{outline:none;border-color:#7952ad;box-shadow:0 0 0 3px #7c3aed18}button{background:linear-gradient(135deg,var(--purple),var(--purple2));border:0;font-weight:800;cursor:pointer}button:hover{filter:brightness(1.08)}.full{grid-column:1/-1}.hint{font-size:10px;color:#696273;margin-top:9px}
.endpoint{background:#0a080e;border:1px solid var(--line);border-radius:10px;padding:13px}.method{color:#9f7aea;font-weight:900;font-size:10px;margin-right:7px}.endpoint strong{font-family:ui-monospace,monospace;font-size:12px}.endpoint p{font-size:11px;color:var(--muted);margin:8px 0 0}.code{margin-top:10px;background:#08070b;border:1px solid var(--line);border-radius:9px;padding:11px;font:11px/1.6 ui-monospace,SFMono-Regular,Consolas,monospace;color:#cfc7da;white-space:pre-wrap}.link{display:inline-block;color:#c4b5fd;text-decoration:none;font-size:11px;font-weight:700;margin-top:12px}.link:hover{text-decoration:underline}
.full-card{margin-top:16px}.list-head{display:flex;justify-content:space-between;align-items:flex-start;gap:15px}.count{color:#70697a;font-size:10px;white-space:nowrap}.item{border-top:1px solid var(--line);padding:15px 0}.item:first-child{margin-top:4px}.item-title{display:flex;justify-content:space-between;gap:12px;align-items:center}.item-title strong{font-size:13px}.meta{display:flex;flex-wrap:wrap;gap:6px 14px;color:#777080;font-size:10px;margin-top:7px}.status{font-size:9px;font-weight:900;padding:4px 7px;border-radius:999px}.on{background:#102218;color:#63d992;border:1px solid #1d4930}.off{background:#211c10;color:var(--yellow);border:1px solid #4a3e20}.key-preview{font:10px ui-monospace,monospace;color:#81768e;margin-top:9px}.actions{display:flex;gap:7px;margin-top:10px}.actions form{flex:1}.actions button{background:#17121d;box-shadow:none;min-height:34px;padding:7px;font-size:10px}.actions .danger{color:#f49aa3;background:#211016}
.empty{padding:28px 15px;text-align:center;color:#6f6878;font-size:11px;border:1px dashed #302a38;border-radius:10px}.key-alert{margin-top:16px;padding:17px;border:1px solid #275339;border-radius:13px;background:#0b1710}.success{color:#72e0a0;font-size:13px}.secret{font:11px ui-monospace,monospace;word-break:break-all;color:#c4b5fd;background:#08070b;border:1px solid #26352b;padding:11px;border-radius:8px;margin:10px 0}.copy{max-width:150px}
.module{margin-top:16px}.module-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:10px}.module-box{border:1px solid var(--line);background:#0c0a10;border-radius:10px;padding:13px}.module-box b{font-size:11px}.module-box span{display:block;color:#66606d;font-size:10px;margin-top:4px}.locked{border-color:#332744}.lock-head{display:flex;justify-content:space-between;align-items:flex-start}.lock-icon{font-size:22px}.lock-note{color:#71697c;font-size:10px;margin-top:12px}
.footer{text-align:center;color:#4f4857;font-size:10px;padding:25px}
@media(max-width:900px){.sidebar{width:205px}.main{margin-left:205px;width:calc(100% - 205px)}.grid{grid-template-columns:1fr}.content{padding:24px}.top{padding:0 24px}}
@media(max-width:680px){.sidebar{position:relative;width:100%;height:auto;bottom:auto;border-right:0;border-bottom:1px solid var(--line);padding:12px}.app{display:block}.main{margin:0;width:100%}.side-nav{grid-template-columns:repeat(3,1fr)}.side-bottom{display:none}.section-label{display:none}.brand{padding:4px 6px 10px}.top{position:relative;height:56px;padding:0 16px}.top-links a:first-child{display:none}.content{padding:20px 14px}.stats{grid-template-columns:1fr}.form-grid{grid-template-columns:1fr}.full{grid-column:auto}.title-row{align-items:flex-start;flex-direction:column}.module-grid{grid-template-columns:1fr}}
</style>
</head>
<body>
<div class="app">
<aside class="sidebar">
  <div class="brand"><div class="logo">S</div><div><strong>Shadow API</strong><span>Central de gerenciamento</span></div></div>
  <div class="section-label">Principal</div>
  <nav class="side-nav">
    <a class="active" href="/admin"><span class="ico">⌂</span>Visão Geral</a>
    <a href="#api"><span class="ico">◈</span>API</a>
    <a href="#bot"><span class="ico">◆</span>Bot</a>
    <a href="#hosting"><span class="ico">▣</span>Hospedagem de Bots <span style="margin-left:auto">🔒</span></a><a href="#mediador"><span class="ico">♢</span>Auto Mediador <span style="margin-left:auto">🔒</span></a>
  </nav>
  <div class="section-label">Recursos</div>
  <nav class="side-nav">
    <a href="/docs"><span class="ico">▤</span>Documentação</a>
    <a href="/health"><span class="ico">●</span>Status</a>
  </nav>
  <div class="side-bottom">
    <div class="account"><div class="avatar">S</div><div><b style="font-size:11px">Shadow</b><small>Administrador</small></div><a class="logout" href="/admin/logout">Sair</a></div>
  </div>
</aside>

<main class="main">
<header class="top"><div class="crumb">Painel / <b>Visão Geral</b></div><div class="top-links"><a href="/docs">Documentação ↗</a><a href="/health">● API online</a></div></header>
<div class="content">

<div class="title-row">
  <div><div class="eyebrow">Shadow API</div><h1>Visão geral</h1><p>Gerencie suas chaves, créditos e integrações em um só lugar.</p></div>
  <div style="display:flex;gap:9px;align-items:center;flex-wrap:wrap;justify-content:flex-end"><a href="#api" style="color:#fff;text-decoration:none;background:linear-gradient(135deg,var(--purple),var(--purple2));padding:9px 13px;border-radius:9px;font-size:11px;font-weight:800">+ Nova API Key</a><div class="status-pill"><span class="dot"></span> Serviço operacional</div></div>
</div>

<section class="stats">
  <div class="stat"><div class="stat-top"><span>Total de chaves</span><span class="stat-icon">🔑</span></div><div class="num">{{keys|length}}</div><div class="stat-foot">Chaves cadastradas</div></div>
  <div class="stat"><div class="stat-top"><span>Chaves ativas</span><span class="stat-icon">✓</span></div><div class="num">{{active_count}}</div><div class="stat-foot">Prontas para requisições</div></div>
  <div class="stat"><div class="stat-top"><span>Salas utilizadas</span><span class="stat-icon">◈</span></div><div class="num">{{rooms_used}}</div><div class="stat-foot">Cada sala bem-sucedida custa R$ 0,05</div></div>
  <div class="stat"><div class="stat-top"><span>Saldo total</span><span class="stat-icon">R$</span></div><div class="num">R$ {{"%.2f"|format(total_balance_cents / 100)}}</div><div class="stat-foot">Créditos disponíveis nas keys</div></div>
</section>

<section class="grid">
<div class="card" id="api">
  <h2>Criar nova API Key</h2><p class="desc">Crie uma credencial para um cliente ou integração. A chave completa será exibida apenas uma vez.</p>
  <form method="post" action="/admin/keys">
    <div class="form-grid">
      <div class="full"><input name="label" placeholder="Nome do cliente ou integração" required></div>
      <div><select name="days"><option value="1">1 dia</option><option value="7">7 dias</option><option value="30" selected>30 dias</option><option value="90">90 dias</option><option value="365">365 dias</option></select></div>
      <div><input name="owner_user_id" placeholder="Discord User ID (opcional)"></div>
      <div><input name="max_rooms" type="number" min="0" placeholder="Limite de salas"></div>
      <div><input name="rate_limit" type="number" min="1" value="30" placeholder="Requests por minuto"></div>
      <div class="full"><button>+ Criar API Key</button></div>
    </div>
  </form>
  <div class="hint">Deixe o limite de salas vazio ou 0 para permitir uso ilimitado.</div>
</div>

<div class="card">
  <h2>Integração rápida</h2><p class="desc">Sua aplicação usa a Shadow API. O token privado da Nix nunca é enviado ao cliente.</p>
  <div class="endpoint"><span class="method">POST</span><strong>/v1/rooms</strong><p>Autenticação por <b>X-API-Key</b></p><div class="code">X-API-Key: sk_sua_chave
Content-Type: application/json</div></div>
  <a class="link" href="/docs">Ver documentação completa →</a>
</div>
</section>

{% if new_key %}
<section class="key-alert">
  <div class="success">✓ API Key criada com sucesso</div>
  <p class="desc" style="margin-top:6px">Guarde esta chave agora. Por segurança, ela não será exibida novamente.</p>
  <div class="secret">{{new_key}}</div>
  <button class="copy" onclick="navigator.clipboard.writeText({{new_key|tojson}})">Copiar chave</button>
</section>
{% endif %}

<section class="card full-card" id="bot">
  <div class="list-head"><div><h2>Bot</h2><p class="desc">Estrutura preparada para integrar os recursos do Bot da Nix ao Shadow Panel.</p></div><span class="count">EM PREPARAÇÃO</span></div>
  <div class="module-grid">
    <div class="module-box"><b>Visão Geral</b><span>Indicadores e atividade do bot</span></div>
    <div class="module-box"><b>Seu Bot</b><span>Gerenciamento e integração</span></div>
    <div class="module-box"><b>Configurações</b><span>Preferências do servidor</span></div>
    <div class="module-box"><b>Membros</b><span>Dados e gerenciamento</span></div>
  </div>
</section>

<section class="card full-card locked" id="hosting"><div class="lock-head"><div><h2>Hospedagem de Bots <span class="status off">INDISPONÍVEL</span></h2><p class="desc">Este módulo está reservado para uma futura etapa do Shadow Panel.</p></div><div class="lock-icon">🔒</div></div><div class="module-grid"><div class="module-box"><b>Criar hospedagem</b><span>Indisponível</span></div><div class="module-box"><b>Seus bots</b><span>Indisponível</span></div><div class="module-box"><b>Planos</b><span>Indisponível</span></div><div class="module-box"><b>Recursos</b><span>Indisponível</span></div></div></section>

<section class="card full-card locked" id="mediador">
  <div class="lock-head"><div><h2>Auto Mediador <span class="status off">INDISPONÍVEL</span></h2><p class="desc">Este módulo permanece bloqueado enquanto a integração dos recursos da Nix está sendo construída.</p></div><div class="lock-icon">🔒</div></div>
  <div class="module-grid">
    <div class="module-box"><b>Visão Geral</b><span>Em desenvolvimento</span></div>
    <div class="module-box"><b>Como Funciona</b><span>Em desenvolvimento</span></div>
    <div class="module-box"><b>Estatísticas</b><span>Em desenvolvimento</span></div>
    <div class="module-box"><b>Meus Códigos</b><span>Em desenvolvimento</span></div>
  </div>
</section>

<section class="card full-card">
  <div class="list-head"><div><h2>Entregas recebidas</h2><p class="desc">Vendas e webhooks recebidos pela API.</p></div><span class="count">{{deliveries|length}} recentes</span></div>
  {% for d in deliveries %}
  <div class="item"><div class="item-title"><strong>{{d.external_username or d.external_user_id or "Cliente não informado"}}</strong><span class="status on">RECEBIDA</span></div><div class="meta"><span>Venda: {{d.external_sale_id or "—"}}</span><span>Produto: {{d.product_name or "—"}}</span><span>Key ID: {{d.api_key_id or "não vinculada"}}</span><span>{{d.delivered_at or "—"}}</span></div></div>
  {% else %}<div class="empty">Nenhuma entrega recebida ainda.</div>{% endfor %}
</section>

<section class="card full-card">
  <div class="list-head"><div><h2>API Keys</h2><p class="desc">Credenciais criadas neste painel, com seus limites e status.</p></div><span class="count">{{keys|length}} cadastradas</span></div>
  {% for k in keys %}
  <div class="item">
    <div class="item-title"><strong>{{k.label}}</strong>{% if k.active %}<span class="status on">ATIVA</span>{% else %}<span class="status off">PAUSADA</span>{% endif %}</div>
    <div class="meta"><span>ID {{k.id}}</span><span>Dono: {{k.owner_user_id or "—"}}</span><span>Expira: {{k.expires_at or "sem expiração"}}</span><span>Uso: {{k.rooms_used}}{% if k.max_rooms is not none %} / {{k.max_rooms}}{% endif %} salas</span><span>Saldo: R$ {{"%.2f"|format((k.balance_cents or 0) / 100)}}</span><span>{{k.rate_limit_per_minute}} req/min</span></div>
    <div class="key-preview">{{k.key_prefix}} ••••••••••••••••</div>
    <div class="actions"><form method="post" action="/admin/keys/{{k.id}}/renew"><button>+30 dias</button></form><form method="post" action="/admin/keys/{{k.id}}/toggle"><button>{{"Pausar" if k.active else "Ativar"}}</button></form><form method="post" action="/admin/keys/{{k.id}}/delete" onsubmit="return confirm('Excluir esta API Key?')"><button class="danger">Excluir</button></form></div>
  </div>
  {% else %}<div class="empty">Nenhuma API Key criada ainda.<br>Crie a primeira usando o formulário acima.</div>{% endfor %}
</section>

<div class="footer">Shadow API • Painel administrativo</div>
</div></main></div>
</body>
</html>
"""

DOCS_HTML = """
<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Shadow API • Documentação</title><style>
*{box-sizing:border-box}body{margin:0;background:#08060d;color:#f5f3ff;font-family:Inter,system-ui,Arial}.wrap{max-width:1000px;margin:auto;padding:22px}
.card{background:#110d1b;border:1px solid #292033;border-radius:18px;padding:20px;margin:14px 0}.muted{color:#a49caf}a{color:#c4b5fd;text-decoration:none}code,pre{background:#0b0710;border:1px solid #292033;border-radius:10px}code{padding:2px 5px}pre{padding:14px;overflow:auto;white-space:pre-wrap}.method{color:#a78bfa;font-weight:900}
</style></head><body><div class="wrap"><a href="/admin">← Dashboard</a><h1>Shadow API — Documentação</h1>
<p class="muted">API própria da Shadow para criação de salas. Cada sala criada com sucesso consome R$ 0,05 do saldo da API Key.</p>
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

    # Cada criação de sala custa R$ 0,05.
    # O valor é reservado antes da chamada para impedir que duas requisições
    # concorrentes criem salas sem saldo. Se a Nix não criar a sala,
    # o valor é devolvido automaticamente.
    try:
        if not reserve_room_credit(key["id"]):
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
            refund_room_credit(key["id"])
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
        total_balance_cents=sum(int(item.get("balance_cents") or 0) for item in keys),
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
