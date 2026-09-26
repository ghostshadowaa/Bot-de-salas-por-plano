from datetime import datetime, timezone
from supabase import create_client
from .config import SUPABASE_URL,SUPABASE_KEY

db=create_client(SUPABASE_URL,SUPABASE_KEY)

def now():
    return datetime.now(timezone.utc).isoformat()

def get_key(guild_id):
    r=db.table("guild_keys").select("*, keys(*, plans(*))").eq("guild_id",str(guild_id)).eq("active",True).limit(1).execute()
    if not r.data: return None
    link=r.data[0]
    k=link.get("keys")
    if not k or not k.get("active"): return None
    if k.get("expires_at") and k["expires_at"] <= now(): return None
    return {**link,"key":k,"plan":k.get("plans")}

def activate_key(guild_id,value):
    r=db.table("keys").select("*, plans(*)").eq("key",value.strip()).eq("active",True).limit(1).execute()
    if not r.data: return None,"INVALID"
    k=r.data[0]
    if k.get("expires_at") and k["expires_at"] <= now(): return None,"EXPIRED"
    db.table("guild_keys").update({"active":False}).eq("guild_id",str(guild_id)).execute()
    db.table("guild_keys").insert({"guild_id":str(guild_id),"key_id":k["id"],"active":True}).execute()
    return k,None

def get_config(guild_id):
    r=db.table("guild_config").select("*").eq("guild_id",str(guild_id)).limit(1).execute()
    return r.data[0] if r.data else {}

def save_config(guild_id,role_id=None,channel_id=None):
    db.table("guild_config").upsert({"guild_id":str(guild_id),"room_role_id":str(role_id) if role_id else None,"notify_channel_id":str(channel_id) if channel_id else None},on_conflict="guild_id").execute()

def register_guild(guild):
    db.table("guilds").upsert({"guild_id":str(guild.id),"name":guild.name,"owner_id":str(guild.owner_id)},on_conflict="guild_id").execute()

def usage(guild_id,key_id):
    r=db.table("room_usage").select("count").eq("guild_id",str(guild_id)).eq("key_id",key_id).limit(1).execute()
    return r.data[0]["count"] if r.data else 0

def add_usage(guild_id,key_id):
    current=usage(guild_id,key_id)
    db.table("room_usage").upsert({"guild_id":str(guild_id),"key_id":key_id,"count":current+1},on_conflict="guild_id,key_id").execute()
    db.table("keys").update({"uses":current+1}).eq("id",key_id).execute()
