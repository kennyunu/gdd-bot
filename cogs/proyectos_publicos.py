"""
cogs/proyectos_publicos.py — Canal de visibilidad pública de GDD
=================================================================
Mantiene un canal de solo lectura con el estado actualizado de todos
los flujos y tareas activos del semestre. Se actualiza automáticamente
cada vez que algo cambia, y también tiene un refresh cada hora.

Problema que resuelve:
  Cuando el trabajo se mueve a canales privados o WhatsApp, los miembros
  nuevos no saben en qué está trabajando el grupo → nadie se engancha.
  Este canal es la vitrina pública siempre actualizada.
"""

import discord
from discord import app_commands
from discord.ext import commands, tasks
from datetime import datetime
from database import get_db

# Clave para guardar la config del canal en BD
CONFIG_KEY = "canal_proyectos"

ESTADO_EMOJI = {
    "pendiente":   "⏳",
    "en_progreso": "🔄",
    "completada":  "✅",
    "bloqueada":   "🔒",
}

AREA_EMOJI = {
    "Logística":           "📦",
    "Comunicaciones":      "📱",
    "Pedagogía":           "📚",
    "Relaciones Externas": "🤝",
    "Tesorería":           "💰",
}


class ProyectosPublicos(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # guild_id → {"canal_id": str, "mensaje_id": str | None}
        self._config: dict[str, dict] = {}
        self.refresh_loop.start()

    def cog_unload(self):
        self.refresh_loop.cancel()

    # ─────────────────────────────────────────────
    #  Construir el embed del tablero
    # ─────────────────────────────────────────────
    async def _build_tablero(self, guild_id: str) -> list[discord.Embed]:
        """
        Genera los embeds del tablero de proyectos activos.
        Devuelve una lista porque Discord permite hasta 10 embeds por mensaje.
        """
        async with await get_db() as db:
            # Flujos activos (con al menos una tarea no completada)
            async with db.execute(
                """SELECT f.id, f.nombre, f.area,
                          COUNT(t.id) as total,
                          SUM(CASE WHEN t.estado='completada' THEN 1 ELSE 0 END) as hechas,
                          SUM(CASE WHEN t.estado='bloqueada' THEN 1 ELSE 0 END) as bloqueadas,
                          SUM(CASE WHEN t.estado='en_progreso' THEN 1 ELSE 0 END) as en_progreso
                   FROM flujos f
                   JOIN tareas t ON t.flujo_id = f.id
                   WHERE f.guild_id = ?
                   GROUP BY f.id
                   HAVING hechas < total
                   ORDER BY f.area, f.id""",
                (guild_id,)
            ) as cur:
                flujos = await cur.fetchall()

            # Tareas sueltas activas (sin flujo, no completadas)
            async with db.execute(
                """SELECT area, id, nombre, responsable, deadline, estado
                   FROM tareas
                   WHERE guild_id=? AND flujo_id IS NULL AND estado != 'completada'
                   ORDER BY area, deadline ASC NULLS LAST""",
                (guild_id,)
            ) as cur:
                tareas_sueltas = await cur.fetchall()

            # Próximo evento
            async with db.execute(
                """SELECT nombre, fecha, lugar FROM eventos
                   WHERE guild_id=? AND fecha > datetime('now')
                   ORDER BY fecha ASC LIMIT 1""",
                (guild_id,)
            ) as cur:
                proximo_evento = await cur.fetchone()

        ahora = datetime.now().strftime("%d/%m/%Y %H:%M")

        # ── Embed principal ──────────────────────────────────────────────────
        embed_main = discord.Embed(
            title="🎮 GDD — Tablero de actividad",
            description=(
                "Este canal se actualiza automáticamente con lo que está pasando en el grupo.\n"
                "¿Quieres participar? Entra al servidor y presenta tu perfil 👇"
            ),
            color=discord.Color.blurple()
        )
        embed_main.set_footer(text=f"Última actualización: {ahora} (Bogotá)")

        if proximo_evento:
            nombre_ev, fecha_ev, lugar_ev = proximo_evento
            try:
                fecha_dt = datetime.fromisoformat(fecha_ev)
                fecha_str = fecha_dt.strftime("%d/%m/%Y a las %H:%M")
            except:
                fecha_str = fecha_ev
            embed_main.add_field(
                name="📅 Próximo evento",
                value=f"**{nombre_ev}**\n{fecha_str}" + (f"\n📍 {lugar_ev}" if lugar_ev else ""),
                inline=False
            )

        embeds = [embed_main]

        # ── Embeds por flujo ─────────────────────────────────────────────────
        for flujo in flujos:
            fid, fnombre, farea, total, hechas, bloqueadas, en_progreso = flujo

            # Barra de progreso visual
            porcentaje = int((hechas / total) * 100) if total > 0 else 0
            bloques_llenos = porcentaje // 10
            barra = "█" * bloques_llenos + "░" * (10 - bloques_llenos)

            # Tareas del flujo con su estado
            async with await get_db() as db:
                async with db.execute(
                    """SELECT flujo_paso, nombre, estado, responsable, deadline
                       FROM tareas WHERE flujo_id=? ORDER BY flujo_paso""",
                    (fid,)
                ) as cur:
                    pasos = await cur.fetchall()

            pasos_str = ""
            for paso_num, paso_nombre, paso_estado, resp_id, deadline in pasos:
                emoji = ESTADO_EMOJI.get(paso_estado, "❓")
                dl = f" · 📅 {deadline}" if deadline and paso_estado != "completada" else ""
                pasos_str += f"{emoji} **Paso {paso_num}:** {paso_nombre}{dl}\n"

            area_emoji = AREA_EMOJI.get(farea, "📌")
            embed_flujo = discord.Embed(
                title=f"{area_emoji} {fnombre}",
                description=f"`{barra}` {porcentaje}%\n{pasos_str}",
                color=discord.Color.green() if porcentaje == 100 else discord.Color.blurple()
            )
            embed_flujo.set_footer(text=f"Área: {farea} · {hechas}/{total} pasos completados")
            embeds.append(embed_flujo)

        # ── Tareas sueltas por área ──────────────────────────────────────────
        if tareas_sueltas:
            # Agrupar por área
            por_area: dict[str, list] = {}
            for area, tid, nombre, resp_id, deadline, estado in tareas_sueltas:
                por_area.setdefault(area, []).append((tid, nombre, deadline, estado))

            for area, items in por_area.items():
                lineas = ""
                for tid, nombre, deadline, estado in items[:8]:  # max 8 por área
                    emoji = ESTADO_EMOJI.get(estado, "❓")
                    dl = f" · {deadline}" if deadline else ""
                    lineas += f"{emoji} #{tid} {nombre}{dl}\n"

                embed_area = discord.Embed(
                    title=f"{AREA_EMOJI.get(area, '📌')} {area} — tareas activas",
                    description=lineas or "Sin tareas activas",
                    color=discord.Color.og_blurple()
                )
                embeds.append(embed_area)

        if len(embeds) == 1 and not proximo_evento:
            embed_main.description = (
                "✨ **Todo tranquilo por acá** — no hay flujos ni tareas activas en este momento.\n"
                "Cuando el equipo arranque un nuevo proyecto o flujo, aparecerá aquí automáticamente."
            )

        # Discord permite máx 10 embeds por mensaje
        return embeds[:10]

    # ─────────────────────────────────────────────
    #  Publicar o actualizar el mensaje del tablero
    # ─────────────────────────────────────────────
    async def _actualizar_tablero(self, guild: discord.Guild):
        """Edita el mensaje fijo del tablero o lo crea si no existe."""
        guild_id = str(guild.id)
        config = self._config.get(guild_id)
        if not config or not config.get("canal_id"):
            return

        canal = guild.get_channel(int(config["canal_id"]))
        if not canal:
            return

        embeds = await self._build_tablero(guild_id)

        mensaje_id = config.get("mensaje_id")
        if mensaje_id:
            try:
                msg = await canal.fetch_message(int(mensaje_id))
                await msg.edit(embeds=embeds)
                return
            except (discord.NotFound, discord.HTTPException):
                pass  # El mensaje fue borrado — crear uno nuevo

        # Crear mensaje nuevo
        msg = await canal.send(embeds=embeds)
        self._config[guild_id]["mensaje_id"] = str(msg.id)

        # Persistir mensaje_id en BD
        async with await get_db() as db:
            await db.execute(
                "INSERT OR REPLACE INTO notion_pages (entidad_tipo, entidad_id, page_id) VALUES ('tablero_msg',?,?)",
                (guild.id, str(msg.id))
            )
            await db.commit()

    async def _cargar_config(self):
        """Carga canal y mensaje guardados desde BD al arrancar el bot."""
        async with await get_db() as db:
            async with db.execute(
                "SELECT entidad_id, page_id FROM notion_pages WHERE entidad_tipo IN ('tablero_canal','tablero_msg')"
            ) as cur:
                rows = await cur.fetchall()

        # Reconstruir config desde BD (reutilizamos notion_pages como KV store genérico)
        temp: dict[str, dict] = {}
        async with await get_db() as db:
            async with db.execute(
                "SELECT entidad_tipo, entidad_id, page_id FROM notion_pages WHERE entidad_tipo LIKE 'tablero_%'"
            ) as cur:
                rows = await cur.fetchall()

        for tipo, eid, valor in rows:
            guild_id = str(eid)
            if guild_id not in temp:
                temp[guild_id] = {}
            if tipo == "tablero_canal":
                temp[guild_id]["canal_id"] = valor
            elif tipo == "tablero_msg":
                temp[guild_id]["mensaje_id"] = valor

        self._config = temp

    # ─────────────────────────────────────────────
    #  Loop de refresh automático (cada hora)
    # ─────────────────────────────────────────────
    @tasks.loop(hours=1)
    async def refresh_loop(self):
        for guild in self.bot.guilds:
            try:
                await self._actualizar_tablero(guild)
            except Exception as e:
                import logging
                logging.getLogger("gdd.proyectos").error(f"Error refresh tablero {guild.id}: {e}")

    @refresh_loop.before_loop
    async def before_refresh(self):
        await self.bot.wait_until_ready()
        await self._cargar_config()

    # ─────────────────────────────────────────────
    #  Método público para actualizar desde otros cogs
    # ─────────────────────────────────────────────
    async def trigger_update(self, guild: discord.Guild):
        """Llamado por tareas/flujos/eventos cuando algo cambia."""
        try:
            await self._actualizar_tablero(guild)
        except Exception as e:
            import logging
            logging.getLogger("gdd.proyectos").error(f"Error trigger tablero: {e}")

    # ─────────────────────────────────────────────
    #  /tablero_configurar — admin elige el canal
    # ─────────────────────────────────────────────
    @app_commands.command(
        name="tablero_configurar",
        description="Configura el canal público donde el bot muestra los proyectos activos de GDD"
    )
    @app_commands.describe(canal="Canal de solo lectura para el tablero de proyectos")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def tablero_configurar(
        self,
        interaction: discord.Interaction,
        canal: discord.TextChannel,
    ):
        guild_id = str(interaction.guild_id)

        # Guardar en memoria y BD
        if guild_id not in self._config:
            self._config[guild_id] = {}
        self._config[guild_id]["canal_id"] = str(canal.id)
        self._config[guild_id]["mensaje_id"] = None  # Forzar mensaje nuevo

        async with await get_db() as db:
            await db.execute(
                "INSERT OR REPLACE INTO notion_pages (entidad_tipo, entidad_id, page_id) VALUES ('tablero_canal',?,?)",
                (interaction.guild_id, str(canal.id))
            )
            # Limpiar mensaje anterior si existía
            await db.execute(
                "DELETE FROM notion_pages WHERE entidad_tipo='tablero_msg' AND entidad_id=?",
                (interaction.guild_id,)
            )
            await db.commit()

        await interaction.response.send_message(
            f"✅ Tablero configurado en {canal.mention}\n"
            f"Publicando el primer tablero ahora...",
            ephemeral=True
        )

        # Publicar inmediatamente
        await self._actualizar_tablero(interaction.guild)

    # ─────────────────────────────────────────────
    #  /tablero_actualizar — refresh manual
    # ─────────────────────────────────────────────
    @app_commands.command(
        name="tablero_actualizar",
        description="Fuerza una actualización inmediata del tablero de proyectos"
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def tablero_actualizar(self, interaction: discord.Interaction):
        config = self._config.get(str(interaction.guild_id))
        if not config or not config.get("canal_id"):
            await interaction.response.send_message(
                "❌ El tablero no está configurado. Usa `/tablero_configurar` primero.",
                ephemeral=True
            )
            return

        await interaction.response.send_message("🔄 Actualizando tablero...", ephemeral=True)
        await self._actualizar_tablero(interaction.guild)
        await interaction.edit_original_response(content="✅ Tablero actualizado.")


async def setup(bot):
    await bot.add_cog(ProyectosPublicos(bot))
