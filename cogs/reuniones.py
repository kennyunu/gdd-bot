import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timedelta
from database import get_db

RESPUESTA_EMOJI = {
    "puede":    "✅",
    "no_puede": "❌",
    "tal_vez":  "🤔",
}


def _formatear_slot(iso: str) -> str:
    """YYYY-MM-DDTHH:MM → 'Lun 14/07 · 18:00'"""
    dt = datetime.fromisoformat(iso)
    dias = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
    return f"{dias[dt.weekday()]} {dt.strftime('%d/%m')} · {dt.strftime('%H:%M')}"


def _build_embed(reunion: dict, slots_conteo: dict, respuestas_usuario: dict | None = None) -> discord.Embed:
    """Construye el embed principal de la reunión con el estado actual de votos."""
    embed = discord.Embed(
        title=f"🗓️ ¿Cuándo pueden? — {reunion['titulo']}",
        description=reunion.get("descripcion") or "",
        color=discord.Color.blurple()
    )
    if reunion.get("duracion_min"):
        embed.add_field(name="⏱️ Duración estimada", value=f"{reunion['duracion_min']} min", inline=True)
    embed.add_field(name="🆔 Reunión ID", value=f"#{reunion['id']}", inline=True)
    embed.add_field(name="📊 Estado", value=reunion.get("estado", "abierta").capitalize(), inline=True)

    for slot, conteo in slots_conteo.items():
        puede    = conteo.get("puede", 0)
        tal_vez  = conteo.get("tal_vez", 0)
        no_puede = conteo.get("no_puede", 0)
        total    = puede + tal_vez + no_puede

        barra = ""
        if total > 0:
            barra = "✅" * puede + "🤔" * tal_vez + "❌" * no_puede

        mi_resp = ""
        if respuestas_usuario and slot in respuestas_usuario:
            mi_resp = f" ← *tú: {RESPUESTA_EMOJI[respuestas_usuario[slot]]}*"

        embed.add_field(
            name=_formatear_slot(slot),
            value=f"{barra or '—'}\n✅ {puede}  🤔 {tal_vez}  ❌ {no_puede}{mi_resp}",
            inline=True
        )

    embed.set_footer(text="Usa los botones para marcar tu disponibilidad • Un admin confirma el horario final con /reunion_confirmar")
    return embed


class DisponibilidadView(discord.ui.View):
    """Vista con botones generados dinámicamente según los slots de la reunión."""

    def __init__(self, reunion_id: int, slots: list[str]):
        super().__init__(timeout=None)
        self.reunion_id = reunion_id
        self.slots = slots
        self._agregar_botones()

    def _agregar_botones(self):
        for i, slot in enumerate(self.slots):
            label = _formatear_slot(slot)
            # Tres botones por slot: puede / tal_vez / no_puede
            self.add_item(SlotButton(self.reunion_id, slot, "puede",    f"✅ {label}", discord.ButtonStyle.success,  f"rsvp_{self.reunion_id}_{i}_puede"))
            self.add_item(SlotButton(self.reunion_id, slot, "tal_vez",  f"🤔 {label}", discord.ButtonStyle.secondary, f"rsvp_{self.reunion_id}_{i}_talvez"))
            self.add_item(SlotButton(self.reunion_id, slot, "no_puede", f"❌ {label}", discord.ButtonStyle.danger,    f"rsvp_{self.reunion_id}_{i}_no"))


