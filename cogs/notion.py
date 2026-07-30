"""
cogs/notion.py — Comandos de configuración y diagnóstico de Notion
"""

import discord
from discord import app_commands
from discord.ext import commands
import notion_sync


class Notion(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(
        name="notion_estado",
        description="Verifica que la integración con Notion esté funcionando correctamente"
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def notion_estado(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        estado = await notion_sync.check_notion_config()

        embed = discord.Embed(
            title="🔗 Estado de integración — Notion",
            color=discord.Color.green() if estado["conexion"] else discord.Color.red()
        )

        embed.add_field(
            name="🔑 Token",
            value="✅ Configurado" if estado["token"] else "❌ Falta `NOTION_TOKEN`",
            inline=True
        )
        embed.add_field(
            name="📋 BD Tareas",
            value="✅ Configurada" if estado["db_tareas"] else "❌ Falta `NOTION_DB_TAREAS`",
            inline=True
        )
        embed.add_field(
            name="📅 BD Eventos",
            value="✅ Configurada" if estado["db_eventos"] else "❌ Falta `NOTION_DB_EVENTOS`",
            inline=True
        )
        embed.add_field(
            name="🌐 Conexión API",
            value="✅ Activa" if estado["conexion"] else f"❌ Error: {estado.get('error', 'desconocido')}",
            inline=False
        )

        if not estado["conexion"]:
            embed.add_field(
                name="📖 Cómo configurar",
                value=(
                    "1. Ve a https://www.notion.so/my-integrations\n"
                    "2. Crea una integración nueva → copia el **Secret**\n"
                    "3. En Railway agrega la variable `NOTION_TOKEN=secret_...`\n"
                    "4. Crea las BDs en Notion y compártelas con tu integración\n"
                    "5. Copia los IDs de cada BD → `NOTION_DB_TAREAS` y `NOTION_DB_EVENTOS`\n"
                    "6. Reinicia el bot"
                ),
                inline=False
            )

        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(
        name="notion_setup",
        description="Muestra las instrucciones para conectar Notion con el bot"
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def notion_setup(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="📖 Setup de Notion para GDD Bot",
            description="Sigue estos pasos para conectar Notion. Solo hay que hacerlo una vez.",
            color=discord.Color.blurple()
        )

        embed.add_field(
            name="Paso 1 — Crear la integración",
            value=(
                "1. Ve a **https://www.notion.so/my-integrations**\n"
                "2. Clic en **+ New integration**\n"
                "3. Nómbrala `GDD Bot`, selecciona tu workspace\n"
                "4. Copia el **Internal Integration Secret** (empieza con `secret_...`)\n"
                "5. En Railway → Variables → agrega:\n"
                "   `NOTION_TOKEN = secret_...`"
            ),
            inline=False
        )

        embed.add_field(
            name="Paso 2 — Crear la BD de Tareas en Notion",
            value=(
                "Crea una base de datos con estas propiedades exactas:\n"
                "• **Nombre** — Title\n"
                "• **Área** — Select\n"
                "• **Responsable** — Text\n"
                "• **Estado** — Select\n"
                "• **Deadline** — Date\n"
                "• **Flujo** — Text\n"
                "• **ID Discord** — Number\n\n"
                "Luego: **Share → Invite → tu integración GDD Bot**\n"
                "Copia el ID de la URL y agrégalo en Railway:\n"
                "`NOTION_DB_TAREAS = abc123...`"
            ),
            inline=False
        )

        embed.add_field(
            name="Paso 3 — Crear la BD de Eventos en Notion",
            value=(
                "Crea una base de datos con:\n"
                "• **Nombre** — Title\n"
                "• **Fecha** — Date\n"
                "• **Lugar** — Text\n"
                "• **Confirmados** — Number\n"
                "• **No pueden** — Number\n"
                "• **Tal vez** — Number\n"
                "• **ID Discord** — Number\n\n"
                "Compártela con la integración e ingresa:\n"
                "`NOTION_DB_EVENTOS = def456...`"
            ),
            inline=False
        )

        embed.add_field(
            name="Paso 4 — Verificar",
            value="Reinicia el bot y usa `/notion_estado` para confirmar que todo esté conectado.",
            inline=False
        )

        embed.set_footer(text="El bot solo escribe en Notion — nunca borra ni modifica datos manuales.")
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Notion(bot))
