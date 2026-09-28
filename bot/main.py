import discord
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from discord import app_commands
from discord.ext import commands
from .config import DISCORD_TOKEN
from .db import get_key, activate_key, get_config, save_config, register_guild, usage, add_usage
from .nix_api import NixAPI, NixAPIError
from .tasks import start_background

MODES = {
    "cs1": "ap_padrao",
    "cs2": "gelo_inf",
    "cs3": "tatico",
    "cs4": "ap_fullcapa",
    "cs5": "capa_3",
    "cs6": "ap_uxd",
    "cs7": "ap_7r",
}

ROOM_PASSWORD = "00"
ROOM_DELAY = 1
ROOM_MAP = "Bermuda"
ROOM_NAME = "Shadow Salas"

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix=".", intents=intents)
nix = NixAPI()
worker_started = False


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b'{"status":"online","service":"shadow-salas-bot"}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        return


def start_health_server():
    port = int(os.environ.get("PORT", "10000"))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    server.serve_forever()


# O bot e a API sao servicos separados no Render.
# O bot so precisa de um endpoint HTTP minimo para o health check do Web Service.
threading.Thread(target=start_health_server, daemon=True).start()


async def permission(interaction):
    key = get_key(interaction.guild.id)
    if not key:
        return None, "Nenhum plano ativo. Use /ativar."

    OWNER_ID = 1019382408719638530
    is_owner = interaction.user.id == interaction.guild.owner_id
    is_shadow = interaction.user.id == OWNER_ID

    cfg = get_config(interaction.guild.id)
    role = cfg.get("room_role_id")

    try:
        has_role = bool(
            role and any(r.id == int(role) for r in interaction.user.roles)
        )
    except (TypeError, ValueError):
        has_role = False

    if not (is_owner or has_role or is_shadow):
        return None, "❌ Você não tem permissão para criar salas."

    plan = key.get("plan") or {}
    limit = plan.get("room_limit")

    if limit is not None and not (is_owner or has_role or is_shadow):
        if usage(interaction.guild.id, key["key"]["id"]) >= int(limit):
            return None, f"Limite atingido: {limit} salas."

    return key, None


def room_embed(result):
    embed = discord.Embed(title="🎮 Shadow Salas", color=0x7C3AED)
    embed.add_field(
        name="Sala",
        value=str(result.get("room_id") or result.get("session_id") or "—"),
        inline=True,
    )
    embed.add_field(name="Senha", value=ROOM_PASSWORD, inline=True)
    embed.add_field(name="Mapa", value=ROOM_MAP, inline=True)
    embed.add_field(name="Nome", value=ROOM_NAME, inline=True)
    embed.add_field(name="Delay", value=f"{ROOM_DELAY} min", inline=True)

    if result.get("region"):
        embed.add_field(name="Região", value=str(result["region"]), inline=True)

    if result.get("invite_link"):
        embed.add_field(name="Link", value=result["invite_link"], inline=False)

    return embed


async def create(interaction, mode):
    await interaction.response.defer()

    key, err = await permission(interaction)
    if err:
        return await interaction.followup.send(err, ephemeral=True)

    data = {
        "password": ROOM_PASSWORD,
        "start_delay_minutes": ROOM_DELAY,
        "config_type": mode,
        "map_name": ROOM_MAP,
        "room_name": ROOM_NAME,
    }

    try:
        result = await nix.create_room(data)
        add_usage(interaction.guild.id, key["key"]["id"])
        await interaction.followup.send(embed=room_embed(result))
    except NixAPIError as exc:
        await interaction.followup.send(f"❌ Nix: {exc}", ephemeral=True)
    except Exception:
        await interaction.followup.send(
            "❌ Ocorreu um erro ao criar a sala. Tente novamente.",
            ephemeral=True,
        )


async def slash_room(interaction: discord.Interaction):
    await create(interaction, MODES[interaction.command.name])


