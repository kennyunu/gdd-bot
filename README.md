# 🎮 GDD Bot — Discord Bot de Gamers, Developers & Designers

Bot de Discord para la gestión interna de GDD (UNAL Bogotá). Maneja tareas, flujos del organigrama, eventos y más.

---

## 📦 Stack

- **Python 3.11+** + **discord.py 2.3**
- **SQLite** (aiosqlite) — base de datos local, sin servidor externo
- **Railway** — hosting gratuito, siempre activo, deploy desde GitHub

---

## 🚀 Setup inicial (primera vez)

### 1. Crear el bot en Discord
1. Ve a https://discord.com/developers/applications
2. Clic en **New Application** → ponle nombre (ej: `GDD Bot`)
3. Ve a **Bot** → **Reset Token** → copia el token (solo se ve una vez)
4. En **Bot**, activa: `SERVER MEMBERS INTENT` y `MESSAGE CONTENT INTENT`
5. Ve a **OAuth2 → URL Generator**:
   - Scopes: `bot` + `applications.commands`
   - Bot Permissions: `Send Messages`, `Embed Links`, `Read Message History`, `Manage Messages`, `Use Slash Commands`
6. Copia la URL generada y úsala para invitar el bot a tu servidor

### 2. Configurar localmente
```bash
# Clonar el repo
git clone https://github.com/tu-usuario/gdd-bot.git
cd gdd-bot

# Crear entorno virtual
python -m venv venv
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate     # Windows

# Instalar dependencias
pip install -r requirements.txt

# Configurar variables de entorno
cp .env.example .env
# Edita .env y pega tu DISCORD_TOKEN

# Correr el bot
python main.py
```

### 3. Deploy en Railway (hosting gratuito)
1. Sube el proyecto a GitHub (sin el `.env`)
2. Ve a https://railway.app → **New Project** → **Deploy from GitHub repo**
3. Selecciona tu repo
4. Ve a **Variables** → agrega `DISCORD_TOKEN` con tu token
5. Railway detecta el `Procfile` y lo corre automáticamente
6. El bot queda **siempre activo** con `restartPolicyType = "always"`

---

## 🛠️ Comandos disponibles

### Tareas
| Comando | Descripción |
|---|---|
| `/tarea_crear` | Crea una tarea para un área del organigrama |
| `/tarea_ver` | Ver tareas filtrando por área, persona o estado |
| `/tarea_completar` | Marca como hecha y desbloquea dependientes automáticamente |
| `/tarea_editar` | Cambia responsable, deadline o estado |
| `/tareas_bloqueadas` | Muestra qué tareas están esperando algo |

### Flujos del organigrama
| Comando | Descripción |
|---|---|
| `/flujo_iniciar` | Inicia un flujo predefinido (charla, publicación, compra, etc.) |
| `/flujo_ver` | Ver el estado paso a paso de un flujo activo |

Flujos disponibles:
- 📅 **Organizar Charla** — de conseguir ponente a documentar asistencia
- 📱 **Publicación en Redes** — de solicitud a publicación final
- 💰 **Cotización y Compra** — de solicitud a registro en inventario
- 🎮 **Checkpoint de Proyecto** — GDD doc → Teaser → Pitch → MVP → Shark Tank → Showcase
- 🤝 **Gestionar Alianza Externa** — de identificar contacto a registrar alianza

### Eventos
| Comando | Descripción |
|---|---|
| `/evento_crear` | Crea un evento con botones RSVP (✅ Voy / ❌ No puedo / 🤔 Tal vez) |

Los eventos envían recordatorios automáticos **24 horas antes** y **1 hora antes**, mencionando a quienes confirmaron asistencia.

---

## 🗺️ Roadmap

- **F1 (actual):** MVP — CRUD de tareas, flujos, eventos + RSVP ✅
- **F2:** Recordatorios de deadlines (daily check)
- **F3:** Integración con Notion (sync bidireccional)
- **F4:** Moderación y bienvenida automática
- **F5:** Tooling 4D4H — registro de equipos, votación por categorías, deadline de subida a itch.io

---

## 📁 Estructura del proyecto

```
gdd-bot/
├── main.py           # Entry point del bot
├── database.py       # Schema SQLite e inicialización
├── cogs/
│   ├── tareas.py     # CRUD de tareas + dependencias
│   ├── eventos.py    # Eventos + RSVP + recordatorios automáticos
│   └── flujos.py     # Flujos predefinidos del organigrama
├── requirements.txt
├── railway.toml      # Config de Railway (siempre activo)
├── Procfile
├── .env.example
└── .gitignore
```
