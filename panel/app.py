import os,secrets,string
from datetime import datetime,timezone,timedelta
import httpx
from flask import Flask,request,redirect,session,render_template
from werkzeug.security import check_password_hash
from bot.config import PANEL_USERNAME,PANEL_PASSWORD_HASH,DISCORD_TOKEN
from bot.db import db

app=Flask(__name__)
app.secret_key=os.environ.get("SECRET_KEY",secrets.token_hex(32))

def ok():
    return session.get("admin") is True

def redirect_login():
    return redirect("/painel-login")

def discord_send(channel_id,message):
    url=f"https://discord.com/api/v10/channels/{channel_id}/messages"
    headers={"Authorization":f"Bot {DISCORD_TOKEN}","Content-Type":"application/json"}
    with httpx.Client(timeout=15) as client:
        response=client.post(url,headers=headers,json={"content":message})
    if response.status_code not in (200,201):
        raise RuntimeError(f"Discord HTTP {response.status_code}")

@app.route("/")
def home():
    return redirect("/painel")

@app.route("/painel-login",methods=["GET","POST"])
def login():
    error=None
    if request.method=="POST":
        if request.form.get("username")==PANEL_USERNAME and check_password_hash(PANEL_PASSWORD_HASH,request.form.get("password","")):
            session["admin"]=True
            return redirect("/painel")
        error="Usuário ou senha inválidos."
    return render_template("login.html",error=error)

@app.route("/logout")
def logout():
    session.clear()
    return redirect_login()

@app.route("/painel")
def painel():
    if not ok():
        return redirect_login()
    plans=db.table("plans").select("*").eq("active",True).order("id").execute().data
    keys=db.table("keys").select("*, plans(name,room_limit)").order("created_at",desc=True).execute().data
    guilds=db.table("guilds").select("*").order("name").execute().data
    active_guild_keys=db.table("guild_keys").select("guild_id,key_id,active,guilds(name)").eq("active",True).execute().data
    guild_config=db.table("guild_config").select("guild_id,notify_channel_id").execute().data
    config_by_guild={str(x["guild_id"]):x for x in guild_config}
    linked_by_key={}
    for link in active_guild_keys:
        linked_by_key[str(link["key_id"])]=link
    return render_template(
        "dashboard.html",
        plans=plans,
        keys=keys,
        guilds=guilds,
        active_guild_keys=active_guild_keys,
        linked_by_key=linked_by_key,
        config_by_guild=config_by_guild,
        batch_result=session.pop("batch_result", None),
    )

@app.route("/painel/keys",methods=["POST"])
def new_key():
    if not ok():
        return redirect_login()
    try:
        plan_id=int(request.form["plan_id"])
    except (KeyError,ValueError):
        return redirect("/painel")
    rows=db.table("plans").select("*").eq("id",plan_id).eq("active",True).limit(1).execute().data
    if not rows:
        return redirect("/painel")
    p=rows[0]
    value="SHADOW-"+"-".join("".join(secrets.choice(string.ascii_uppercase+string.digits) for _ in range(4)) for _ in range(3))
    expires=(datetime.now(timezone.utc)+timedelta(days=p["duration_days"])).isoformat()
    db.table("keys").insert({"key":value,"plan_id":plan_id,"expires_at":expires,"active":True}).execute()
    return redirect("/painel")

@app.route("/painel/keys/batch",methods=["POST"])
def batch_keys():
    if not ok():
        return redirect_login()

    try:
        plan_id=int(request.form.get("plan_id",""))
        quantity=int(request.form.get("quantity",""))
    except (TypeError,ValueError):
        return redirect("/painel")

    separator=request.form.get("separator","|")
    if not separator:
        separator="|"

    quantity=max(1,min(quantity,1000))
    rows=db.table("plans").select("*").eq("id",plan_id).eq("active",True).limit(1).execute().data
    if not rows:
        return redirect("/painel")

    keys=[]
    for _ in range(quantity):
        value="SHADOW-"+"-".join(
            "".join(secrets.choice(string.ascii_uppercase+string.digits) for _ in range(4))
            for _ in range(3)
        )
        keys.append(value)

    db.table("keys").insert([
        {"key":value,"plan_id":plan_id,"expires_at":None,"active":True}
        for value in keys
    ]).execute()

    session["batch_result"]={
        "plan_name":rows[0]["name"],
        "duration_days":rows[0]["duration_days"],
        "quantity":len(keys),
        "separator":separator,
        "keys":keys,
    }
    return redirect("/painel")


@app.route("/painel/keys/<int:key_id>/toggle",methods=["POST"])
def toggle(key_id):
    if not ok():
        return redirect_login()
    r=db.table("keys").select("active").eq("id",key_id).limit(1).execute()
    if r.data:
        db.table("keys").update({"active":not r.data[0]["active"]}).eq("id",key_id).execute()
    return redirect("/painel")

@app.route("/painel/keys/<int:key_id>/renew",methods=["POST"])
def renew(key_id):
    if not ok():
        return redirect_login()
    try:
        days=int(request.form.get("days","30"))
    except ValueError:
        return redirect("/painel")
    if days not in (7,30,90):
        return redirect("/painel")
    r=db.table("keys").select("expires_at").eq("id",key_id).limit(1).execute()
    if r.data:
        current=r.data[0].get("expires_at")
        base=datetime.now(timezone.utc)
        if current:
            try:
                base=max(base,datetime.fromisoformat(current.replace("Z","+00:00")))
            except ValueError:
                pass
        db.table("keys").update({"expires_at":(base+timedelta(days=days)).isoformat(),"active":True}).eq("id",key_id).execute()
    return redirect("/painel")

@app.route("/painel/keys/<int:key_id>/delete",methods=["POST"])
def delete_key(key_id):
    if not ok():
        return redirect_login()
    db.table("guild_keys").delete().eq("key_id",key_id).execute()
    db.table("room_usage").delete().eq("key_id",key_id).execute()
    db.table("keys").delete().eq("id",key_id).execute()
    return redirect("/painel")

@app.route("/painel/keys/<int:key_id>/broadcast",methods=["POST"])
def key_broadcast(key_id):
    if not ok():
        return redirect_login()
    message=request.form.get("message","").strip()
    if not message:
        return redirect("/painel")
    link=db.table("guild_keys").select("guild_id").eq("key_id",key_id).eq("active",True).limit(1).execute().data
    if not link:
        return redirect("/painel")
    guild_id=str(link[0]["guild_id"])
    cfg=db.table("guild_config").select("notify_channel_id").eq("guild_id",guild_id).limit(1).execute().data
    channel_id=cfg[0].get("notify_channel_id") if cfg else None
    if channel_id:
        try:
            discord_send(channel_id,f"📢 **Aviso Shadow Salas**\n{message}")
            db.table("broadcasts").insert({"guild_id":guild_id,"message":message,"sent":True}).execute()
        except Exception:
            db.table("broadcasts").insert({"guild_id":guild_id,"message":message,"sent":False}).execute()
    else:
        db.table("broadcasts").insert({"guild_id":guild_id,"message":message,"sent":False}).execute()
    return redirect("/painel")

@app.route("/painel/broadcast",methods=["POST"])
def broadcast():
    if not ok():
        return redirect_login()
    message=request.form.get("message","").strip()
    if message:
        db.table("broadcasts").insert({"message":message,"sent":False}).execute()
    return redirect("/painel")

@app.route("/health")
def health():
    return {"status":"ok"}
