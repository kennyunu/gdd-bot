import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime
from database import get_db
import notion_sync

AREAS = ["Logística", "Comunicaciones", "Pedagogía", "Relaciones Externas", "Tesorería"]

AREA_COLORES = {
    "Logística":           discord.Color.blue(),
    "Comunicaciones":      discord.Color.purple(),
    "Pedagogía":           discord.Color.green(),
    "Relaciones Externas": discord.Color.orange(),
    "Tesorería":           discord.Color.gold(),
}

ESTADO_EMOJI = {
    "pendiente":    "⏳",
    "en_progreso":  "🔄",
    "completada":   "✅",
    "bloqueada":    "🔒",
}


class Tareas(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ─────────────────────────────────────────────
    #  /tarea crear
    # ─────────────────────────────────────────────
    @app_commands.command(name="tarea_crear", description="Crea una nueva tarea para un área de GDD")
    @app_commands.describe(
        nombre="Nombre corto de la tarea",
        area="Área del organigrama responsable",
        responsable="@menciona al responsable",
        deadline="Fecha límite (YYYY-MM-DD)",
        descripcion="Descripción opcional",
        depende_de="ID de tarea de la que depende esta (opcional)",
    )
    @app_commands.choices(area=[app_commands.Choice(name=a, value=a) for a in AREAS])
    async def tarea_crear(
        self,
        interaction: discord.Interaction,
        nombre: str,
        area: str,
        responsable: discord.Member,
        deadline: str = None,
        descripcion: str = None,
        depende_de: int = None,
    ):
        # Validar fecha
        if deadline:
            try:
                datetime.strptime(deadline, "%Y-%m-%d")
            except ValueError:
                await interaction.response.send_message(
                    "❌ Formato de fecha inválido. Usa YYYY-MM-DD (ej: 2026-08-15)", ephemeral=True
                )
                return

        # Si depende de otra, verificar que existe
        if depende_de:
            async with await get_db() as db:
                async with db.execute("SELECT id, nombre, estado FROM tareas WHERE id=? AND guild_id=?",
                                      (depende_de, str(interaction.guild_id))) as cur:
                    dep_tarea = await cur.fetchone()
            if not dep_tarea:
                await interaction.response.send_message(
                    f"❌ No existe ninguna tarea con ID `{depende_de}`.", ephemeral=True
                )
                return
            # Si la dependencia no está completa, esta tarea nace bloqueada
            estado_inicial = "bloqueada" if dep_tarea[2] != "completada" else "pendiente"
        else:
            estado_inicial = "pendiente"

        async with await get_db() as db:
            cur = await db.execute(
                """INSERT INTO tareas (nombre, descripcion, area, responsable, deadline, estado, guild_id)
                   VALUES (?,?,?,?,?,?,?)""",
                (nombre, descripcion, area, str(responsable.id), deadline, estado_inicial, str(interaction.guild_id))
            )
            tarea_id = cur.lastrowid

            if depende_de:
                await db.execute(
                    "INSERT INTO dependencias (tarea_id, depende_de_id) VALUES (?,?)",
                    (tarea_id, depende_de)
                )
            await db.commit()

        # ── Sync a Notion (no bloquea si falla) ──
        page_id = await notion_sync.crear_tarea_notion(
            tarea_id=tarea_id,
            nombre=nombre,
            area=area,
            responsable_nombre=responsable.display_name,
            estado=estado_inicial,
            deadline=deadline,
            descripcion=descripcion,
        )
        if page_id:
            async with await get_db() as db2:
                await db2.execute(
                    "INSERT OR REPLACE INTO notion_pages (entidad_tipo, entidad_id, page_id) VALUES ('tarea',?,?)",
                    (tarea_id, page_id)
                )
                await db2.commit()

        embed = discord.Embed(
            title=f"{ESTADO_EMOJI[estado_inicial]} Tarea #{tarea_id} creada",
            description=descripcion or "*Sin descripción*",
            color=AREA_COLORES.get(area, discord.Color.blurple())
        )
        embed.add_field(name="📌 Nombre", value=nombre, inline=True)
        embed.add_field(name="🏷️ Área", value=area, inline=True)
        embed.add_field(name="👤 Responsable", value=responsable.mention, inline=True)
        embed.add_field(name="📅 Deadline", value=deadline or "Sin fecha", inline=True)
        embed.add_field(name="🔖 Estado", value=estado_inicial, inline=True)
        if depende_de:
            embed.add_field(name="🔗 Depende de", value=f"Tarea #{depende_de}", inline=True)
        embed.set_footer(text=f"Creada por {interaction.user.display_name}")

        await interaction.response.send_message(embed=embed)

        # Notificar al responsable por DM
        try:
            dm_msg = (
                f"📋 **Te asignaron una tarea en GDD**\n"
                f"**#{tarea_id} — {nombre}**\n"
                f"Área: {area} | Deadline: {deadline or 'Sin fecha'}\n"
                f"Estado: `{estado_inicial}`"
            )
            if estado_inicial == "bloqueada":
                dm_msg += f"\n⚠️ Esta tarea está **bloqueada** hasta que se complete la tarea #{depende_de}."
            await responsable.send(dm_msg)
        except discord.Forbidden:
            pass  # El usuario tiene DMs cerrados

    # ─────────────────────────────────────────────
    #  /tarea ver
    # ─────────────────────────────────────────────
    @app_commands.command(name="tarea_ver", description="Ver tareas por área, persona o estado")
    @app_commands.describe(
        area="Filtrar por área (opcional)",
        responsable="Filtrar por persona (opcional)",
        estado="Filtrar por estado (opcional)",
    )
    @app_commands.choices(
        area=[app_commands.Choice(name=a, value=a) for a in AREAS],
        estado=[
            app_commands.Choice(name="⏳ Pendiente", value="pendiente"),
            app_commands.Choice(name="🔄 En progreso", value="en_progreso"),
            app_commands.Choice(name="✅ Completada", value="completada"),
            app_commands.Choice(name="🔒 Bloqueada", value="bloqueada"),
        ]
    )
    async def tarea_ver(
        self,
        interaction: discord.Interaction,
        area: str = None,
        responsable: discord.Member = None,
        estado: str = None,
    ):
        query = "SELECT id, nombre, area, responsable, deadline, estado FROM tareas WHERE guild_id=?"
        params = [str(interaction.guild_id)]

        if area:
            query += " AND area=?"
            params.append(area)
        if responsable:
            query += " AND responsable=?"
            params.append(str(responsable.id))
        if estado:
            query += " AND estado=?"
            params.append(estado)

        query += " ORDER BY deadline ASC, id ASC LIMIT 20"

        async with await get_db() as db:
            async with db.execute(query, params) as cur:
                tareas = await cur.fetchall()

        if not tareas:
            await interaction.response.send_message("📭 No se encontraron tareas con esos filtros.", ephemeral=True)
            return

        titulo = "📋 Tareas de GDD"
        if area:
            titulo += f" — {area}"
        embed = discord.Embed(title=titulo, color=AREA_COLORES.get(area, discord.Color.blurple()))

        for t in tareas:
            tid, nombre, tarea_area, resp_id, deadline, estado_t = t
            try:
                miembro = interaction.guild.get_member(int(resp_id))
                resp_str = miembro.display_name if miembro else f"<@{resp_id}>"
            except:
                resp_str = resp_id

            valor = f"{ESTADO_EMOJI.get(estado_t, '❓')} `{estado_t}` | 👤 {resp_str} | 📅 {deadline or 'Sin fecha'}"
            if not area:
                valor = f"🏷️ {tarea_area}\n" + valor
            embed.add_field(name=f"#{tid} — {nombre}", value=valor, inline=False)

        embed.set_footer(text=f"Mostrando {len(tareas)} tarea(s)")
        await interaction.response.send_message(embed=embed)

    # ─────────────────────────────────────────────
    #  /tarea completar
    # ─────────────────────────────────────────────
    @app_commands.command(name="tarea_completar", description="Marca una tarea como completada y desbloquea dependientes")
    @app_commands.describe(tarea_id="ID de la tarea a completar")
    async def tarea_completar(self, interaction: discord.Interaction, tarea_id: int):
        async with await get_db() as db:
            async with db.execute(
                "SELECT id, nombre, area, responsable, estado, flujo_id, flujo_paso FROM tareas WHERE id=? AND guild_id=?",
                (tarea_id, str(interaction.guild_id))
            ) as cur:
                tarea = await cur.fetchone()

            if not tarea:
                await interaction.response.send_message(f"❌ No existe la tarea #{tarea_id}.", ephemeral=True)
                return

            if tarea[4] == "completada":
                await interaction.response.send_message(f"ℹ️ La tarea #{tarea_id} ya estaba completada.", ephemeral=True)
                return

            # Marcar como completada
            await db.execute(
                "UPDATE tareas SET estado='completada' WHERE id=?", (tarea_id,)
            )

            # Buscar tareas que dependían de esta y desbloquearlas
            async with db.execute(
                """SELECT t.id, t.nombre, t.responsable FROM tareas t
                   JOIN dependencias d ON d.tarea_id = t.id
                   WHERE d.depende_de_id = ? AND t.estado = 'bloqueada'""",
                (tarea_id,)
            ) as cur:
                desbloqueadas = await cur.fetchall()

            for dt in desbloqueadas:
                await db.execute("UPDATE tareas SET estado='pendiente' WHERE id=?", (dt[0],))

            await db.commit()

        # ── Sync a Notion ──
        async with await get_db() as db2:
            async with db2.execute(
                "SELECT page_id FROM notion_pages WHERE entidad_tipo='tarea' AND entidad_id=?", (tarea_id,)
            ) as cur:
                row = await cur.fetchone()
        if row:
            await notion_sync.actualizar_estado_notion(row[0], "completada")

        # Construir respuesta
        embed = discord.Embed(
            title=f"✅ Tarea #{tarea_id} completada",
            description=f"**{tarea[1]}** marcada como completada.",
            color=discord.Color.green()
        )

        if desbloqueadas:
            lista = "\n".join([f"• #{dt[0]} — {dt[1]}" for dt in desbloqueadas])
            embed.add_field(
                name=f"🔓 {len(desbloqueadas)} tarea(s) desbloqueada(s)",
                value=lista,
                inline=False
            )

        await interaction.response.send_message(embed=embed)

        # Notificar a los responsables de tareas desbloqueadas
        for dt in desbloqueadas:
            try:
                miembro = interaction.guild.get_member(int(dt[2]))
                if miembro:
                    await miembro.send(
                        f"🔓 **¡Tu tarea en GDD está desbloqueada!**\n"
                        f"**#{dt[0]} — {dt[1]}**\n"
                        f"Ya puedes comenzar — la tarea de la que dependía fue completada ✅"
                    )
            except discord.Forbidden:
                pass

        # Si la tarea pertenece a un flujo, activar siguiente paso
        if tarea[5]:  # flujo_id
            await self._avanzar_flujo(interaction, tarea[5], tarea[6], tarea[2])

    async def _avanzar_flujo(self, interaction, flujo_id, paso_actual, area):
        """Activa el siguiente paso de un flujo automáticamente."""
        async with await get_db() as db:
            async with db.execute(
                "SELECT id, nombre, descripcion, dias_deadline FROM flujo_pasos WHERE flujo_id=? AND paso=?",
                (flujo_id, (paso_actual or 0) + 1)
            ) as cur:
                siguiente = await cur.fetchone()

            if not siguiente:
                # No hay más pasos — flujo completo
                async with db.execute("SELECT nombre FROM flujos WHERE id=?", (flujo_id,)) as cur:
                    flujo = await cur.fetchone()
                await interaction.followup.send(
                    f"🎉 **¡Flujo '{flujo[0]}' completado!** Todos los pasos fueron terminados."
                )
                return

            paso_id, paso_nombre, paso_desc, dias = siguiente
            from datetime import date, timedelta
            deadline = None
            if dias:
                deadline = (date.today() + timedelta(days=dias)).isoformat()

            # Crear la tarea del siguiente paso automáticamente (sin responsable asignado aún)
            await db.execute(
                """INSERT INTO tareas (nombre, descripcion, area, responsable, deadline, estado, flujo_id, flujo_paso, guild_id)
                   VALUES (?,?,?,?,?,'pendiente',?,?,?)""",
                (paso_nombre, paso_desc, area, "sin_asignar", deadline, flujo_id, paso_actual + 1, str(interaction.guild_id))
            )
            await db.commit()

        embed = discord.Embed(
            title=f"➡️ Siguiente paso del flujo activado",
            description=f"**{paso_nombre}**\n{paso_desc or ''}",
            color=discord.Color.blurple()
        )
        if deadline:
            embed.add_field(name="📅 Deadline sugerido", value=deadline)
        embed.set_footer(text="⚠️ Asigna un responsable con /tarea_editar")
        await interaction.followup.send(embed=embed)

    # ─────────────────────────────────────────────
    #  /tarea editar
    # ─────────────────────────────────────────────
    @app_commands.command(name="tarea_editar", description="Edita responsable, deadline o estado de una tarea")
    @app_commands.describe(
        tarea_id="ID de la tarea",
        responsable="Nuevo responsable",
        deadline="Nuevo deadline (YYYY-MM-DD)",
        estado="Nuevo estado",
    )
    @app_commands.choices(estado=[
        app_commands.Choice(name="⏳ Pendiente", value="pendiente"),
        app_commands.Choice(name="🔄 En progreso", value="en_progreso"),
        app_commands.Choice(name="🔒 Bloqueada", value="bloqueada"),
    ])
    async def tarea_editar(
        self,
        interaction: discord.Interaction,
        tarea_id: int,
        responsable: discord.Member = None,
        deadline: str = None,
        estado: str = None,
    ):
        async with await get_db() as db:
            async with db.execute("SELECT id, nombre FROM tareas WHERE id=? AND guild_id=?",
                                  (tarea_id, str(interaction.guild_id))) as cur:
                tarea = await cur.fetchone()

            if not tarea:
                await interaction.response.send_message(f"❌ No existe la tarea #{tarea_id}.", ephemeral=True)
                return

            cambios = []
            if responsable:
                await db.execute("UPDATE tareas SET responsable=? WHERE id=?", (str(responsable.id), tarea_id))
                cambios.append(f"👤 Responsable → {responsable.mention}")
            if deadline:
                await db.execute("UPDATE tareas SET deadline=? WHERE id=?", (deadline, tarea_id))
                cambios.append(f"📅 Deadline → {deadline}")
            if estado:
                await db.execute("UPDATE tareas SET estado=? WHERE id=?", (estado, tarea_id))
                cambios.append(f"🔖 Estado → {estado}")
            await db.commit()

        if not cambios:
            await interaction.response.send_message("ℹ️ No se realizaron cambios.", ephemeral=True)
            return

        # ── Sync a Notion ──
        async with await get_db() as db2:
            async with db2.execute(
                "SELECT page_id FROM notion_pages WHERE entidad_tipo='tarea' AND entidad_id=?", (tarea_id,)
            ) as cur:
                row = await cur.fetchone()
        if row:
            await notion_sync.actualizar_tarea_notion(
                page_id=row[0],
                responsable_nombre=responsable.display_name if responsable else None,
                deadline=deadline,
                estado=estado,
            )

        embed = discord.Embed(
            title=f"✏️ Tarea #{tarea_id} actualizada",
            description="\n".join(cambios),
            color=discord.Color.yellow()
        )
        await interaction.response.send_message(embed=embed)

    # ─────────────────────────────────────────────
    #  /tareas_bloqueadas
    # ─────────────────────────────────────────────
    @app_commands.command(name="tareas_bloqueadas", description="Muestra todas las tareas bloqueadas y por qué")
    async def tareas_bloqueadas(self, interaction: discord.Interaction):
        async with await get_db() as db:
            async with db.execute(
                """SELECT t.id, t.nombre, t.area, t.responsable,
                          dep.id, dep.nombre, dep.estado
                   FROM tareas t
                   JOIN dependencias d ON d.tarea_id = t.id
                   JOIN tareas dep ON dep.id = d.depende_de_id
                   WHERE t.estado = 'bloqueada' AND t.guild_id = ?
                   ORDER BY t.area, t.id""",
                (str(interaction.guild_id),)
            ) as cur:
                bloqueadas = await cur.fetchall()

        if not bloqueadas:
            await interaction.response.send_message("🎉 ¡No hay tareas bloqueadas!", ephemeral=True)
            return

        embed = discord.Embed(
            title="🔒 Tareas bloqueadas",
            description="Estas tareas no pueden avanzar hasta que se complete su dependencia.",
            color=discord.Color.red()
        )

        for b in bloqueadas:
            tid, tnombre, tarea, tresp, dep_id, dep_nombre, dep_estado = b
            valor = (
                f"🔗 Esperando: **#{dep_id} — {dep_nombre}** `{ESTADO_EMOJI.get(dep_estado, '')} {dep_estado}`\n"
                f"🏷️ {tarea}"
            )
            embed.add_field(name=f"#{tid} — {tnombre}", value=valor, inline=False)

        await interaction.response.send_message(embed=embed)


async def setup(bot):
    await bot.add_cog(Tareas(bot))
