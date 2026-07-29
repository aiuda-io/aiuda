"""Saneo de salida del modelo para la consola.

Regla dura de aiuda: cero emojis (red de seguridad sobre core/engine/llm.py) y sin
markdown (la consola no lo renderiza). Compartido por los endpoints de chat.
"""

import re

from aiuda_core.engine.llm import strip_emojis


def plain_text(text: str) -> str:
    text = strip_emojis(text)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)  # **negritas**
    text = re.sub(r"__(.+?)__", r"\1", text)
    text = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", text)  # encabezados
    text = re.sub(r"(?m)^\s*[\*\-]\s+", "- ", text)  # viñetas a guion simple
    return re.sub(r"[ \t]{2,}", " ", text).strip()
