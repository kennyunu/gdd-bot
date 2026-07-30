import aiosqlite
import os

DB_PATH = os.environ.get("DB_PATH", "data/gdd.db")

async def init_db():
    os.makedirs("data", exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
            -- TAREAS
            CREATE TABLE IF NOT EXISTS tareas (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre      TEXT NOT NULL,
                descripcion TEXT,
                area        TEXT NOT NULL,  -- Logística | Comunicaciones | Pedagogía | Relaciones Externas | Tesorería
                responsable TEXT NOT NULL,  -- @mention o nombre
                deadline    TEXT,           -- ISO date YYYY-MM-DD
                estado      TEXT NOT NULL DEFAULT 'pendiente',  -- pendiente | en_progreso | completada | bloqueada
                flujo_id    INTEGER,        -- FK a flujos.id (si pertenece a un flujo)
                flujo_paso  INTEGER,        -- posición dentro del flujo
                creada_en   TEXT DEFAULT (datetime('now')),
                guild_id    TEXT NOT NULL
            );

            -- DEPENDENCIAS entre tareas
            CREATE TABLE IF NOT EXISTS dependencias (
                tarea_id        INTEGER NOT NULL,
                depende_de_id   INTEGER NOT NULL,
                PRIMARY KEY (tarea_id, depende_de_id),
                FOREIGN KEY (tarea_id) REFERENCES tareas(id),
                FOREIGN KEY (depende_de_id) REFERENCES tareas(id)
            );

            -- FLUJOS del organigrama (secuencias predefinidas de tareas)
            CREATE TABLE IF NOT EXISTS flujos (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre      TEXT NOT NULL,  -- ej: "Organizar charla"
                area        TEXT NOT NULL,
                descripcion TEXT,
                guild_id    TEXT NOT NULL
            );

            -- PASOS de cada flujo (plantilla)
            CREATE TABLE IF NOT EXISTS flujo_pasos (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                flujo_id        INTEGER NOT NULL,
                paso            INTEGER NOT NULL,  -- orden: 1, 2, 3...
                nombre          TEXT NOT NULL,     -- ej: "Conseguir ponente"
                descripcion     TEXT,
                dias_deadline   INTEGER,           -- días desde que se activa el paso
                FOREIGN KEY (flujo_id) REFERENCES flujos(id)
            );

            -- EVENTOS y RSVP
            CREATE TABLE IF NOT EXISTS eventos (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre      TEXT NOT NULL,
                descripcion TEXT,
                fecha       TEXT NOT NULL,         -- ISO datetime
                lugar       TEXT,
                canal_id    TEXT,                  -- canal de Discord donde se anunció
                creado_por  TEXT NOT NULL,
                guild_id    TEXT NOT NULL,
                creado_en   TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS rsvp (
                evento_id   INTEGER NOT NULL,
                user_id     TEXT NOT NULL,
                respuesta   TEXT NOT NULL,  -- voy | no_voy | tal_vez
                timestamp   TEXT DEFAULT (datetime('now')),
                PRIMARY KEY (evento_id, user_id),
                FOREIGN KEY (evento_id) REFERENCES eventos(id)
            );

            -- ── FASE 5: 4D4H GAME JAM ────────────────────────────────────

            -- Configuración de la jam activa
            CREATE TABLE IF NOT EXISTS jam_config (
                guild_id        TEXT PRIMARY KEY,
                nombre          TEXT DEFAULT '4D4H Game Jam',
                estado          TEXT DEFAULT 'inactiva', -- inactiva | registros | activa | votacion | cerrada
                tema            TEXT,
                inicio          TEXT,   -- ISO datetime arranque oficial
                fin             TEXT,   -- ISO datetime cierre de entregas
                canal_jam_id    TEXT,   -- canal principal de la jam
                canal_entregas_id TEXT, -- canal donde se detectan links itch.io
                canal_votos_id  TEXT,   -- canal de votaciones
                itch_jam_url    TEXT    -- URL de la jam en itch.io
            );

            -- Diversificadores de la jam
            CREATE TABLE IF NOT EXISTS jam_diversificadores (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id    TEXT NOT NULL,
                nombre      TEXT NOT NULL,
                descripcion TEXT
            );

            -- Equipos registrados
            CREATE TABLE IF NOT EXISTS jam_equipos (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id    TEXT NOT NULL,
                nombre      TEXT NOT NULL,
                engine      TEXT,
                lider_id    TEXT NOT NULL,  -- user_id del líder
                creado_en   TEXT DEFAULT (datetime('now')),
                juego_url   TEXT,           -- link itch.io de entrega
                entregado_en TEXT           -- timestamp de entrega
            );

            -- Integrantes de cada equipo
            CREATE TABLE IF NOT EXISTS jam_integrantes (
                equipo_id   INTEGER NOT NULL,
                user_id     TEXT NOT NULL,
                PRIMARY KEY (equipo_id, user_id),
                FOREIGN KEY (equipo_id) REFERENCES jam_equipos(id)
            );

            -- Recordatorios de jam ya enviados
            CREATE TABLE IF NOT EXISTS jam_recordatorios (
                guild_id    TEXT NOT NULL,
                tipo        TEXT NOT NULL,  -- "24h" | "6h" | "1h"
                PRIMARY KEY (guild_id, tipo)
            );

            -- Categorías de votación
            CREATE TABLE IF NOT EXISTS jam_categorias (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id    TEXT NOT NULL,
                nombre      TEXT NOT NULL,
                descripcion TEXT,
                estado      TEXT DEFAULT 'cerrada',  -- cerrada | abierta
                mensaje_id  TEXT   -- ID del mensaje con botones de voto
            );

            -- Votos por categoría
            CREATE TABLE IF NOT EXISTS jam_votos (
                categoria_id    INTEGER NOT NULL,
                user_id         TEXT NOT NULL,
                equipo_id       INTEGER NOT NULL,
                PRIMARY KEY (categoria_id, user_id),
                FOREIGN KEY (categoria_id) REFERENCES jam_categorias(id),
                FOREIGN KEY (equipo_id) REFERENCES jam_equipos(id)
            );

            CREATE TABLE IF NOT EXISTS notion_pages (
                entidad_tipo  TEXT NOT NULL,  -- "tarea" | "evento" | "flujo"
                entidad_id    INTEGER NOT NULL,
                page_id       TEXT NOT NULL,
                PRIMARY KEY (entidad_tipo, entidad_id)
            );

            -- REGISTRO de recordatorios ya enviados (evita duplicados)
            CREATE TABLE IF NOT EXISTS recordatorios_enviados (
                tarea_id    INTEGER NOT NULL,
                tipo        TEXT NOT NULL,  -- "7d" | "3d" | "1d" | "vencida"
                enviado_en  TEXT DEFAULT (datetime('now')),
                PRIMARY KEY (tarea_id, tipo)
            );

            -- REUNIONES: sesiones de agendamiento colectivo
            CREATE TABLE IF NOT EXISTS reuniones (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                titulo          TEXT NOT NULL,
                descripcion     TEXT,
                duracion_min    INTEGER DEFAULT 60,
                creado_por      TEXT NOT NULL,
                canal_id        TEXT NOT NULL,
                mensaje_id      TEXT,           -- ID del mensaje con los botones
                estado          TEXT DEFAULT 'abierta',  -- abierta | cerrada | confirmada
                fecha_elegida   TEXT,           -- ISO datetime, una vez confirmada
                guild_id        TEXT NOT NULL,
                creado_en       TEXT DEFAULT (datetime('now'))
            );

            -- DISPONIBILIDAD: respuestas de cada miembro a una reunión
            CREATE TABLE IF NOT EXISTS disponibilidad (
                reunion_id  INTEGER NOT NULL,
                user_id     TEXT NOT NULL,
                slot        TEXT NOT NULL,  -- ISO datetime del slot propuesto
                respuesta   TEXT NOT NULL,  -- "puede" | "no_puede" | "tal_vez"
                PRIMARY KEY (reunion_id, user_id, slot),
                FOREIGN KEY (reunion_id) REFERENCES reuniones(id)
            );
        """)
        await db.commit()
    print(f"🗄️  Base de datos inicializada en {DB_PATH}")

async def get_db():
    return aiosqlite.connect(DB_PATH)
