"""
cogs/jam.py — Tooling completo para la 4D4H Game Jam de GDD
============================================================
Cubre todo el ciclo de la jam:
  1. Configuración inicial (canales, URL de itch.io)
  2. Registro de equipos con validación
  3. Arranque oficial (tema + diversificadores + contador)
  4. Recordatorios automáticos de deadline de entrega
  5. Detección automática de entregas (links itch.io)
  6. Votación por categorías con botones interactivos
  7. Resultados finales
"""

import discord
from discord import app_commands
from discord.ext import commands, tasks
from datetime import datetime, timedelta
from database import get_db

CATEGORIAS_DEFAULT = [
    ("🏆 Game of the Jam (GOTJ)", "El juego más completo y destacado de la jam"),
    ("🎨 Mejores Visuales", "Arte, diseño visual y estética general"),
    ("🎵 Mejor Audio Original", "Música y efectos de sonido creados durante la jam"),
    ("⚙️ Mecánica Más Original", "Innovación en la mecánica de juego"),
    ("📈 Mejor Curva de Dificultad", "Progresión y balance del reto"),
    ("♿ Más Accesible", "Facilidad de entrada y opciones de accesibilidad"),
]


# ─── Vista de votación ────────────────────────────────────────────────────────

class VotacionView(discord.ui.View):
    """Botones de votación para una categoría. Uno por equipo registrado."""

    def __init__(self, categoria_id: int, equipos: list[tuple]):
        super().__init__(timeout=None)
        self.categoria_id = categoria_id
        for equipo_id, nombre in equipos:
            self.add_item(VotoButton(categoria_id, equipo_id, nombre))


class VotoButton(discord.ui.Button):
    def __init__(self, categoria_id: int, equipo_id: int, nombre_equipo: str):
        super().__init__(
            label=nombre_equipo[:80],
            style=discord.ButtonStyle.primary,
            custom_id=f"voto_{categoria_id}_{equipo_id}"
        )
        self.categoria_id = categoria_id
        self.equipo_id = equipo_id

    async def callback(self, interaction: discord.Interaction):
        async with await get_db() as db:
            # Verificar que la categoría sigue abierta
            async with db.execute(
                "SELECT estado FROM jam_categorias WHERE id=?", (self.categoria_id,)
            ) as cur:
                cat = await cur.fetchone()

            if not cat or cat[0] != "abierta":
                await interaction.response.send_message(
                    "⏱️ La votación para esta categoría ya cerró.", ephemeral=True
                )
                return

            # Verificar que el votante no es del equipo que vota (no puede votar por sí mismo)
            async with db.execute(
                "SELECT 1 FROM jam_integrantes WHERE equipo_id=? AND user_id=?",
                (self.equipo_id, str(interaction.user.id))
            ) as cur:
                es_miembro = await cur.fetchone()

            if es_miembro:
                await interaction.response.send_message(
                    "❌ No puedes votar por tu propio equipo.", ephemeral=True
                )
                return

            # Registrar voto (upsert — cambia si ya votó)
            async with db.execute(
                "SELECT equipo_id FROM jam_votos WHERE categoria_id=? AND user_id=?",
                (self.categoria_id, str(interaction.user.id))
            ) as cur:
                voto_anterior = await cur.fetchone()

            await db.execute(
                """INSERT INTO jam_votos (categoria_id, user_id, equipo_id) VALUES (?,?,?)
                   ON CONFLICT(categoria_id, user_id) DO UPDATE SET equipo_id=excluded.equipo_id""",
                (self.categoria_id, str(interaction.user.id), self.equipo_id)
            )
            await db.commit()

        accion = "cambiado a" if voto_anterior else "registrado para"
        await interaction.response.send_message(
            f"✅ Voto {accion} **{self.label}**", ephemeral=True
        )


# ─── Cog principal ────────────────────────────────────────────────────────────

