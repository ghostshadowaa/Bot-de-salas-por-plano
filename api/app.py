import hashlib
import os
import secrets
import time
from datetime import datetime, timezone, timedelta

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
<title>Shadow API • Painel</title><style>
*{box-sizing:border-box}body{margin:0;background:#09060f;color:#f5f3ff;font-family:Inter,Arial,sans-serif}.wrap{max-width:1180px;margin:auto;padding:22px}
header{display:flex;justify-content:space-between;align-items:center;margin-bottom:22px}.brand{display:flex;gap:12px;align-items:center}.logo{width:44px;height:44px;border-radius:13px;background:#7c3aed;display:grid;place-items:center;font-weight:900}.muted{color:#9b93aa}
.grid{display:grid;grid-template-columns:1fr 1.7fr;gap:18px}.card{background:#130e1c;border:1px solid #30233e;border-radius:18px;padding:20px;box-shadow:0 12px 35px #0004}
h1,h2,h3{margin:0 0 8px}.accent{color:#a78bfa}.durations{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin:14px 0}.duration{padding:13px;border:1px solid #3b2a4c;background:#0e0a14;border-radius:11px;color:#ddd;cursor:pointer}.duration.selected{border-color:#8b5cf6;background:#25143c;color:#fff}
input,button{font:inherit}.input{width:100%;padding:12px;border:1px solid #3b2a4c;background:#0d0912;color:#fff;border-radius:10px;margin-top:7px}.primary{width:100%;padding:12px;border:0;border-radius:10px;background:#7c3aed;color:white;font-weight:800;cursor:pointer;margin-top:12px}
.stats{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-bottom:18px}.stat{background:#100b16;border:1px solid #2b2036;border-radius:13px;padding:14px}.num{font-size:24px;font-weight:800}
.keys{display:grid;gap:12px}.key{background:#100b16;border:1px solid #2b2036;border-radius:14px;padding:15px}.keytop{display:flex;justify-content:space-between;gap:10px}.pill{font-size:12px;padding:5px 9px;border-radius:99px;background:#164e32}.paused{background:#604514}.expired{background:#641d2b}.keyline{font-family:monospace;color:#c4b5fd;margin:9px 0;word-break:break-all}.meta{font-size:12px;color:#9b93aa}.actions{display:flex;flex-wrap:wrap;gap:7px;margin-top:12px}.actions button{padding:8px 11px;border-radius:9px;border:1px solid #3b2a4c;background:#18101f;color:#eee;cursor:pointer}.actions .renew{background:#4c1d95}.actions .danger{border-color:#6b2737;color:#ffb4c0}.newkey{margin-bottom:18px;border-color:#6d28d9}.newkey .keyline{font-size:15px}
@media(max-width:800px){.grid{grid-template-columns:1fr}.stats{grid-template-columns:repeat(3,1fr)}}
</style></head><body><div class="wrap">
<header><div class="brand"><div class="logo">S</div><div><h1>Shadow API</h1><div class="muted">Painel de chaves</div></div></div><a href="/admin/logout" class="muted">Sair</a></header>
<div class="stats"><div class="stat"><div class="muted">Total</div><div class="num">{{keys|length}}</div></div><div class="stat"><div class="muted">Ativas</div><div class="num">{{active_count}}</div></div><div class="stat"><div class="muted">Pausadas</div><div class="num">{{paused_count}}</div></div></div>
{% if new_key %}<div class="card newkey"><h2>✓ Chave criada</h2><div class="muted">Copie agora. Por segurança, a chave completa não será armazenada.</div><div class="keyline">{{new_key}}</div><button class="primary" onclick="copyText({{new_key|tojson}})">Copiar chave</button></div>{% endif %}
<div class="grid"><div class="card"><h2>Criar chave</h2><div class="muted">Escolha a duração.</div><form method="post" action="/admin/keys">
<input class="input" name="label" placeholder="Nome do cliente" required>
<div class="durations"><button type="button" class="duration selected" onclick="pick(1,this)">1 dia</button><button type="button" class="duration" onclick="pick(7,this)">1 semana</button><button type="button" class="duration" onclick="pick(30,this)">1 mês</button></div>
<input type="hidden" name="days" id="days" value="1">
<input class="input" name="max_rooms" type="number" min="0" placeholder="Limite de salas (0 = ilimitado)">
<input class="input" name="rate_limit" type="number" min="1" value="30" placeholder="Chamadas por minuto">
<button class="primary">+ Criar chave</button></form></div>
<div class="card"><h2>Suas chaves</h2><div class="keys">
{% for k in keys %}<div class="key"><div class="keytop"><div><h3>{{k.label}}</h3><div class="meta">Criada em {{k.created_at[:10]}}</div></div>
{% if not k.active %}<span class="pill paused">Pausada</span>{% elif k.expires_at and k.expires_at < now_iso %}<span class="pill expired">Expirada</span>{% else %}<span class="pill">Ativa</span>{% endif %}</div>
<div class="keyline">{{k.key_prefix}}••••••••••••••••</div><div class="meta">Salas usadas: {{k.rooms_used}}{{'' if not k.max_rooms else ' / '+k.max_rooms|string}} · Expira: {{k.expires_at[:16].replace('T',' ') if k.expires_at else '—'}}</div>
<div class="actions">
<button onclick="copyText('{{k.key_prefix}}')">Copiar prefixo</button>
<form method="post" action="/admin/keys/{{k.id}}/renew"><button class="renew">Renovar</button></form>
<form method="post" action="/admin/keys/{{k.id}}/toggle"><button>{{'Ativar' if not k.active else 'Pausar'}}</button></form>
<form method="post" action="/admin/keys/{{k.id}}/delete" onsubmit="return confirm('Excluir esta chave?')"><button class="danger">Excluir</button></form>
</div></div>{% else %}<div class="muted">Nenhuma chave criada.</div>{% endfor %}
</div></div></div></div>
<script>
function pick(days,el){document.getElementById('days').value=days;document.querySelectorAll('.duration').forEach(x=>x.classList.remove('selected'));el.classList.add('selected')}
function copyText(t){navigator.clipboard.writeText(t).then(()=>alert('Copiado!'))}
</script></body></html>
"""
