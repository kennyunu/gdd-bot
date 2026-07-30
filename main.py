import discord
from discord.ext import commands
import asyncio
import os
from database import init_db

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

COGS = [
    "cogs.tareas",
    "cogs.eventos",
    "cogs.flujos",
    "cogs.recordatorios",  # F2 — deadlines diarios
    "cogs.reuniones",      # F2 — agendamiento colectivo
]

@bot.event
async def on_ready():
    await init_db()
    print(f"✅ GDD Bot activo como {bot.user} (ID: {bot.user.id})")
    try:
        synced = await bot.tree.sync()
        print(f"⚡ {len(synced)} slash commands sincronizados")
    except Exception as e:
        print(f"❌ Error sincronizando comandos: {e}")

async def main():
    async with bot:
        for cog in COGS:
            try:
                await bot.load_extension(cog)
                print(f"📦 Cog cargado: {cog}")
            except Exception as e:
                print(f"❌ Error cargando {cog}: {e}")
        token = os.environ.get("DISCORD_TOKEN")
        if not token:
            raise ValueError("❌ DISCORD_TOKEN no encontrado en variables de entorno")
        await bot.start(token)

if __name__ == "__main__":
    asyncio.run(main())