class Jam(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.recordatorios_jam.start()

    def cog_unload(self):
        self.recordatorios_jam.cancel()

    # ── Helpers ──────────────────────────────────────────────────────────────

    async def _get_config(self, guild_id: str) -> dict | None:
        async with await get_db() as db:
            async with db.execute(
                "SELECT * FROM jam_config WHERE guild_id=?", (guild_id,)
            ) as cur:
                row = await cur.fetchone()
                if not row:
                    return None
                cols = [d[0] for d in cur.description]
                return dict(zip(cols, row))

    async def _verificar_jam_activa(self, interaction: discord.Interaction, estado_requerido: list[str]) -> bool:
        config = await self._get_config(str(interaction.guild_id))
        if not config or config["estado"] not in estado_requerido:
            estados_str = " o ".join(f"`{e}`" for e in estado_requerido)
            await interaction.response.send_message(
                f"❌ Este comando solo funciona cuando la jam está en estado {estados_str}.\n"
                f"Estado actual: `{config['estado'] if config else 'sin configurar'}`",
                ephemeral=True
            )
            return False
        return True

    # ── SETUP ────────────────────────────────────────────────────────────────

    @app_commands.command(name="jam_configurar", description="Configura los canales y parámetros de la 4D4H Game Jam")
    @app_commands.describe(
        canal_jam="Canal principal de anuncios de la jam",
        canal_entregas="Canal donde los equipos pegan su link de itch.io",
        canal_votos="Canal donde se publican las votaciones",
        itch_url="URL de la jam en itch.io (ej: https://itch.io/jam/4d4h-game-jam)",
        nombre="Nombre de la edición (ej: '4D4H 2026')",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def jam_configurar(
        self,
        interaction: discord.Interaction,
        canal_jam: discord.TextChannel,
        canal_entregas: discord.TextChannel,
        canal_votos: discord.TextChannel,
        itch_url: str,
        nombre: str = "4D4H Game Jam",
    ):
        guild_id = str(interaction.guild_id)
        async with await get_db() as db:
            await db.execute(
                """INSERT INTO jam_config
                   (guild_id, nombre, estado, canal_jam_id, canal_entregas_id, canal_votos_id, itch_jam_url)
                   VALUES (?,?,?,?,?,?,?)
                   ON CONFLICT(guild_id) DO UPDATE SET
                     nombre=excluded.nombre,
                     canal_jam_id=excluded.canal_jam_id,
                     canal_entregas_id=excluded.canal_entregas_id,
                     canal_votos_id=excluded.canal_votos_id,
                     itch_jam_url=excluded.itch_jam_url""",
                (guild_id, nombre, "registros",
                 str(canal_jam.id), str(canal_entregas.id),
                 str(canal_votos.id), itch_url)
            )

            # Crear categorías por defecto si no existen
            async with db.execute(
                "SELECT COUNT(*) FROM jam_categorias WHERE guild_id=?", (guild_id,)
            ) as cur:
                count = (await cur.fetchone())[0]

            if count == 0:
                for nombre_cat, desc in CATEGORIAS_DEFAULT:
                    await db.execute(
                        "INSERT INTO jam_categorias (guild_id, nombre, descripcion) VALUES (?,?,?)",
                        (guild_id, nombre_cat, desc)
                    )
            await db.commit()

        embed = discord.Embed(
            title=f"⚙️ {nombre} configurada",
            color=discord.Color.green()
        )
        embed.add_field(name="📢 Canal principal", value=canal_jam.mention, inline=True)
        embed.add_field(name="📦 Entregas", value=canal_entregas.mention, inline=True)
        embed.add_field(name="🗳️ Votaciones", value=canal_votos.mention, inline=True)
        embed.add_field(name="🔗 itch.io", value=itch_url, inline=False)
        embed.add_field(
            name="✅ Estado",
            value="Registros abiertos — usa `/jam_registrar` para inscribirse",
            inline=False
        )
        await interaction.response.send_message(embed=embed)

    # ── REGISTRO DE EQUIPOS ──────────────────────────────────────────────────

    @app_commands.command(name="jam_registrar", description="Registra tu equipo en la 4D4H Game Jam")
    @app_commands.describe(
        nombre_equipo="Nombre de tu equipo",
        engine="Engine o herramienta principal (ej: Godot, Unity, GameMaker...)",
        integrante2="Segundo integrante (opcional)",
        integrante3="Tercer integrante (opcional)",
        integrante4="Cuarto integrante (opcional)",
        integrante5="Quinto integrante (opcional)",
    )
    async def jam_registrar(
        self,
        interaction: discord.Interaction,
        nombre_equipo: str,
        engine: str = None,
        integrante2: discord.Member = None,
        integrante3: discord.Member = None,
        integrante4: discord.Member = None,
        integrante5: discord.Member = None,
    ):
        if not await self._verificar_jam_activa(interaction, ["registros", "activa"]):
            return

        guild_id = str(interaction.guild_id)
        integrantes = [interaction.user] + [m for m in [integrante2, integrante3, integrante4, integrante5] if m]
        integrantes_ids = [str(m.id) for m in integrantes]

        async with await get_db() as db:
            # Verificar que nadie ya esté en otro equipo
            placeholders = ",".join("?" * len(integrantes_ids))
            async with db.execute(
                f"""SELECT ji.user_id, je.nombre FROM jam_integrantes ji
                    JOIN jam_equipos je ON je.id = ji.equipo_id
                    WHERE ji.user_id IN ({placeholders}) AND je.guild_id=?""",
                (*integrantes_ids, guild_id)
            ) as cur:
                ya_registrados = await cur.fetchall()

            if ya_registrados:
                conflictos = "\n".join([f"<@{uid}> → equipo **{en}**" for uid, en in ya_registrados])
                await interaction.response.send_message(
                    f"❌ Algunos integrantes ya están en un equipo:\n{conflictos}",
                    ephemeral=True
                )
                return

            # Crear equipo
            cur = await db.execute(
                "INSERT INTO jam_equipos (guild_id, nombre, engine, lider_id) VALUES (?,?,?,?)",
                (guild_id, nombre_equipo, engine, str(interaction.user.id))
            )
            equipo_id = cur.lastrowid

            for uid in integrantes_ids:
                await db.execute(
                    "INSERT INTO jam_integrantes (equipo_id, user_id) VALUES (?,?)",
                    (equipo_id, uid)
                )
            await db.commit()

        embed = discord.Embed(
            title=f"🎮 Equipo #{equipo_id} registrado — {nombre_equipo}",
            color=discord.Color.green()
        )
        embed.add_field(name="👑 Líder", value=interaction.user.mention, inline=True)
        embed.add_field(name="⚙️ Engine", value=engine or "Por definir", inline=True)
        embed.add_field(
            name=f"👥 Equipo ({len(integrantes)} personas)",
            value=" ".join(m.mention for m in integrantes),
            inline=False
        )

        config = await self._get_config(guild_id)
        if config and config.get("itch_jam_url"):
            embed.add_field(
                name="📦 Al terminar",
                value=f"Suban su juego en {config['itch_jam_url']} y pegan el link en el canal de entregas.",
                inline=False
            )

        await interaction.response.send_message(embed=embed)

        # Notificar en canal de la jam
        if config and config.get("canal_jam_id"):
            canal = interaction.guild.get_channel(int(config["canal_jam_id"]))
            if canal:
                await canal.send(
                    f"🎮 Nuevo equipo registrado: **{nombre_equipo}** "
                    f"({' '.join(m.mention for m in integrantes)}) ¡Bienvenidos! 🔥"
                )

    # ── ARRANQUE OFICIAL ─────────────────────────────────────────────────────

    @app_commands.command(name="jam_arrancar", description="Anuncia el tema, los diversificadores y arranca el contador oficial")
    @app_commands.describe(
        tema="El tema de la jam (se revela aquí)",
        fin="Fecha y hora de cierre de entregas (YYYY-MM-DD HH:MM)",
        diversificadores="Diversificadores separados por | (ej: 'Solo una pantalla|Sin texto|Usa el micrófono')",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def jam_arrancar(
        self,
        interaction: discord.Interaction,
        tema: str,
        fin: str,
        diversificadores: str = None,
    ):
        if not await self._verificar_jam_activa(interaction, ["registros"]):
            return

        try:
            fin_dt = datetime.strptime(fin, "%Y-%m-%d %H:%M")
        except ValueError:
            await interaction.response.send_message(
                "❌ Formato de fecha inválido. Usa: `YYYY-MM-DD HH:MM`", ephemeral=True
            )
            return

        guild_id = str(interaction.guild_id)
        ahora = datetime.now()

        async with await get_db() as db:
            await db.execute(
                """UPDATE jam_config SET tema=?, estado='activa', inicio=?, fin=? WHERE guild_id=?""",
                (tema, ahora.isoformat(), fin_dt.isoformat(), guild_id)
            )

            # Guardar diversificadores
            if diversificadores:
                await db.execute("DELETE FROM jam_diversificadores WHERE guild_id=?", (guild_id,))
                for div in diversificadores.split("|"):
                    div = div.strip()
                    if div:
                        await db.execute(
                            "INSERT INTO jam_diversificadores (guild_id, nombre) VALUES (?,?)",
                            (guild_id, div)
                        )

            # Obtener equipos registrados para mencionar
            async with db.execute(
                "SELECT lider_id FROM jam_equipos WHERE guild_id=?", (guild_id,)
            ) as cur:
                lideres = await cur.fetchall()

            await db.commit()

        config = await self._get_config(guild_id)
        canal = interaction.guild.get_channel(int(config["canal_jam_id"])) if config else None

        duracion = fin_dt - ahora
        horas_totales = int(duracion.total_seconds() / 3600)

        embed = discord.Embed(
            title="🚀 ¡LA JAM HA COMENZADO!",
            description=f"## 🎯 Tema: **{tema}**",
            color=discord.Color.gold()
        )

        if diversificadores:
            divs = [d.strip() for d in diversificadores.split("|") if d.strip()]
            embed.add_field(
                name="🎲 Diversificadores (opcionales)",
                value="\n".join(f"• {d}" for d in divs),
                inline=False
            )

        embed.add_field(
            name="⏱️ Duración",
            value=f"{horas_totales} horas — hasta el **{fin_dt.strftime('%d/%m/%Y a las %H:%M')}**",
            inline=False
        )

        if config and config.get("itch_jam_url"):
            embed.add_field(
                name="📦 Entrega",
                value=f"Suban su juego en {config['itch_jam_url']}\nLuego peguen el link en el canal de entregas.",
                inline=False
            )

        embed.set_footer(text="¡Buena suerte a todos los equipos! 🎮")

        # Menciones a todos los líderes
        menciones = " ".join(f"<@{l[0]}>" for l in lideres) if lideres else ""

        if canal:
            await canal.send(content=menciones, embed=embed)
            await interaction.response.send_message(
                f"✅ Jam arrancada y anunciada en {canal.mention}", ephemeral=True
            )
        else:
            await interaction.response.send_message(embed=embed)

    # ── DETECCIÓN AUTOMÁTICA DE ENTREGAS ────────────────────────────────────

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Detecta links de itch.io en el canal de entregas."""
        if message.author.bot or not message.guild:
            return

        guild_id = str(message.guild.id)
        config = await self._get_config(guild_id)

        if not config or not config.get("canal_entregas_id"):
            return
        if str(message.channel.id) != config["canal_entregas_id"]:
            return
        if config["estado"] not in ["activa", "votacion"]:
            return

        # Buscar link de itch.io en el mensaje
        import re
        urls = re.findall(r'https?://[^\s]+itch\.io[^\s]*', message.content)
        if not urls:
            return

        url = urls[0]
        user_id = str(message.author.id)

        async with await get_db() as db:
            # Encontrar equipo del usuario
            async with db.execute(
                """SELECT je.id, je.nombre FROM jam_equipos je
                   JOIN jam_integrantes ji ON ji.equipo_id = je.id
                   WHERE ji.user_id=? AND je.guild_id=?""",
                (user_id, guild_id)
            ) as cur:
                equipo = await cur.fetchone()

            if not equipo:
                await message.reply(
                    "⚠️ No encontré tu equipo registrado. ¿Ya usaste `/jam_registrar`?",
                    delete_after=15
                )
                return

            equipo_id, equipo_nombre = equipo

            # Registrar entrega
            await db.execute(
                "UPDATE jam_equipos SET juego_url=?, entregado_en=datetime('now') WHERE id=?",
                (url, equipo_id)
            )
            await db.commit()

        embed = discord.Embed(
            title="📦 ¡Entrega registrada!",
            description=f"**{equipo_nombre}** entregó su juego",
            color=discord.Color.green()
        )
        embed.add_field(name="🔗 Link", value=url)
        embed.add_field(name="⏰ Timestamp", value=datetime.now().strftime("%d/%m/%Y %H:%M"))
        await message.reply(embed=embed)

    # ── RECORDATORIOS AUTOMÁTICOS DE DEADLINE ───────────────────────────────

    @tasks.loop(minutes=30)
    async def recordatorios_jam(self):
        """Revisa cada 30 min si hay que enviar recordatorio de deadline."""
        for guild in self.bot.guilds:
            guild_id = str(guild.id)
            config = await self._get_config(guild_id)

            if not config or config["estado"] != "activa" or not config.get("fin"):
                continue

            fin_dt = datetime.fromisoformat(config["fin"])
            ahora = datetime.now()
            delta_h = (fin_dt - ahora).total_seconds() / 3600

            umbrales = [("24h", 23.5, 24.5), ("6h", 5.75, 6.25), ("1h", 0.75, 1.25)]

            for tipo, min_h, max_h in umbrales:
                if not (min_h <= delta_h <= max_h):
                    continue

                async with await get_db() as db:
                    async with db.execute(
                        "SELECT 1 FROM jam_recordatorios WHERE guild_id=? AND tipo=?",
                        (guild_id, tipo)
                    ) as cur:
                        ya_enviado = await cur.fetchone()

                    if ya_enviado:
                        continue

                    await db.execute(
                        "INSERT OR IGNORE INTO jam_recordatorios (guild_id, tipo) VALUES (?,?)",
                        (guild_id, tipo)
                    )

                    # Obtener equipos sin entrega aún
                    async with db.execute(
                        "SELECT lider_id, nombre FROM jam_equipos WHERE guild_id=? AND juego_url IS NULL",
                        (guild_id,)
                    ) as cur:
                        sin_entregar = await cur.fetchall()

                    await db.commit()

                canal_id = config.get("canal_jam_id")
                canal = guild.get_channel(int(canal_id)) if canal_id else None
                if not canal:
                    continue

                horas_str = tipo.replace("h", " hora(s)")
                menciones = " ".join(f"<@{l[0]}>" for l in sin_entregar)

                embed = discord.Embed(
                    title=f"⏰ ¡Faltan {horas_str} para el cierre!",
                    description=f"El deadline es el **{fin_dt.strftime('%d/%m/%Y a las %H:%M')}**",
                    color=discord.Color.red() if tipo == "1h" else discord.Color.orange()
                )

                if sin_entregar:
                    embed.add_field(
                        name=f"⚠️ {len(sin_entregar)} equipo(s) sin entregar",
                        value="\n".join(f"• {n}" for _, n in sin_entregar),
                        inline=False
                    )
                    if config.get("itch_jam_url"):
                        embed.add_field(
                            name="📦 Entrega aquí",
                            value=config["itch_jam_url"],
                            inline=False
                        )

                await canal.send(content=menciones if menciones else None, embed=embed)

    @recordatorios_jam.before_loop
    async def before_jam_loop(self):
        await self.bot.wait_until_ready()

    # ── VOTACIONES ───────────────────────────────────────────────────────────

    @app_commands.command(name="jam_votacion_abrir", description="Abre la votación para una categoría de premiación")
    @app_commands.describe(categoria="Nombre de la categoría a abrir")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def jam_votacion_abrir(
        self,
        interaction: discord.Interaction,
        categoria: str,
    ):
        guild_id = str(interaction.guild_id)
        config = await self._get_config(guild_id)

        if not config:
            await interaction.response.send_message("❌ La jam no está configurada.", ephemeral=True)
            return

        async with await get_db() as db:
            # Buscar categoría (búsqueda flexible)
            async with db.execute(
                "SELECT id, nombre, descripcion FROM jam_categorias WHERE guild_id=? AND nombre LIKE ?",
                (guild_id, f"%{categoria}%")
            ) as cur:
                cat = await cur.fetchone()

            if not cat:
                async with db.execute(
                    "SELECT nombre FROM jam_categorias WHERE guild_id=?", (guild_id,)
                ) as cur:
                    todas = await cur.fetchall()
                lista = "\n".join(f"• {n[0]}" for n in todas)
                await interaction.response.send_message(
                    f"❌ Categoría no encontrada. Categorías disponibles:\n{lista}",
                    ephemeral=True
                )
                return

            cat_id, cat_nombre, cat_desc = cat

            # Obtener equipos que entregaron
            async with db.execute(
                "SELECT id, nombre FROM jam_equipos WHERE guild_id=? AND juego_url IS NOT NULL ORDER BY nombre",
                (guild_id,)
            ) as cur:
                equipos = await cur.fetchall()

            if not equipos:
                await interaction.response.send_message(
                    "❌ No hay equipos con entregas registradas aún.", ephemeral=True
                )
                return

            await db.execute(
                "UPDATE jam_categorias SET estado='abierta' WHERE id=?", (cat_id,)
            )
            await db.commit()

        canal_id = config.get("canal_votos_id")
        canal = interaction.guild.get_channel(int(canal_id)) if canal_id else interaction.channel

        embed = discord.Embed(
            title=f"🗳️ Votación abierta — {cat_nombre}",
            description=cat_desc or "Vota por el mejor juego en esta categoría.",
            color=discord.Color.gold()
        )
        embed.add_field(
            name="ℹ️ Reglas",
            value="• Un voto por persona\n• No puedes votar por tu propio equipo\n• Puedes cambiar tu voto mientras la votación esté abierta",
            inline=False
        )
        embed.set_footer(text="Un admin cerrará la votación con /jam_votacion_cerrar")

        view = VotacionView(cat_id, equipos)
        msg = await canal.send(embed=embed, view=view)

        async with await get_db() as db:
            await db.execute(
                "UPDATE jam_categorias SET mensaje_id=? WHERE id=?",
                (str(msg.id), cat_id)
            )
            await db.commit()

        # Actualizar estado general de la jam a "votacion"
        async with await get_db() as db:
            await db.execute(
                "UPDATE jam_config SET estado='votacion' WHERE guild_id=?", (guild_id,)
            )
            await db.commit()

        await interaction.response.send_message(
            f"✅ Votación abierta en {canal.mention}", ephemeral=True
        )

    @app_commands.command(name="jam_votacion_cerrar", description="Cierra la votación de una categoría y muestra los resultados")
    @app_commands.describe(categoria="Nombre de la categoría a cerrar")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def jam_votacion_cerrar(
        self,
        interaction: discord.Interaction,
        categoria: str,
    ):
        guild_id = str(interaction.guild_id)

        async with await get_db() as db:
            async with db.execute(
                "SELECT id, nombre FROM jam_categorias WHERE guild_id=? AND nombre LIKE ?",
                (guild_id, f"%{categoria}%")
            ) as cur:
                cat = await cur.fetchone()

            if not cat:
                await interaction.response.send_message("❌ Categoría no encontrada.", ephemeral=True)
                return

            cat_id, cat_nombre = cat

            await db.execute(
                "UPDATE jam_categorias SET estado='cerrada' WHERE id=?", (cat_id,)
            )

            # Contar votos
            async with db.execute(
                """SELECT je.nombre, je.juego_url, COUNT(jv.user_id) as votos
                   FROM jam_votos jv
                   JOIN jam_equipos je ON je.id = jv.equipo_id
                   WHERE jv.categoria_id=?
                   GROUP BY jv.equipo_id
                   ORDER BY votos DESC""",
                (cat_id,)
            ) as cur:
                resultados = await cur.fetchall()

            await db.commit()

        embed = discord.Embed(
            title=f"🏁 Resultados — {cat_nombre}",
            color=discord.Color.gold()
        )

        if not resultados:
            embed.description = "No se registraron votos en esta categoría."
        else:
            medallas = ["🥇", "🥈", "🥉"]
            for i, (nombre, url, votos) in enumerate(resultados):
                medalla = medallas[i] if i < 3 else f"#{i+1}"
                link = f"[{nombre}]({url})" if url else nombre
                embed.add_field(
                    name=f"{medalla} {link}",
                    value=f"{votos} voto(s)",
                    inline=False
                )

        config = await self._get_config(guild_id)
        canal_id = config.get("canal_votos_id") if config else None
        canal = interaction.guild.get_channel(int(canal_id)) if canal_id else interaction.channel

        await canal.send(embed=embed)
        await interaction.response.send_message(
            f"✅ Votación cerrada. Resultados publicados en {canal.mention}", ephemeral=True
        )

    # ── RESULTADOS FINALES ───────────────────────────────────────────────────

    @app_commands.command(name="jam_resultados", description="Muestra el resumen final de todos los ganadores de la jam")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def jam_resultados(self, interaction: discord.Interaction):
        guild_id = str(interaction.guild_id)

        async with await get_db() as db:
            async with db.execute(
                "SELECT id, nombre FROM jam_categorias WHERE guild_id=? AND estado='cerrada'",
                (guild_id,)
            ) as cur:
                categorias = await cur.fetchall()

            async with db.execute(
                "SELECT COUNT(*) FROM jam_equipos WHERE guild_id=?", (guild_id,)
            ) as cur:
                total_equipos = (await cur.fetchone())[0]

            async with db.execute(
                "SELECT COUNT(*) FROM jam_equipos WHERE guild_id=? AND juego_url IS NOT NULL",
                (guild_id,)
            ) as cur:
                total_entregas = (await cur.fetchone())[0]

        config = await self._get_config(guild_id)

        embed = discord.Embed(
            title=f"🏆 Resultados Finales — {config['nombre'] if config else '4D4H'}",
            description=f"**{total_entregas}/{total_equipos}** equipos entregaron su juego",
            color=discord.Color.gold()
        )

        for cat_id, cat_nombre in categorias:
            async with await get_db() as db:
                async with db.execute(
                    """SELECT je.nombre, COUNT(jv.user_id) as votos
                       FROM jam_votos jv
                       JOIN jam_equipos je ON je.id = jv.equipo_id
                       WHERE jv.categoria_id=?
                       GROUP BY jv.equipo_id
                       ORDER BY votos DESC LIMIT 1""",
                    (cat_id,)
                ) as cur:
                    ganador = await cur.fetchone()

            if ganador:
                embed.add_field(
                    name=cat_nombre,
                    value=f"🥇 **{ganador[0]}** ({ganador[1]} votos)",
                    inline=False
                )

        embed.set_footer(text="¡Gracias a todos los participantes! 🎮 GDD — UNAL Bogotá")
        await interaction.response.send_message(embed=embed)

    # ── ESTADO GENERAL ───────────────────────────────────────────────────────

    @app_commands.command(name="jam_estado", description="Muestra el estado actual de la jam: equipos, entregas y tiempo restante")
    async def jam_estado(self, interaction: discord.Interaction):
        guild_id = str(interaction.guild_id)
        config = await self._get_config(guild_id)

        if not config:
            await interaction.response.send_message(
                "❌ La jam no está configurada aún.", ephemeral=True
            )
            return

        async with await get_db() as db:
            async with db.execute(
                "SELECT id, nombre, juego_url FROM jam_equipos WHERE guild_id=? ORDER BY id",
                (guild_id,)
            ) as cur:
                equipos = await cur.fetchall()

            async with db.execute(
                "SELECT nombre FROM jam_diversificadores WHERE guild_id=?", (guild_id,)
            ) as cur:
                divs = await cur.fetchall()

        embed = discord.Embed(
            title=f"🎮 {config['nombre']} — Estado actual",
            color=discord.Color.blurple()
        )
        embed.add_field(name="📊 Estado", value=config["estado"].capitalize(), inline=True)
        embed.add_field(name="👥 Equipos", value=str(len(equipos)), inline=True)
        entregas = sum(1 for e in equipos if e[2])
        embed.add_field(name="📦 Entregas", value=f"{entregas}/{len(equipos)}", inline=True)

        if config.get("tema"):
            embed.add_field(name="🎯 Tema", value=config["tema"], inline=False)

        if divs:
            embed.add_field(
                name="🎲 Diversificadores",
                value="\n".join(f"• {d[0]}" for d in divs),
                inline=False
            )

        if config.get("fin") and config["estado"] == "activa":
            fin_dt = datetime.fromisoformat(config["fin"])
            delta = fin_dt - datetime.now()
            if delta.total_seconds() > 0:
                horas = int(delta.total_seconds() // 3600)
                minutos = int((delta.total_seconds() % 3600) // 60)
                embed.add_field(
                    name="⏱️ Tiempo restante",
                    value=f"**{horas}h {minutos}m** (cierre: {fin_dt.strftime('%d/%m/%Y %H:%M')})",
                    inline=False
                )
            else:
                embed.add_field(name="⏱️ Tiempo", value="⚠️ ¡El tiempo de entrega ha vencido!", inline=False)

        if equipos:
            lista = "\n".join(
                f"{'✅' if e[2] else '⏳'} **{e[1]}**" for e in equipos
            )
            embed.add_field(name="📋 Equipos registrados", value=lista, inline=False)

        await interaction.response.send_message(embed=embed)


async def setup(bot):
    await bot.add_cog(Jam(bot))
