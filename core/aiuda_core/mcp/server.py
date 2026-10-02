"""Servidor MCP sobre stdio: JSON-RPC 2.0, solo herramientas.

POR QUÉ A MANO Y NO CON EL SDK. El SDK oficial (`mcp`) arrastra ocho paquetes que
aiuda no tiene, entre ellos `opentelemetry-api` y `httpx2` (un SEGUNDO cliente HTTP
junto al `httpx` que ya usamos), unos 28 MB de site-packages. aiuda se distribuye como
un binario de PyInstaller que hay que firmar y notarizar, así que cada dependencia
nueva es peso y es riesgo de empaquetado. Un servidor de solo tools necesita cuatro
métodos y ninguna dependencia. Verificado en vivo contra Claude Code 2.1.220, que
negocia `2025-11-25`, lista las tools y las llama.

POR QUÉ NO ACP. ACP exige un adaptador de Node de terceros por cada arnés, y el `.dmg`
no trae Node. Además lo que ACP compra de verdad (`session/request_permission`) es
justo lo que aiuda no necesita: sus herramientas no escriben, así que no hay nada que
aprobar en el momento. La soberanía humana vive en la máquina de estados de la base
(`draft -> pending_approval -> approved -> sent`), fuera del alcance del modelo.

REGLA DURA DEL TRANSPORTE: stdout es SOLO JSON-RPC. Cualquier diagnóstico va a stderr.
Un `print` de más rompe la sesión del cliente.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any, Callable, TextIO

from aiuda_core.aiuditas.chat import CHAT_AIUDITAS, AyudanteChatExecutor
from aiuda_core.models import Ayudante, Tenant

# La revisión que ofrecemos si el cliente no propone ninguna. Si propone una, se le
# devuelve la suya: la negociación de MCP es "el servidor contesta con la que hablará",
# y para un servidor de solo tools todas las revisiones vigentes son equivalentes.
VERSION_POR_DEFECTO = "2025-06-18"

# JSON-RPC 2.0
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


def herramientas_de(aiudita_ids) -> list[dict]:
    """Las tools MCP de un ayudante: sus aiuditas activas que son de chat (lectura).

    Se derivan de CHAT_AIUDITAS, que ya es la lista de "aiuditas de solo lectura con
    ejecutor real". No hay un catálogo paralelo que se pueda desincronizar, que es
    exactamente el bug que aiuda ya pagó en la capa de integraciones.
    """
    tools = []
    for aid in aiudita_ids:
        entry = CHAT_AIUDITAS.get(aid)
        if entry is None:
            continue
        schema, _ = entry
        tools.append(
            {
                "name": schema["name"],
                "description": schema.get("description", ""),
                "inputSchema": schema.get("input_schema") or schema.get("inputSchema") or {
                    "type": "object",
                    "properties": {},
                },
                # Todas son de lectura: aquí no existe ninguna que escriba ni que envíe.
                # Es una pista para el cliente, no la garantía: la garantía es que la
                # tool de envío no está en este servidor.
                "annotations": {"readOnlyHint": True, "destructiveHint": False},
            }
        )
    return tools


class Sesion:
    """El alcance de UNA corrida del servidor: un negocio, un ayudante, un interlocutor.

    El alcance viaja por variables de entorno del subproceso, NUNCA por argv, porque
    argv se ve en `ps` y ahí iría el token. Y el servidor no acepta `tenant_id` como
    argumento de tool: se ata al del proceso. Es el mismo cierre que ya hace
    CleoToolExecutor con caller_phone.
    """

    def __init__(self, session, tenant: Tenant, ayudante: Ayudante | None, caller_phone=None):
        self.session = session
        self.tenant = tenant
        self.ayudante = ayudante
        self.caller_phone = caller_phone
        activas = list((ayudante.aiuditas or {}).keys()) if ayudante is not None else []
        # Doble reja: lo que se LISTA y lo que se puede LLAMAR salen de la misma lista.
        self.tools = herramientas_de(activas)
        self._nombres = {t["name"] for t in self.tools}
        self._exec = AyudanteChatExecutor(session, tenant, activas, caller_phone=caller_phone)

    def llamar(self, nombre: str, args: dict) -> str:
        if nombre not in self._nombres:
            raise ValueError(
                f"'{nombre}' no es una herramienta de este ayudante. "
                "Solo puede usar las aiuditas que su dueño le activó."
            )
        # El tenant no se acepta del modelo: se impone. Si viene en los argumentos, se
        # ignora en silencio (no es un error del modelo, es una defensa del servidor).
        limpio = {k: v for k, v in (args or {}).items() if k not in ("tenant_id", "tenant")}
        return self._exec(nombre, limpio)


def _respuesta(mid, result) -> dict:
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def _error(mid, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}


def _manejar(msg: dict, sesion: Sesion) -> dict | None:
    """Contesta UN mensaje JSON-RPC. Devuelve None si era una notificación."""
    mid = msg.get("id")
    metodo = msg.get("method")
    params = msg.get("params") or {}

    if metodo == "initialize":
        pedida = params.get("protocolVersion")
        return _respuesta(
            mid,
            {
                "protocolVersion": pedida or VERSION_POR_DEFECTO,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "aiuda", "version": "0.1.0"},
            },
        )

    if metodo in ("notifications/initialized", "initialized"):
        return None  # notificación: no lleva respuesta

    if metodo == "ping":
        return _respuesta(mid, {})

    if metodo == "tools/list":
        return _respuesta(mid, {"tools": sesion.tools})

    if metodo == "tools/call":
        nombre = params.get("name") or ""
        args = params.get("arguments") or {}
        try:
            texto = sesion.llamar(nombre, args)
        except ValueError as exc:
            # isError, no un error de JSON-RPC: el modelo tiene que poder leerlo y
            # corregir. Un error de protocolo mataría la sesión entera.
            return _respuesta(
                mid, {"content": [{"type": "text", "text": str(exc)}], "isError": True}
            )
        except Exception as exc:  # el ejecutor falló de verdad
            print(f"aiuda-mcp: fallo en {nombre}: {exc!r}", file=sys.stderr, flush=True)
            return _respuesta(
                mid,
                {
                    "content": [
                        {"type": "text", "text": f"No se pudo consultar: {exc}"}
                    ],
                    "isError": True,
                },
            )
        return _respuesta(mid, {"content": [{"type": "text", "text": texto}], "isError": False})

    if mid is None:
        return None  # notificación desconocida: se ignora, no se contesta
    return _error(mid, METHOD_NOT_FOUND, f"Método no soportado: {metodo}")


def bucle(entrada: TextIO, salida: TextIO, sesion: Sesion) -> None:
    """Lee mensajes delimitados por salto de línea y contesta. Inyectable para pruebas."""
    for linea in entrada:
        linea = linea.strip()
        if not linea:
            continue
        try:
            msg = json.loads(linea)
        except json.JSONDecodeError:
            _escribir(salida, _error(None, PARSE_ERROR, "JSON inválido"))
            continue
        if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
            _escribir(salida, _error(msg.get("id") if isinstance(msg, dict) else None,
                                     INVALID_REQUEST, "No es un mensaje JSON-RPC 2.0"))
            continue
        try:
            respuesta = _manejar(msg, sesion)
        except Exception as exc:
            print(f"aiuda-mcp: {exc!r}", file=sys.stderr, flush=True)
            respuesta = _error(msg.get("id"), INTERNAL_ERROR, str(exc))
        if respuesta is not None:
            _escribir(salida, respuesta)


def _escribir(salida: TextIO, obj: dict) -> None:
    salida.write(json.dumps(obj, ensure_ascii=False) + "\n")
    salida.flush()


def _abrir_sesion(entorno: dict[str, str], fabrica_sesion: Callable[[], Any] | None = None):
    """Arma la Sesion desde el entorno. Falla ruidoso: sin alcance no se sirve nada."""
    from sqlalchemy import select

    if fabrica_sesion is None:
        from aiuda_core.db import get_sessionmaker

        fabrica_sesion = get_sessionmaker()

    db = fabrica_sesion()
    tenant_id = entorno.get("AIUDA_TENANT_ID") or ""
    if tenant_id:
        tenant = db.get(Tenant, tenant_id)
    else:
        # Un solo workspace: si no se especifica, es el único que hay. Se resuelve por
        # el más viejo, igual que el scheduler, para no inventar uno nuevo.
        tenant = db.scalars(select(Tenant).order_by(Tenant.created_at)).first()
    if tenant is None:
        raise SystemExit("aiuda-mcp: no hay negocio en esta computadora todavía.")

    ayudante = None
    ayudante_id = entorno.get("AIUDA_AYUDANTE_ID") or ""
    if ayudante_id:
        ayudante = db.get(Ayudante, ayudante_id)
        if ayudante is None or ayudante.tenant_id != tenant.id:
            raise SystemExit(f"aiuda-mcp: el ayudante {ayudante_id} no es de este negocio.")

    return Sesion(db, tenant, ayudante, caller_phone=entorno.get("AIUDA_CALLER_PHONE") or None)


def correr(entorno: dict[str, str] | None = None) -> None:
    """Punto de entrada de `aiuda mcp`. Sirve hasta que el cliente cierra stdin."""
    sesion = _abrir_sesion(dict(entorno if entorno is not None else os.environ))
    print(
        f"aiuda-mcp: {len(sesion.tools)} herramientas para "
        f"{sesion.ayudante.name if sesion.ayudante else 'el negocio'}",
        file=sys.stderr,
        flush=True,
    )
    bucle(sys.stdin, sys.stdout, sesion)
