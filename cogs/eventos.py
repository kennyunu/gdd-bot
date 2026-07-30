import discord
from discord import app_commands
from discord.ext import commands, tasks
from datetime import datetime, timedelta
from database import get_db
import notion_sync


class RSVPView(discord.ui.View):
    """Botones interactivos de asistencia al evento."""

    def __init__(self, evento_id: int):
        super().__init__(timeout=None)  # Persistente
        self.evento_id = evento_id

    @discord.ui.button(label="✅ Voy", style=discord.ButtonStyle.success, custom_id="rsvp_voy")
    async def voy(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._registrar_rsvp(interaction, "voy")

    @discord.ui.button(label="❌ No puedo", style=discord.ButtonStyle.danger, custom_id="rsvp_no_voy")
    async def no_voy(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._registrar_rsvp(interaction, "no_voy")

    @discord.ui.button(label="🤔 Tal vez", style=discord.ButtonStyle.secondary, custom_id="rsvp_tal_vez")
    async def tal_vez(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._registrar_rsvp(interaction, "tal_vez")

    @discord.ui.button(label="👥 Ver asistencia", style=discord.ButtonStyle.primary, custom_id="rsvp_ver")
    async def ver_asistencia(self, interaction: discord.Interaction, button: discord.ui.Button):
        async with await get_db() as db:
            async with db.execute(
                "SELECT respuesta, COUNT(*) as cnt FROM rsvp WHERE evento_id=? GROUP BY respuesta",
                (self.evento_id,)
            ) as cur:
                conteo = await cur.fetchall()

        resumen = {"voy": 0, "no_voy": 0, "tal_vez": 0}
        for r, cnt in conteo:
            resumen[r] = cnt

        embed = discord.Embed(title="👥 Asistencia al evento", color=discord.Color.blurple())
        embed.add_field(name="✅ Van", value=str(resumen["voy"]), inline=True)
        embed.add_field(name="🤔 Tal vez", value=str(resumen["tal_vez"]), inline=True)
        embed.add_field(name="❌ No pueden", value=str(resumen["no_voy"]), inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def _registrar_rsvp(self, interaction: discord.Interaction, respuesta: str):
        async with await get_db() as db:
            await db.execute(
                """INSERT INTO rsvp (evento_id, user_id, respuesta)
                   VALUES (?,?,?)
                   ON CONFLICT(evento_id, user_id) DO UPDATE SET respuesta=excluded.respuesta, timestamp=datetime('now')""",
                (self.evento_id, str(interaction.user.id), respuesta)
            )
            await db.commit()

        emoji = {"voy": "✅", "no_voy": "❌", "tal_vez": "🤔"}[respuesta]
        texto = {"voy": "¡Anotado! Te vemos ahí 🎮", "no_voy": "Anotado. ¡La próxima!", "tal_vez": "Anotado, ¡esperamos que puedas!"}[respuesta]
        await interaction.response.send_message(f"{emoji} {texto}", ephemeral=True)


class Eventos(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.recordatorios_loop.start()

    def cog_unload(self):
        self.recordatorios_loop.cancel()

    # ─────────────────────────────────────────────
    #  /evento_crear
    # ─────────────────────────────────────────────
    @app_commands.command(name="evento_crear", description="Crea un evento con sistema de asistencia (RSVP)")
    @app_commands.describe(
        nombre="Nombre del evento",
        fecha="Fecha y hora (YYYY-MM-DD HH:MM)",
        lugar="Lugar o link (ej: Aula 301 o https://meet.google.com/...)",
        descripcion="Descripción del evento",
    )
    async def evento_crear(
        self,
        interaction: discord.Interaction,
        nombre: str,
        fecha: str,
        lugar: str = None,
        descripcion: str = None,
    ):
        try:
            fecha_dt = datetime.strptime(fecha, "%Y-%m-%d %H:%M")
        except ValueError:
            await interaction.response.send_message(
                "❌ Formato de fecha inválido. Usa: `YYYY-MM-DD HH:MM` (ej: 2026-08-15 18:00)", ephemeral=True
            )
            return

        async with await get_db() as db:
            cur = await db.execute(
                """INSERT INTO eventos (nombre, descripcion, fecha, lugar, canal_id, creado_por, guild_id)
                   VALUES (?,?,?,?,?,?,?)""",
                (nombre, descripcion, fecha_dt.isoformat(), lugar,
                 str(interaction.channel_id), str(interaction.user.id), str(interaction.guild_id))
            )
            evento_id = cur.lastrowid
            await db.commit()

        # ── Sync a Notion ──
        page_id = await notion_sync.crear_evento_notion(
            evento_id=evento_id,
            nombre=nombre,
            fecha=fecha_dt.isoformat(),
            lugar=lugar,
            descripcion=descripcion,
        )
        if page_id:
            async with await get_db() as db2:
                await db2.execute(
                    "INSERT OR REPLACE INTO notion_pages (entidad_tipo, entidad_id, page_id) VALUES ('evento',?,?)",
                    (evento_id, page_id)
                )
                await db2.commit()

        embed = discord.Embed(
            title=f"📅 {nombre}",
            description=descripcion or "*Sin descripción*",
            color=discord.Color.blue()
        )
        embed.add_field(name="📆 Fecha", value=fecha_dt.strftime("%d/%m/%Y a las %H:%M"), inline=True)
        embed.add_field(name="📍 Lugar", value=lugar or "Por confirmar", inline=True)
        embed.add_field(name="🆔 ID", value=f"#{evento_id}", inline=True)
        embed.set_footer(text=f"Organizado por {interaction.user.display_name} • ¡Marca tu asistencia!")

        view = RSVPView(evento_id)
        await interaction.response.send_message(embed=embed, view=view)

    # ─────────────────────────────────────────────
    #  Loop de recordatorios automáticos
    # ─────────────────────────────────────────────
    @tasks.loop(hours=1)
    async def recordatorios_loop(self):
        """Revisa cada hora si hay eventos próximos y envía recordatorios."""
        ahora = datetime.now()

        async with await get_db() as db:
            async with db.execute(
                "SELECT id, nombre, fecha, lugar, canal_id, guild_id FROM eventos WHERE fecha > ?",
                (ahora.isoformat(),)
            ) as cur:
                eventos = await cur.fetchall()

        for evento in eventos:
            eid, nombre, fecha_str, lugar, canal_id, guild_id = evento
            fecha_evento = datetime.fromisoformat(fecha_str)
            delta = fecha_evento - ahora
            horas = delta.total_seconds() / 3600

            # Recordatorio 24h antes y 1h antes
            if not (23.5 <= horas <= 24.5 or 0.75 <= horas <= 1.25):
                continue

            guild = self.bot.get_guild(int(guild_id))
            if not guild or not canal_id:
                continue
            canal = guild.get_channel(int(canal_id))
            if not canal:
                continue

            # Obtener quiénes dijeron que van
            async with await get_db() as db:
                async with db.execute(
                    "SELECT user_id FROM rsvp WHERE evento_id=? AND respuesta='voy'", (eid,)
                ) as cur:
                    van = await cur.fetchall()

            menciones = " ".join([f"<@{u[0]}>" for u in van]) if van else "Nadie confirmó aún 👀"
            tiempo_str = "¡en 1 hora!" if horas <= 1.25 else "mañana"

            embed = discord.Embed(
                title=f"⏰ Recordatorio — {nombre}",
                description=f"El evento es **{tiempo_str}**",
                color=discord.Color.orange()
            )
            embed.add_field(name="📆 Fecha", value=fecha_evento.strftime("%d/%m/%Y %H:%M"), inline=True)
            embed.add_field(name="📍 Lugar", value=lugar or "Por confirmar", inline=True)
            embed.add_field(name="✅ Confirmados", value=menciones, inline=False)

            await canal.send(embed=embed)

    @recordatorios_loop.before_loop
    async def before_loop(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(Eventos(bot))
