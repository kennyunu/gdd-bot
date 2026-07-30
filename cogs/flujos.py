import discord
from discord import app_commands
from discord.ext import commands
from database import get_db
import notion_sync

# ─────────────────────────────────────────────────────────
#  FLUJOS PREDEFINIDOS del organigrama de GDD
#  Cada flujo representa un proceso documentado del grupo.
#  Al iniciarlo se crean las tareas en cadena automáticamente.
# ─────────────────────────────────────────────────────────
FLUJOS_PREDEFINIDOS = {
    "organizar_charla": {
        "nombre": "Organizar Charla",
        "area": "Logística",
        "descripcion": "Flujo completo para organizar una charla/taller en GDD",
        "pasos": [
            {"nombre": "Conseguir ponente", "descripcion": "Confirmar quién dará la charla y el tema", "dias": 14},
            {"nombre": "Reservar espacio físico", "descripcion": "Pedir sala al profesor Jean Pierre o al NEA", "dias": 10},
            {"nombre": "Confirmar fecha y hora", "descripcion": "Coordinar con ponente y espacio disponible", "dias": 8},
            {"nombre": "Crear pieza gráfica", "descripcion": "Pedir a Comunicaciones el arte del evento", "dias": 6},
            {"nombre": "Publicar en redes", "descripcion": "Instagram, Discord y WhatsApp con al menos 1 semana de anticipación", "dias": 4},
            {"nombre": "Hacer recordatorio el día anterior", "descripcion": "Post en Discord y estado en WhatsApp", "dias": 1},
            {"nombre": "Documentar asistencia y resultados", "descripcion": "Registro de quiénes asistieron y qué se trató", "dias": 0},
        ]
    },
    "publicacion_redes": {
        "nombre": "Publicación en Redes",
        "area": "Comunicaciones",
        "descripcion": "Flujo de solicitud y publicación de contenido en Instagram/Discord",
        "pasos": [
            {"nombre": "Recibir solicitud de publicación", "descripcion": "El solicitante llena el formulario con tema, texto e imágenes", "dias": 14},
            {"nombre": "Revisar contenido", "descripcion": "Receptor de publicaciones valida que cumpla los lineamientos", "dias": 12},
            {"nombre": "Diseñar pieza gráfica", "descripcion": "Diseñador crea el arte (1 semana de plazo)", "dias": 7},
            {"nombre": "Aprobar pieza final", "descripcion": "Validación por el área solicitante", "dias": 2},
            {"nombre": "Programar y publicar", "descripcion": "Publicar en Instagram, Discord y/o WhatsApp según aplique", "dias": 0},
        ]
    },
    "cotizacion_compra": {
        "nombre": "Cotización y Compra",
        "area": "Tesorería",
        "descripcion": "Flujo para solicitar y aprobar una compra con recursos del grupo",
        "pasos": [
            {"nombre": "Recibir solicitud de compra", "descripcion": "El área solicitante describe qué necesita y para qué", "dias": 14},
            {"nombre": "Conseguir cotización 1", "descripcion": "Analista busca primer proveedor con precio", "dias": 10},
            {"nombre": "Conseguir cotización 2", "descripcion": "Comparar con al menos otro proveedor", "dias": 8},
            {"nombre": "Aprobar compra", "descripcion": "Presentar cotizaciones al equipo admin para aval", "dias": 5},
            {"nombre": "Ejecutar compra", "descripcion": "Realizar la compra con el proveedor seleccionado", "dias": 3},
            {"nombre": "Registrar en inventario", "descripcion": "Auditor registra el bien en el Excel de control", "dias": 1},
        ]
    },
    "checkpoint_proyecto": {
        "nombre": "Checkpoint de Proyecto",
        "area": "Logística",
        "descripcion": "Seguimiento del ciclo semestral: GDD doc → Teaser → Pitch → MVP → Shark Tank → Showcase",
        "pasos": [
            {"nombre": "Documento GDD entregado", "descripcion": "El equipo entrega el Game Design Document inicial", "dias": 30},
            {"nombre": "Teaser publicado", "descripcion": "Video teaser del juego publicado en redes", "dias": 25},
            {"nombre": "Pitch presentado", "descripcion": "Presentación del concepto al grupo", "dias": 20},
            {"nombre": "MVP jugable", "descripcion": "Primera versión jugable del juego", "dias": 14},
            {"nombre": "Shark Tank con Efecto Studio", "descripcion": "Presentación formal al jurado externo", "dias": 7},
            {"nombre": "Showcase CyT", "descripcion": "Exhibición final en el evento de cierre de semestre", "dias": 0},
        ]
    },
    "alianza_externa": {
        "nombre": "Gestionar Alianza Externa",
        "area": "Relaciones Externas",
        "descripcion": "Flujo para establecer contacto y acuerdo con grupo o empresa externa",
        "pasos": [
            {"nombre": "Identificar contacto potencial", "descripcion": "Mapear el grupo/empresa y encontrar canal de contacto", "dias": 21},
            {"nombre": "Primer contacto formal", "descripcion": "Enviar mensaje de presentación de GDD", "dias": 18},
            {"nombre": "Reunión de presentación", "descripcion": "Call o encuentro para explorar colaboración", "dias": 14},
            {"nombre": "Definir términos de colaboración", "descripcion": "Documentar qué ofrece cada parte y responsabilidades", "dias": 7},
            {"nombre": "Publicar alianza en redes", "descripcion": "Anuncio oficial en Instagram y Discord", "dias": 3},
            {"nombre": "Registrar en base de datos de alianzas", "descripcion": "Actualizar el Excel de contactos externos", "dias": 0},
        ]
    },
}


