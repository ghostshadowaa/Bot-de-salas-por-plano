from datetime import datetime, timezone
from supabase import create_client
from .config import SUPABASE_URL, SUPABASE_KEY

db = create_client(SUPABASE_URL, SUPABASE_KEY)

def now():
    return datetime.now(timezone.utc).isoformat()

def get_key(guild_id):
    r = (db.table("guild_keys").select("*, keys(*, plans(*))")
         .eq("guild_id", str(guild_id)).eq("active", True).limit(1).execute())
    if not r.data:
        return None
    link = r.data[0]
    key = link.get("keys")
    if not key or not key.get("active"):
        return None
    if key.get("expires_at") and key["expires_at"] <= now():
        return None
    return {**link, "key": key, "plan": key.get("plans") or {}}

def activate_key(guild_id, value):
    r = (db.table("keys").select("*, plans(*)")
         .eq("key", value.strip()).eq("active", True).limit(1).execute())
    if not r.data:
        return None, "INVALID"
    key = r.data[0]
    if key.get("expires_at") and key["expires_at"] <= now():
        return None, "EXPIRED"

    db.table("guild_keys").update({"active": False}).eq("guild_id", str(guild_id)).execute()
    db.table("guild_keys").upsert(
        {"guild_id": str(guild_id), "key_id": key["id"], "active": True},
        on_conflict="guild_id"
    ).execute()
    return key, None

def get_config(guild_id):
    r = db.table("guild_config").select("*").eq("guild_id", str(guild_id)).limit(1).execute()
    return r.data[0] if r.data else {}

def save_config(guild_id, role_id=None, channel_id=None):
    db.table("guild_config").upsert(
        {
            "guild_id": str(guild_id),
            "room_role_id": str(role_id) if role_id else None,
            "notify_channel_id": str(channel_id) if channel_id else None,
        },
        on_conflict="guild_id"
    ).execute()

def register_guild(guild):
    db.table("guilds").upsert(
        {"guild_id": str(guild.id), "name": guild.name, "owner_id": str(guild.owner_id)},
        on_conflict="guild_id"
    ).execute()

def usage(guild_id, key_id):
    r = (db.table("room_usage").select("count")
         .eq("guild_id", str(guild_id)).eq("key_id", key_id).limit(1).execute())
    return int(r.data[0]["count"]) if r.data else 0

def add_usage(guild_id, key_id):
    count = usage(guild_id, key_id) + 1
    db.table("room_usage").upsert(
        {"guild_id": str(guild_id), "key_id": key_id, "count": count},
        on_conflict="guild_id,key_id"
    ).execute()
    db.table("keys").update({"uses": count}).eq("id", key_id).execute()

def pending_broadcasts():
    return (db.table("broadcasts").select("*").eq("sent", False)
            .order("id").limit(10).execute().data)

def mark_broadcast_sent(row_id):
    db.table("broadcasts").update({"sent": True}).eq("id", row_id).execute()
