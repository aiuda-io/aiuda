"""Servidor MCP de aiuda: el negocio expuesto como herramientas para el arnés del dueño.

Es la ÚNICA puerta por la que un modelo toca los datos del negocio cuando corre en el
CLI que el dueño ya tiene instalado (`claude`, `codex`). No es un camino nuevo de
permisos: importa los mismos ejecutores que usa el chat de la consola, con el mismo
tenant obligatorio.
"""

from aiuda_core.mcp.server import correr, herramientas_de

__all__ = ["correr", "herramientas_de"]