class Flujos(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ─────────────────────────────────────────────
    #  /flujo_iniciar
    # ─────────────────────────────────────────────
    @app_commands.command(name="flujo_iniciar", description="Inicia un flujo predefinido del organigrama de GDD")
    @app_commands.describe(
        tipo="Tipo de flujo a iniciar",
        responsable="Responsable del primer paso",
        contexto="Contexto adicional (ej: 'Charla de arte con Ilustranima')",
    )
    @app_commands.choices(tipo=[
        app_commands.Choice(name="📅 Organizar Charla", value="organizar_charla"),
        app_commands.Choice(name="📱 Publicación en Redes", value="publicacion_redes"),
        app_commands.Choice(name="💰 Cotización y Compra", value="cotizacion_compra"),
        app_commands.Choice(name="🎮 Checkpoint de Proyecto", value="checkpoint_proyecto"),
        app_commands.Choice(name="🤝 Gestionar Alianza Externa", value="alianza_externa"),
    ])
    async def flujo_iniciar(
        self,
        interaction: discord.Interaction,
        tipo: str,
        responsable: discord.Member,
        contexto: str = "",
    ):
        plantilla = FLUJOS_PREDEFINIDOS[tipo]
        from datetime import date, timedelta

        async with await get_db() as db:
            # Crear el flujo
            cur = await db.execute(
                "INSERT INTO flujos (nombre, area, descripcion, guild_id) VALUES (?,?,?,?)",
                (
                    f"{plantilla['nombre']}{' — ' + contexto if contexto else ''}",
                    plantilla["area"],
                    plantilla["descripcion"],
                    str(interaction.guild_id)
                )
            )
            flujo_id = cur.lastrowid

            # Crear los pasos del flujo
            for i, paso in enumerate(plantilla["pasos"]):
                await db.execute(
                    "INSERT INTO flujo_pasos (flujo_id, paso, nombre, descripcion, dias_deadline) VALUES (?,?,?,?,?)",
                    (flujo_id, i + 1, paso["nombre"], paso["descripcion"], paso["dias"])
                )

            # Crear solo la PRIMERA tarea (las demás se crean al completar la anterior)
            primer_paso = plantilla["pasos"][0]
            deadline = (date.today() + timedelta(days=primer_paso["dias"])).isoformat() if primer_paso["dias"] else None

            cur2 = await db.execute(
                """INSERT INTO tareas (nombre, descripcion, area, responsable, deadline, estado, flujo_id, flujo_paso, guild_id)
                   VALUES (?,?,?,?,?,'pendiente',?,1,?)""",
                (
                    primer_paso["nombre"],
                    primer_paso["descripcion"],
                    plantilla["area"],
                    str(responsable.id),
                    deadline,
                    flujo_id,
                    str(interaction.guild_id)
                )
            )
            primera_tarea_id = cur2.lastrowid
            await db.commit()

        # Embed de confirmación con todos los pasos visibles
        embed = discord.Embed(
            title=f"🚀 Flujo iniciado: {plantilla['nombre']}",
            description=f"{plantilla['descripcion']}\n{'📝 ' + contexto if contexto else ''}",
            color=discord.Color.blurple()
        )
        embed.add_field(name="🏷️ Área", value=plantilla["area"], inline=True)
        embed.add_field(name="🆔 Flujo ID", value=f"#{flujo_id}", inline=True)

        pasos_str = ""
        for i, paso in enumerate(plantilla["pasos"]):
            emoji = "▶️" if i == 0 else "⏸️"
            pasos_str += f"{emoji} **Paso {i+1}:** {paso['nombre']}\n"
        embed.add_field(name="📋 Pasos del flujo", value=pasos_str, inline=False)

        embed.add_field(
            name="▶️ Primera tarea activa",
            value=f"#{primera_tarea_id} — **{primer_paso['nombre']}**\n👤 {responsable.mention} | 📅 {deadline or 'Sin fecha'}",
            inline=False
        )
        embed.set_footer(text="Cada paso se activa automáticamente al completar el anterior ✅")

        await interaction.response.send_message(embed=embed)

        # ── Sync a Notion ──
        pasos_nombres = [p["nombre"] for p in plantilla["pasos"]]
        page_id = await notion_sync.crear_flujo_notion(
            flujo_id=flujo_id,
            nombre=plantilla["nombre"] + (f" — {contexto}" if contexto else ""),
            area=plantilla["area"],
            pasos=pasos_nombres,
        )
        if page_id:
            async with await get_db() as db2:
                await db2.execute(
                    "INSERT OR REPLACE INTO notion_pages (entidad_tipo, entidad_id, page_id) VALUES ('flujo',?,?)",
                    (flujo_id, page_id)
                )
                await db2.commit()

        # DM al responsable
        try:
            await responsable.send(
                f"🚀 **Se inició el flujo '{plantilla['nombre']}' en GDD**\n"
                f"Tu primera tarea: **#{primera_tarea_id} — {primer_paso['nombre']}**\n"
                f"📅 Deadline: {deadline or 'Sin fecha'}\n"
                f"Usa `/tarea_completar {primera_tarea_id}` cuando termines para activar el siguiente paso."
            )
        except discord.Forbidden:
            pass

    # ─────────────────────────────────────────────
    #  /flujo_ver
    # ─────────────────────────────────────────────
    @app_commands.command(name="flujo_ver", description="Ver el estado actual de un flujo activo")
    @app_commands.describe(flujo_id="ID del flujo")
    async def flujo_ver(self, interaction: discord.Interaction, flujo_id: int):
        async with await get_db() as db:
            async with db.execute(
                "SELECT id, nombre, area FROM flujos WHERE id=? AND guild_id=?",
                (flujo_id, str(interaction.guild_id))
            ) as cur:
                flujo = await cur.fetchone()

            if not flujo:
                await interaction.response.send_message(f"❌ No existe el flujo #{flujo_id}.", ephemeral=True)
                return

            async with db.execute(
                "SELECT id, flujo_paso, nombre, responsable, estado, deadline FROM tareas WHERE flujo_id=? ORDER BY flujo_paso",
                (flujo_id,)
            ) as cur:
                tareas = await cur.fetchall()

        from cogs.tareas import ESTADO_EMOJI
        embed = discord.Embed(
            title=f"📋 Flujo #{flujo_id} — {flujo[1]}",
            description=f"Área: {flujo[2]}",
            color=discord.Color.blurple()
        )

        for t in tareas:
            tid, paso, nombre, resp_id, estado, deadline = t
            try:
                miembro = interaction.guild.get_member(int(resp_id)) if resp_id != "sin_asignar" else None
                resp_str = miembro.display_name if miembro else "⚠️ Sin asignar"
            except:
                resp_str = "Sin asignar"
            emoji = ESTADO_EMOJI.get(estado, "❓")
            embed.add_field(
                name=f"Paso {paso}: {nombre}",
                value=f"{emoji} `{estado}` | 👤 {resp_str} | 📅 {deadline or 'Sin fecha'} | ID: #{tid}",
                inline=False
            )

        await interaction.response.send_message(embed=embed)


async def setup(bot):
    await bot.add_cog(Flujos(bot))
