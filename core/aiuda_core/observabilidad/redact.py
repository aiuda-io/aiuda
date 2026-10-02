"""Quitarle los datos de tus clientes a la transcripción, sin volverla ilegible.

Guardar el prompt de una corrida de cobranza es guardar la cartera: teléfonos, correos,
RFCs, nombres. Esto lo redacta ANTES de que toque la base.

DOS DECISIONES QUE IMPORTAN:

1. **Los montos y los folios NO se redactan.** El dueño abre la transcripción para juzgar
   si el mensaje estaba bien, y sin el monto ni el folio no puede. Redactarlos volvería la
   pantalla inútil justo para lo que existe.

2. **El marcador es estable**: `[tel:a91f]` es prefijo más hash corto del valor. Así el
   dueño ve que dos menciones son el MISMO teléfono, sin que el teléfono esté ahí. Un
   `[tel]` genérico perdería esa información y volvería ilegible un hilo.

Los nombres de cliente no se pueden atrapar por regex: se sustituyen por diccionario, con
los `Customer.name` del propio tenant.
"""

from __future__ import annotations

import hashlib
import re

# Teléfono mexicano en cualquiera de sus formas: E.164 (+52…, 521…), 10 dígitos con o sin
# separadores, con lada entre paréntesis. Se pide un borde de no-dígito para no morder la
# mitad de un folio largo.
_TEL = re.compile(r"(?<!\d)(?:\+?52\s?1?[\s.-]?)?(?:\(\d{2,3}\)|\d{2,3})[\s.-]?\d{3,4}[\s.-]?\d{4}(?!\d)")
_CORREO = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
# RFC: 4 letras + 6 dígitos + 3 de homoclave (física) o 3 letras + 6 + 3 (moral).
_RFC = re.compile(r"\b[A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3}\b", re.IGNORECASE)
_CURP = re.compile(r"\b[A-Z]{4}\d{6}[HM][A-Z]{5}[A-Z0-9]\d\b", re.IGNORECASE)
_CLABE = re.compile(r"(?<!\d)\d{18}(?!\d)")
# 14 a 19 dígitos, y el último no puede ser un separador. Un teléfono mexicano en E.164
# son 13 (521 + 10) y pasaba por aquí: 5215512345678 hasta cumple Luhn por casualidad. En
# una herramienta de cobranza mexicana, una cadena de 13 dígitos es un teléfono.
_TARJETA = re.compile(r"(?<!\d)\d(?:[ -]?\d){13,18}(?!\d)")


def _marca(prefijo: str, valor: str) -> str:
    """Marcador estable: el mismo valor da el mismo marcador, siempre."""
    corto = hashlib.sha256(valor.encode("utf-8")).hexdigest()[:4]
    return f"[{prefijo}:{corto}]"


def _luhn(numero: str) -> bool:
    """¿Pasa el check de Luhn? Sin esto, cualquier cadena larga de dígitos (un folio, una
    referencia bancaria) se confundiría con una tarjeta."""
    digitos = [int(c) for c in numero if c.isdigit()]
    if not 13 <= len(digitos) <= 19:
        return False
    total, doble = 0, False
    for d in reversed(digitos):
        if doble:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        doble = not doble
    return total % 10 == 0


def redactar(texto: str | None, nombres: list[str] | None = None) -> str | None:
    """Devuelve el texto con los datos personales sustituidos por marcadores estables.

    `nombres` son los `Customer.name` del tenant: lo único que atrapa a un cliente por
    nombre, porque por regex es imposible."""
    if not texto:
        return texto
    out = texto

    # ORDEN: el teléfono va primero. Es el dato más común en cobranza y el más específico
    # del dominio; si corriera después, la regla de tarjeta ya se lo habría comido.
    out = _TEL.sub(lambda m: _marca("tel", re.sub(r"\D", "", m.group())[-10:]), out)
    out = _TARJETA.sub(lambda m: _marca("tarjeta", m.group()) if _luhn(m.group()) else m.group(), out)
    out = _CLABE.sub(lambda m: _marca("clabe", m.group()), out)
    out = _CURP.sub(lambda m: _marca("curp", m.group().upper()), out)
    out = _RFC.sub(lambda m: _marca("rfc", m.group().upper()), out)
    out = _CORREO.sub(lambda m: _marca("correo", m.group().lower()), out)

    # Nombres de cliente: los más largos primero, para que "Ferretería Ruiz SA de CV" no
    # quede a medias por sustituir antes "Ferretería Ruiz".
    for nombre in sorted({n.strip() for n in (nombres or []) if n and len(n.strip()) > 3},
                         key=len, reverse=True):
        # Se conserva la primera palabra: "[cliente:Ferretería…]" sigue siendo legible y
        # el dueño reconoce de quién se habla sin que el registro cargue el dato completo.
        primera = nombre.split()[0]
        out = re.sub(re.escape(nombre), f"[cliente:{primera}]", out, flags=re.IGNORECASE)
    return out


def redactar_args(args: dict | None, nombres: list[str] | None = None) -> dict:
    """Lo mismo sobre los argumentos de una tool (valores de texto, recursivo en dicts)."""
    if not isinstance(args, dict):
        return {}
    limpio: dict = {}
    for k, v in args.items():
        if isinstance(v, str):
            limpio[k] = redactar(v, nombres)
        elif isinstance(v, dict):
            limpio[k] = redactar_args(v, nombres)
        elif isinstance(v, list):
            limpio[k] = [redactar(x, nombres) if isinstance(x, str) else x for x in v]
        else:
            limpio[k] = v
    return limpio
