import os

DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
NIX_API_TOKEN = os.environ["NIX_API_TOKEN"]
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]
PANEL_USERNAME = os.getenv("PANEL_USERNAME", "Shadow")
PANEL_PASSWORD_HASH = os.environ["PANEL_PASSWORD_HASH"]
NIX_BASE_URL = os.getenv("NIX_BASE_URL", "https://salas.nixbot.vip").rstrip("/")
