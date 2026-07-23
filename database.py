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
        """)
        await db.commit()
    print(f"🗄️  Base de datos inicializada en {DB_PATH}")

async def get_db():
    return aiosqlite.connect(DB_PATH)