class SlotButton(discord.ui.Button):
    def __init__(self, reunion_id: int, slot: str, respuesta: str, label: str, style, custom_id: str):
        super().__init__(label=label, style=style, custom_id=custom_id, row=None)
        self.reunion_id = reunion_id
        self.slot = slot
        self.respuesta = respuesta

    async def callback(self, interaction: discord.Interaction):
        async with await get_db() as db:
            # Verificar que la reunión sigue abierta
            async with db.execute(
                "SELECT estado, titulo FROM reuniones WHERE id=?", (self.reunion_id,)
            ) as cur:
                reunion_row = await cur.fetchone()

            if not reunion_row or reunion_row[0] != "abierta":
                await interaction.response.send_message(
                    "ℹ️ Esta reunión ya fue cerrada o confirmada.", ephemeral=True
                )
                return

            # Registrar / actualizar respuesta
            await db.execute(
                """INSERT INTO disponibilidad (reunion_id, user_id, slot, respuesta)
                   VALUES (?,?,?,?)
                   ON CONFLICT(reunion_id, user_id, slot)
                   DO UPDATE SET respuesta=excluded.respuesta""",
                (self.reunion_id, str(interaction.user.id), self.slot, self.respuesta)
            )
            await db.commit()

            # Recalcular conteos para actualizar el embed
            async with db.execute(
                "SELECT slot, respuesta, COUNT(*) FROM disponibilidad WHERE reunion_id=? GROUP BY slot, respuesta",
                (self.reunion_id,)
            ) as cur:
                rows = await cur.fetchall()

            async with db.execute(
                "SELECT id, titulo, descripcion, duracion_min, estado FROM reuniones WHERE id=?",
                (self.reunion_id,)
            ) as cur:
                r = await cur.fetchone()

            async with db.execute(
                "SELECT slot, respuesta FROM disponibilidad WHERE reunion_id=? AND user_id=?",
                (self.reunion_id, str(interaction.user.id))
            ) as cur:
                mis_resp_rows = await cur.fetchall()

        slots_conteo: dict[str, dict] = {}
        for slot, resp, cnt in rows:
            if slot not in slots_conteo:
                slots_conteo[slot] = {}
            slots_conteo[slot][resp] = cnt

        mis_resp = {row[0]: row[1] for row in mis_resp_rows}

        reunion_dict = {
            "id": r[0], "titulo": r[1], "descripcion": r[2],
            "duracion_min": r[3], "estado": r[4]
        }

        # Mantener el orden original de slots
        slots_ordenados = {s: slots_conteo.get(s, {}) for s in self.view.slots}

        embed = _build_embed(reunion_dict, slots_ordenados, mis_resp)

        await interaction.response.edit_message(embed=embed, view=self.view)


