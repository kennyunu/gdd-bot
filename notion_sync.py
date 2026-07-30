"""
notion_sync.py — Puente Discord → Notion para GDD Bot
======================================================
Cada vez que se crea/actualiza una tarea, flujo o evento en Discord,
este módulo escribe/actualiza la página correspondiente en Notion.

Requiere 3 variables de entorno:
  NOTION_TOKEN        — Integration secret (empieza con "secret_...")
  NOTION_DB_TAREAS    — ID de la base de datos de Tareas en Notion
  NOTION_DB_EVENTOS   — ID de la base de datos de Eventos en Notion

Cómo obtener los IDs:
  Abre la BD en Notion → copia la URL → el ID es la parte después del último /
  Ejemplo: https://notion.so/workspace/abc123def456...  → "abc123def456..."
"""

import os
import logging
from datetime import date
from notion_client import AsyncClient
from notion_client.errors import APIResponseError

log = logging.getLogger("gdd.notion")

# ─── Colores por área (Notion color names) ───────────────────────────────────
AREA_COLOR = {
    "Logística":           "blue",
    "Comunicaciones":      "purple",
    "Pedagogía":           "green",
    "Relaciones Externas": "orange",
    "Tesorería":           "yellow",
}

ESTADO_COLOR = {
    "pendiente":   "gray",
    "en_progreso": "blue",
    "completada":  "green",
    "bloqueada":   "red",
}


def _get_client() -> AsyncClient | None:
    token = os.environ.get("NOTION_TOKEN")
    if not token:
        log.warning("NOTION_TOKEN no configurado — sync desactivado")
        return None
    return AsyncClient(auth=token)


def _db_tareas() -> str | None:
    return os.environ.get("NOTION_DB_TAREAS")


def _db_eventos() -> str | None:
    return os.environ.get("NOTION_DB_EVENTOS")


# ─── TAREAS ──────────────────────────────────────────────────────────────────

async def crear_tarea_notion(
    tarea_id: int,
    nombre: str,
    area: str,
    responsable_nombre: str,
    estado: str,
    deadline: str | None = None,
    descripcion: str | None = None,
    flujo_nombre: str | None = None,
) -> str | None:
    """
    Crea una página nueva en la BD de Tareas de Notion.
    Devuelve el page_id de Notion para guardarlo en SQLite.
    """
    client = _get_client()
    db_id = _db_tareas()
    if not client or not db_id:
        return None

    properties: dict = {
        "Nombre": {
            "title": [{"text": {"content": f"#{tarea_id} — {nombre}"}}]
        },
        "Área": {
            "select": {"name": area, "color": AREA_COLOR.get(area, "default")}
        },
        "Responsable": {
            "rich_text": [{"text": {"content": responsable_nombre}}]
        },
        "Estado": {
            "select": {"name": estado.replace("_", " ").capitalize(),
                       "color": ESTADO_COLOR.get(estado, "default")}
        },
        "ID Discord": {
            "number": tarea_id
        },
    }

    if deadline:
        properties["Deadline"] = {"date": {"start": deadline}}

    if flujo_nombre:
        properties["Flujo"] = {
            "rich_text": [{"text": {"content": flujo_nombre}}]
        }

    children = []
    if descripcion:
        children.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [{"type": "text", "text": {"content": descripcion}}]
            }
        })

    try:
        resp = await client.pages.create(
            parent={"database_id": db_id},
            properties=properties,
            children=children if children else [],
        )
        page_id = resp["id"]
        log.info(f"Notion: tarea #{tarea_id} creada → {page_id}")
        return page_id
    except APIResponseError as e:
        log.error(f"Notion API error al crear tarea #{tarea_id}: {e}")
        return None


async def actualizar_estado_notion(page_id: str, nuevo_estado: str) -> bool:
    """Actualiza solo el campo Estado de una página de tarea existente."""
    client = _get_client()
    if not client or not page_id:
        return False

    try:
        await client.pages.update(
            page_id=page_id,
            properties={
                "Estado": {
                    "select": {
                        "name": nuevo_estado.replace("_", " ").capitalize(),
                        "color": ESTADO_COLOR.get(nuevo_estado, "default"),
                    }
                }
            }
        )
        log.info(f"Notion: página {page_id} → estado '{nuevo_estado}'")
        return True
    except APIResponseError as e:
        log.error(f"Notion API error al actualizar {page_id}: {e}")
        return False


async def actualizar_tarea_notion(
    page_id: str,
    responsable_nombre: str | None = None,
    deadline: str | None = None,
    estado: str | None = None,
) -> bool:
    """Actualiza responsable, deadline y/o estado de una tarea en Notion."""
    client = _get_client()
    if not client or not page_id:
        return False

    properties: dict = {}
    if responsable_nombre:
        properties["Responsable"] = {
            "rich_text": [{"text": {"content": responsable_nombre}}]
        }
    if deadline:
        properties["Deadline"] = {"date": {"start": deadline}}
    if estado:
        properties["Estado"] = {
            "select": {
                "name": estado.replace("_", " ").capitalize(),
                "color": ESTADO_COLOR.get(estado, "default"),
            }
        }

    if not properties:
        return False

    try:
        await client.pages.update(page_id=page_id, properties=properties)
        log.info(f"Notion: página {page_id} actualizada")
        return True
    except APIResponseError as e:
        log.error(f"Notion API error al actualizar {page_id}: {e}")
        return False