async def prefix_room(ctx):
    if ctx.guild is None:
        return await ctx.send("Use este comando dentro de um servidor.")

    key, err = await permission(
        type("InteractionProxy", (), {
            "guild": ctx.guild,
            "user": ctx.author,
        })()
    )
    if err:
        return await ctx.send(err)

    mode = MODES[ctx.invoked_with.lower()]
    data = {
        "password": ROOM_PASSWORD,
        "start_delay_minutes": ROOM_DELAY,
        "config_type": mode,
        "map_name": ROOM_MAP,
        "room_name": ROOM_NAME,
    }

    try:
        result = await nix.create_room(data)
        add_usage(ctx.guild.id, key["key"]["id"])
        await ctx.send(embed=room_embed(result))
    except NixAPIError as exc:
        await ctx.send(f"❌ Nix: {exc}")
    except Exception:
        await ctx.send("❌ Ocorreu um erro ao criar a sala. Tente novamente.")


for name in MODES:
    command = app_commands.Command(
        name=name,
        description={
            "cs1": "AP padrão",
            "cs2": "Gelo infinito",
            "cs3": "Tático",
            "cs4": "AP full capa",
            "cs5": "Capa 3",
            "cs6": "AP UXD",
            "cs7": "AP 7R",
        }[name],
        callback=slash_room,
    )
    bot.tree.add_command(command)
    bot.command(name)(prefix_room)


@bot.tree.command(name="ativar", description="Ativa uma key neste servidor.")
@app_commands.describe(key="Chave recebida")
async def ativar(interaction: discord.Interaction, key: str):
    if not interaction.guild:
        return await interaction.response.send_message(
            "Use em um servidor.", ephemeral=True
        )

    if interaction.user.id != interaction.guild.owner_id:
        return await interaction.response.send_message(
            "Somente o dono pode ativar.", ephemeral=True
        )

    k, err = activate_key(interaction.guild.id, key)
    if err:
        return await interaction.response.send_message(
            "❌ Key inválida, inativa ou expirada.", ephemeral=True
        )

    plan = k.get("plans") or {}
    await interaction.response.send_message(
        f"✅ Plano **{plan.get('name', 'Plano')}** ativado.",
        ephemeral=True,
    )


@bot.tree.command(
    name="config",
    description="Configura cargo autorizado e canal de avisos.",
)
@app_commands.describe(cargo="Cargo que pode criar sem limite", canal="Canal para avisos")
async def config_cmd(
    interaction: discord.Interaction,
    cargo: discord.Role = None,
    canal: discord.TextChannel = None,
):
    if not interaction.guild:
        return await interaction.response.send_message(
            "Use em um servidor.", ephemeral=True
        )

    if interaction.user.id != interaction.guild.owner_id:
        return await interaction.response.send_message(
            "Somente o dono pode configurar.", ephemeral=True
        )

    save_config(
        interaction.guild.id,
        cargo.id if cargo else None,
        canal.id if canal else None,
    )
    await interaction.response.send_message(
        "⚙️ Configuração salva.", ephemeral=True
    )


@bot.tree.command(name="statusplano", description="Mostra o plano e o uso atual.")
async def status(interaction: discord.Interaction):
    if not interaction.guild:
        return await interaction.response.send_message(
            "Use em um servidor.", ephemeral=True
        )

    key = get_key(interaction.guild.id)
    if not key:
        return await interaction.response.send_message(
            "Nenhum plano ativo.", ephemeral=True
        )

    plan = key.get("plan") or {}
    used = usage(interaction.guild.id, key["key"]["id"])
    limit = plan.get("room_limit")

    await interaction.response.send_message(
        f"**{plan.get('name', 'Plano')}**\n"
        f"Salas: {used}/{limit if limit is not None else '∞'}\n"
        f"Expira: {key['key'].get('expires_at', '—')}",
        ephemeral=True,
    )


@bot.event
async def on_ready():
    global worker_started

    for guild in bot.guilds:
        register_guild(guild)

    await bot.tree.sync()

    if not worker_started:
        start_background(bot)
        worker_started = True

    print(f"Shadow Salas online como {bot.user} em {len(bot.guilds)} servidores.")


@bot.event
async def on_guild_join(guild):
    register_guild(guild)


bot.run(DISCORD_TOKEN)
