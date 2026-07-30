import discord
from discord import app_commands
from discord.ext import commands, tasks
from datetime import datetime, date, timedelta
from database import get_db

# Canal donde se postean los resúmenes diarios (configurable por servidor)
# Si no está seteado, los recordatorios van solo por DM al responsable
CANAL_RECORDATORIOS_KEY = "canal_recordatorios"

# Cuántos días antes avisar (y el tipo para el log de duplicados)
UMBRALES = [
    (7,  "7d",      "📅 Faltan 7 días"),
    (3,  "3d",      "⚠️ Faltan 3 días"),
    (1,  "1d",      "🚨 ¡Mañana vence!"),
    (0,  "vencida", "🔴 ¡VENCIDA HOY!"),
]


class Recordatorios(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._config: dict[str, dict] = {}  # guild_id → {canal_id, ...}
        self.check_deadlines.start()

    def cog_unload(self):
        self.check_deadlines.cancel()

    # ─────────────────────────────────────────────
    #  Loop principal — corre cada día a las 9am
    #  (en Railway corre con timezone UTC; 9am Bogotá = UTC-5 = 14:00 UTC)
    # ─────────────────────────────────────────────
    @tasks.loop(hours=24)
    async def check_deadlines(self):
        hoy = date.today()

        async with await get_db() as db:
            # Tareas activas con deadline, no completadas
            async with db.execute(
                """SELECT id, nombre, area, responsable, deadline, estado, guild_id
                   FROM tareas
                   WHERE deadline IS NOT NULL
                     AND estado NOT IN ('completada')
                   ORDER BY deadline ASC"""
            ) as cur:
                tareas = await cur.fetchall()

            for tarea in tareas:
                tid, nombre, area, resp_id, deadline_str, estado, guild_id = tarea

                try:
                    deadline_dt = date.fromisoformat(deadline_str)
                except ValueError:
                    continue

                dias_restantes = (deadline_dt - hoy).days

                # Determinar qué tipo de recordatorio aplica hoy
                tipo_hoy = None
                etiqueta_hoy = None
                for dias, tipo, etiqueta in UMBRALES:
                    if dias_restantes == dias:
                        tipo_hoy = tipo
                        etiqueta_hoy = etiqueta
                        break

                if not tipo_hoy:
                    continue  # No le toca recordatorio hoy

                # Verificar si ya enviamos este recordatorio
                async with db.execute(
                    "SELECT 1 FROM recordatorios_enviados WHERE tarea_id=? AND tipo=?",
                    (tid, tipo_hoy)
                ) as cur:
                    ya_enviado = await cur.fetchone()

                if ya_enviado:
                    continue

                # Marcar como enviado ANTES de intentar enviar (evita reintentos duplicados)
                await db.execute(
                    "INSERT OR IGNORE INTO recordatorios_enviados (tarea_id, tipo) VALUES (?,?)",
                    (tid, tipo_hoy)
                )
                await db.commit()

                # Construir embed
                color = {
                    "7d":      discord.Color.blue(),
                    "3d":      discord.Color.orange(),
                    "1d":      discord.Color.red(),
                    "vencida": discord.Color.dark_red(),
                }[tipo_hoy]

                embed = discord.Embed(
                    title=f"{etiqueta_hoy} — Tarea #{tid}",
                    description=f"**{nombre}**",
                    color=color
                )
                embed.add_field(name="🏷️ Área", value=area, inline=True)
                embed.add_field(name="📅 Deadline", value=deadline_str, inline=True)
                embed.add_field(name="🔖 Estado", value=estado, inline=True)

                # 1) DM al responsable
                guild = self.bot.get_guild(int(guild_id))
                if guild and resp_id and resp_id != "sin_asignar":
                    try:
                        miembro = guild.get_member(int(resp_id))
                        if miembro:
                            await miembro.send(
                                f"⏰ **Recordatorio de tarea en GDD**",
                                embed=embed
                            )
                    except (discord.Forbidden, ValueError):
                        pass

                # 2) Canal de recordatorios del servidor (si está configurado)
                canal_id = self._config.get(guild_id, {}).get("canal_id")
                if guild and canal_id:
                    canal = guild.get_channel(int(canal_id))
                    if canal:
                        # Mencionar al responsable en el canal
                        mencion = f"<@{resp_id}>" if resp_id and resp_id != "sin_asignar" else "⚠️ Sin responsable asignado"
                        await canal.send(content=mencion, embed=embed)

    @check_deadlines.before_loop
    async def before_check(self):
        await self.bot.wait_until_ready()
        # Esperar hasta las 14:00 UTC (9am Bogotá) para el primer disparo
        ahora = datetime.utcnow()
        objetivo = ahora.replace(hour=14, minute=0, second=0, microsecond=0)
        if ahora >= objetivo:
            objetivo += timedelta(days=1)
        espera = (objetivo - ahora).total_seconds()
        print(f"⏰ Recordatorios: primer check en {espera/3600:.1f}h (14:00 UTC)")
        import asyncio
        await asyncio.sleep(espera)

    # ─────────────────────────────────────────────
    #  /recordatorios_canal — configurar canal del servidor
    # ─────────────────────────────────────────────
    @app_commands.command(
        name="recordatorios_canal",
        description="Configura el canal donde el bot postea recordatorios de deadlines"
    )
    @app_commands.describe(canal="Canal de texto para los recordatorios")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def recordatorios_canal(
        self,
        interaction: discord.Interaction,
        canal: discord.TextChannel,
    ):
        guild_id = str(interaction.guild_id)
        if guild_id not in self._config:
            self._config[guild_id] = {}
        self._config[guild_id]["canal_id"] = str(canal.id)

        await interaction.response.send_message(
            f"✅ Canal de recordatorios configurado: {canal.mention}\n"
            f"Los avisos de deadlines aparecerán ahí diariamente a las 9am (Bogotá).",
            ephemeral=True
        )

    # ─────────────────────────────────────────────
    #  /recordatorios_ver — resumen manual inmediato
    # ─────────────────────────────────────────────
    @app_commands.command(
        name="recordatorios_ver",
        description="Ver todas las tareas con deadline en los próximos 14 días"
    )
    async def recordatorios_ver(self, interaction: discord.Interaction):
        hoy = date.today()
        limite = hoy + timedelta(days=14)

        async with await get_db() as db:
            async with db.execute(
                """SELECT id, nombre, area, responsable, deadline, estado
                   FROM tareas
                   WHERE deadline IS NOT NULL
                     AND estado NOT IN ('completada')
                     AND guild_id = ?
                   ORDER BY deadline ASC""",
                (str(interaction.guild_id),)
            ) as cur:
                tareas = await cur.fetchall()

        proximas = []
        vencidas = []
        for t in tareas:
            tid, nombre, area, resp_id, deadline_str, estado = t
            try:
                dl = date.fromisoformat(deadline_str)
            except ValueError:
                continue
            dias = (dl - hoy).days
            if dias < 0:
                vencidas.append((tid, nombre, area, resp_id, deadline_str, estado, dias))
            elif dias <= 14:
                proximas.append((tid, nombre, area, resp_id, deadline_str, estado, dias))

        if not proximas and not vencidas:
            await interaction.response.send_message(
                "✅ No hay tareas con deadline en los próximos 14 días.", ephemeral=True
            )
            return

        embed = discord.Embed(
            title="📅 Deadlines próximos — GDD",
            color=discord.Color.orange()
        )

        if vencidas:
            lineas = []
            for tid, nombre, area, resp_id, dl, estado, dias in vencidas:
                try:
                    miembro = interaction.guild.get_member(int(resp_id))
                    resp = miembro.display_name if miembro else "Sin asignar"
                except:
                    resp = "Sin asignar"
                lineas.append(f"🔴 **#{tid} {nombre}** ({area})\n   👤 {resp} | venció hace {abs(dias)}d")
            embed.add_field(name="🔴 Vencidas", value="\n".join(lineas), inline=False)

        if proximas:
            lineas = []
            for tid, nombre, area, resp_id, dl, estado, dias in proximas:
                try:
                    miembro = interaction.guild.get_member(int(resp_id))
                    resp = miembro.display_name if miembro else "Sin asignar"
                except:
                    resp = "Sin asignar"
                emoji = "🚨" if dias <= 1 else ("⚠️" if dias <= 3 else "📅")
                lineas.append(f"{emoji} **#{tid} {nombre}** ({area})\n   👤 {resp} | {dl} ({dias}d)")
            embed.add_field(name="⏳ Próximas", value="\n".join(lineas), inline=False)

        embed.set_footer(text=f"Hoy: {hoy.isoformat()}")
        await interaction.response.send_message(embed=embed)


async def setup(bot):
    await bot.add_cog(Recordatorios(bot))