# ─── EVENTOS ─────────────────────────────────────────────────────────────────

async def crear_evento_notion(
    evento_id: int,
    nombre: str,
    fecha: str,
    lugar: str | None = None,
    descripcion: str | None = None,
) -> str | None:
    """Crea una página en la BD de Eventos de Notion."""
    client = _get_client()
    db_id = _db_eventos()
    if not client or not db_id:
        return None

    # Notion espera fecha en formato YYYY-MM-DD o YYYY-MM-DDTHH:MM:SS
    fecha_notion = fecha[:10] if len(fecha) >= 10 else fecha

    properties: dict = {
        "Nombre": {
            "title": [{"text": {"content": nombre}}]
        },
        "Fecha": {
            "date": {"start": fecha_notion}
        },
        "ID Discord": {
            "number": evento_id
        },
    }

    if lugar:
        properties["Lugar"] = {
            "rich_text": [{"text": {"content": lugar}}]
        }

    children = []
    if descripcion:
        children.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [{"type": "text", "text": {"content": descripcion}}]
            }
        })

    try:
        resp = await client.pages.create(
            parent={"database_id": db_id},
            properties=properties,
            children=children if children else [],
        )
        page_id = resp["id"]
        log.info(f"Notion: evento #{evento_id} creado → {page_id}")
        return page_id
    except APIResponseError as e:
        log.error(f"Notion API error al crear evento #{evento_id}: {e}")
        return None


async def actualizar_asistencia_notion(page_id: str, van: int, no_van: int, tal_vez: int) -> bool:
    """Actualiza el conteo de RSVP de un evento en Notion."""
    client = _get_client()
    if not client or not page_id:
        return False

    try:
        await client.pages.update(
            page_id=page_id,
            properties={
                "Confirmados": {"number": van},
                "No pueden":   {"number": no_van},
                "Tal vez":     {"number": tal_vez},
            }
        )
        return True
    except APIResponseError as e:
        log.error(f"Notion API error al actualizar RSVP {page_id}: {e}")
        return False


# ─── FLUJOS ──────────────────────────────────────────────────────────────────

async def crear_flujo_notion(
    flujo_id: int,
    nombre: str,
    area: str,
    pasos: list[str],
) -> str | None:
    """
    Crea una página de flujo en la BD de Tareas con los pasos como checklist.
    Usa la misma BD de Tareas, con el campo Flujo = nombre del flujo padre.
    """
    client = _get_client()
    db_id = _db_tareas()
    if not client or not db_id:
        return None

    properties = {
        "Nombre": {
            "title": [{"text": {"content": f"🔄 Flujo #{flujo_id} — {nombre}"}}]
        },
        "Área": {
            "select": {"name": area, "color": AREA_COLOR.get(area, "default")}
        },
        "Estado": {
            "select": {"name": "En progreso", "color": "blue"}
        },
        "Flujo": {
            "rich_text": [{"text": {"content": "Página raíz del flujo"}}]
        },
    }

    # Los pasos como to-do checklist en el cuerpo de la página
    children = [
        {
            "object": "block",
            "type": "heading_2",
            "heading_2": {
                "rich_text": [{"type": "text", "text": {"content": "Pasos del flujo"}}]
            }
        }
    ] + [
        {
            "object": "block",
            "type": "to_do",
            "to_do": {
                "rich_text": [{"type": "text", "text": {"content": paso}}],
                "checked": False,
            }
        }
        for paso in pasos
    ]

    try:
        resp = await client.pages.create(
            parent={"database_id": db_id},
            properties=properties,
            children=children,
        )
        page_id = resp["id"]
        log.info(f"Notion: flujo #{flujo_id} creado → {page_id}")
        return page_id
    except APIResponseError as e:
        log.error(f"Notion API error al crear flujo #{flujo_id}: {e}")
        return None


async def check_notion_config() -> dict:
    """
    Verifica que las credenciales de Notion estén bien configuradas.
    Devuelve un dict con el estado de cada componente.
    """
    resultado = {
        "token": bool(os.environ.get("NOTION_TOKEN")),
        "db_tareas": bool(os.environ.get("NOTION_DB_TAREAS")),
        "db_eventos": bool(os.environ.get("NOTION_DB_EVENTOS")),
        "conexion": False,
        "error": None,
    }

    if not resultado["token"]:
        resultado["error"] = "NOTION_TOKEN no configurado"
        return resultado

    client = _get_client()
    try:
        await client.users.me()
        resultado["conexion"] = True
    except APIResponseError as e:
        resultado["error"] = str(e)

    return resultado