class Reuniones(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ─────────────────────────────────────────────
    #  /reunion_crear
    # ─────────────────────────────────────────────
    @app_commands.command(name="reunion_crear", description="Propone horarios para una reunión y recoge disponibilidad")
    @app_commands.describe(
        titulo="Título de la reunión (ej: 'Reunión de admin semanal')",
        slots="Opciones de horario separadas por | (ej: '2026-08-01 18:00|2026-08-02 19:00|2026-08-03 18:00')",
        descripcion="De qué trata la reunión (opcional)",
        duracion="Duración en minutos (default: 60)",
    )
    async def reunion_crear(
        self,
        interaction: discord.Interaction,
        titulo: str,
        slots: str,
        descripcion: str = None,
        duracion: int = 60,
    ):
        # Parsear y validar slots
        slots_raw = [s.strip() for s in slots.split("|")]
        slots_validos = []
        for s in slots_raw:
            try:
                dt = datetime.strptime(s, "%Y-%m-%d %H:%M")
                slots_validos.append(dt.isoformat())
            except ValueError:
                await interaction.response.send_message(
                    f"❌ Formato inválido en slot: `{s}`\nUsa `YYYY-MM-DD HH:MM` separados por `|`\n"
                    f"Ejemplo: `2026-08-01 18:00|2026-08-02 19:00`",
                    ephemeral=True
                )
                return

        if len(slots_validos) < 2:
            await interaction.response.send_message("❌ Propón al menos 2 opciones de horario.", ephemeral=True)
            return

        if len(slots_validos) > 5:
            await interaction.response.send_message("❌ Máximo 5 opciones de horario por reunión.", ephemeral=True)
            return

        # Guardar reunión en BD (sin mensaje_id aún)
        async with await get_db() as db:
            cur = await db.execute(
                """INSERT INTO reuniones (titulo, descripcion, duracion_min, creado_por, canal_id, guild_id)
                   VALUES (?,?,?,?,?,?)""",
                (titulo, descripcion, duracion, str(interaction.user.id),
                 str(interaction.channel_id), str(interaction.guild_id))
            )
            reunion_id = cur.lastrowid

            # Guardar slots (reutilizamos disponibilidad como catálogo de slots)
            # Los slots sin votos aún no tienen filas, así que los guardamos en una tabla auxiliar
            for slot in slots_validos:
                await db.execute(
                    "INSERT OR IGNORE INTO disponibilidad (reunion_id, user_id, slot, respuesta) VALUES (?,?,?,?)",
                    (reunion_id, "__slot__", slot, "puede")  # fila centinela para recordar los slots
                )
            await db.commit()

        reunion_dict = {
            "id": reunion_id, "titulo": titulo, "descripcion": descripcion,
            "duracion_min": duracion, "estado": "abierta"
        }
        slots_conteo = {s: {} for s in slots_validos}
        embed = _build_embed(reunion_dict, slots_conteo)

        view = DisponibilidadView(reunion_id, slots_validos)
        await interaction.response.send_message(embed=embed, view=view)

        # Guardar mensaje_id para poder editarlo después
        msg = await interaction.original_response()
        async with await get_db() as db:
            await db.execute("UPDATE reuniones SET mensaje_id=? WHERE id=?", (str(msg.id), reunion_id))
            await db.commit()

    # ─────────────────────────────────────────────
    #  /reunion_ver
    # ─────────────────────────────────────────────
    @app_commands.command(name="reunion_ver", description="Ver el resumen de disponibilidad de una reunión")
    @app_commands.describe(reunion_id="ID de la reunión")
    async def reunion_ver(self, interaction: discord.Interaction, reunion_id: int):
        async with await get_db() as db:
            async with db.execute(
                "SELECT id, titulo, descripcion, duracion_min, estado, fecha_elegida FROM reuniones WHERE id=? AND guild_id=?",
                (reunion_id, str(interaction.guild_id))
            ) as cur:
                r = await cur.fetchone()

            if not r:
                await interaction.response.send_message(f"❌ No existe la reunión #{reunion_id}.", ephemeral=True)
                return

            # Obtener slots y conteos (excluir fila centinela)
            async with db.execute(
                """SELECT slot, respuesta, COUNT(*) FROM disponibilidad
                   WHERE reunion_id=? AND user_id != '__slot__'
                   GROUP BY slot, respuesta""",
                (reunion_id,)
            ) as cur:
                rows = await cur.fetchall()

            # Slots en orden
            async with db.execute(
                "SELECT slot FROM disponibilidad WHERE reunion_id=? AND user_id='__slot__' ORDER BY slot",
                (reunion_id,)
            ) as cur:
                slots_rows = await cur.fetchall()

        slots_validos = [row[0] for row in slots_rows]
        slots_conteo: dict[str, dict] = {s: {} for s in slots_validos}
        for slot, resp, cnt in rows:
            if slot in slots_conteo:
                slots_conteo[slot][resp] = cnt

        reunion_dict = {
            "id": r[0], "titulo": r[1], "descripcion": r[2],
            "duracion_min": r[3], "estado": r[4]
        }

        embed = _build_embed(reunion_dict, slots_conteo)

        if r[4] == "confirmada" and r[5]:
            embed.add_field(
                name="✅ Horario confirmado",
                value=f"**{_formatear_slot(r[5])}**",
                inline=False
            )

        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ─────────────────────────────────────────────
    #  /reunion_confirmar — admin elige el horario ganador
    # ─────────────────────────────────────────────
    @app_commands.command(name="reunion_confirmar", description="Confirma el horario final de una reunión y notifica a todos")
    @app_commands.describe(
        reunion_id="ID de la reunión",
        slot="Horario elegido (YYYY-MM-DD HH:MM)",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def reunion_confirmar(
        self,
        interaction: discord.Interaction,
        reunion_id: int,
        slot: str,
    ):
        try:
            dt = datetime.strptime(slot, "%Y-%m-%d %H:%M")
            slot_iso = dt.isoformat()
        except ValueError:
            await interaction.response.send_message("❌ Formato inválido. Usa `YYYY-MM-DD HH:MM`", ephemeral=True)
            return

        async with await get_db() as db:
            async with db.execute(
                "SELECT id, titulo, canal_id, guild_id FROM reuniones WHERE id=? AND guild_id=?",
                (reunion_id, str(interaction.guild_id))
            ) as cur:
                r = await cur.fetchone()

            if not r:
                await interaction.response.send_message(f"❌ No existe la reunión #{reunion_id}.", ephemeral=True)
                return

            await db.execute(
                "UPDATE reuniones SET estado='confirmada', fecha_elegida=? WHERE id=?",
                (slot_iso, reunion_id)
            )

            # Obtener todos los que respondieron "puede" o "tal_vez" en ese slot
            async with db.execute(
                """SELECT DISTINCT user_id FROM disponibilidad
                   WHERE reunion_id=? AND slot=? AND respuesta IN ('puede','tal_vez') AND user_id != '__slot__'""",
                (reunion_id, slot_iso)
            ) as cur:
                confirmados = await cur.fetchall()

            await db.commit()

        guild = self.bot.get_guild(int(r[3]))
        slot_str = _formatear_slot(slot_iso)

        embed = discord.Embed(
            title=f"✅ Reunión confirmada — {r[1]}",
            description=f"**{slot_str}**",
            color=discord.Color.green()
        )
        embed.set_footer(text=f"Confirmada por {interaction.user.display_name}")

        await interaction.response.send_message(embed=embed)

        # Notificar por DM a los que pueden asistir
        if guild:
            for (user_id,) in confirmados:
                try:
                    miembro = guild.get_member(int(user_id))
                    if miembro:
                        await miembro.send(
                            f"📅 **Reunión confirmada en GDD**\n"
                            f"**{r[1]}**\n"
                            f"📆 {slot_str}\n"
                            f"¡Agéndala! 🗓️"
                        )
                except discord.Forbidden:
                    pass


async def setup(bot):
    await bot.add_cog(Reuniones(bot))
