"""Opt-out de mensajes automatizados: el cliente escribe BAJA/STOP y no se le envía más.

El registro vive en la tabla ``optouts``, una fila por (tenant, contacto). La llave es
``contact_key`` del destinatario — ``match_key(teléfono)`` (últimos 10 dígitos, estable
ante 52 vs 521) para WhatsApp/SMS, o el correo normalizado (minúsculas) para el canal de
correo. La baja es POR MEDIO de contacto: quien pide BAJA por correo deja de recibir
correos automatizados; su WhatsApp es otra llave.

POR QUÉ TABLA Y NO ``Tenant.config["optouts"]``, que es donde vivía: ese blob se guarda
con read-modify-write del JSON completo. El sondeo de entrantes registra la baja
(worker/main.py) mientras el latido del scheduler escribe ``ultima_corrida_horaria`` en
el MISMO objeto cada 30 s, cada uno con su sesión. El último commit gana y descarta la
llave del otro sin ruido. Una baja podía desaparecer y aiuda le volvía a escribir a
quien dijo que no.

TRANSICIÓN: la lectura consulta la tabla Y el blob legado. Se queda así a propósito
hasta que ``migrar_optouts_del_config`` lleve semanas sin encontrar nada: equivocarse
del lado de "no le escribas" es gratis, del otro lado no.

Alcance honesto:
- Bloquea los envíos AUTOMATIZADOS (recordatorios y seguimientos del agente).
- El dueño humano puede seguir escribiendo desde la consola (soberanía humana);
  la ficha del cliente muestra el aviso para que decida con contexto.
- Si el cliente escribe de nuevo, el agente puede responderle (conversación que
  él inició); lo que no regresa son los recordatorios, hasta que el dueño lo
  reactive desde la ficha.
"""

from __future__ import annotations

import unicodedata

from sqlalchemy import select

from aiuda_core.models import OptOut, Tenant
from aiuda_core.phones import match_key


class OptedOut(Exception):
    """El destinatario pidió no recibir mensajes (BAJA/STOP). No es un fallo del
    canal: es una decisión del cliente que se respeta. El recordatorio se marca
    'failed' con el motivo visible, nunca se reintenta solo."""


# El mensaje completo (normalizado) debe SER una de estas frases. Igualdad exacta,
# no contención: "no quiero darme de baja" NO debe marcar opt-out.
OPT_OUT_PHRASES = {
    "baja",
    "stop",
    "alto",
    "unsubscribe",
    "no molestar",
    "no me molesten",
    "no mas mensajes",
    "ya no me manden mensajes",
    "ya no quiero mensajes",
}

# Confirmación determinista (sin LLM): cortés, una sola vez, y honesta sobre qué
# se detiene. El dueño sigue pudiendo escribir en persona desde la consola.
OPT_OUT_CONFIRMATION = (
    "Entendido, ya no te enviaremos recordatorios por este medio. "
    "Si cambias de opinión, escríbenos cuando quieras."
)


def contact_key(value) -> str:
    """Llave estable del destinatario para el registro de bajas: un correo (trae
    ``@``) se normaliza a minúsculas; un teléfono pasa por ``match_key``. Cadena
    vacía si no da una llave usable (no se arriesga un match con basura)."""
    text = str(value or "").strip()
    if "@" in text:
        return text.lower()
    return match_key(text)


def _normalize(text: str) -> str:
    """minúsculas, sin acentos, sin puntuación en los bordes, espacios colapsados."""
    lowered = unicodedata.normalize("NFKD", str(text or "").lower())
    stripped = "".join(ch for ch in lowered if not unicodedata.combining(ch))
    cleaned = "".join(ch if ch.isalnum() or ch.isspace() else " " for ch in stripped)
    return " ".join(cleaned.split())


def is_opt_out(body: str) -> bool:
    """¿El mensaje es una solicitud de baja? Igualdad exacta tras normalizar."""
    return _normalize(body) in OPT_OUT_PHRASES


def _legado(tenant, key: str) -> dict | None:
    """La baja como estaba en el blob de config. Solo lectura, para la transición."""
    entry = ((tenant.config or {}).get("optouts") or {}).get(key)
    return dict(entry) if isinstance(entry, dict) else None


def opted_out(session, tenant, phone: str) -> dict | None:
    """El registro de opt-out del destinatario (teléfono o correo) — ``{"at", "via"}``
    o None si puede recibir. Consulta la tabla y, si no hay fila, el blob legado."""
    key = contact_key(phone)
    if not key:
        return None
    row = session.scalar(
        select(OptOut).where(OptOut.tenant_id == tenant.id, OptOut.contact_key == key)
    )
    if row is not None:
        return {"at": row.created_at.isoformat() if row.created_at else None, "via": row.via}
    return _legado(tenant, key)


def claves_dadas_de_baja(session, tenant) -> set[str]:
    """Todas las ``contact_key`` con baja de este tenant, en una sola consulta.

    Para listas: preguntar cliente por cliente con ``opted_out`` es un N+1. Compara
    contra ``contact_key(...)`` del destinatario."""
    filas = session.scalars(
        select(OptOut.contact_key).where(OptOut.tenant_id == tenant.id)
    ).all()
    legado = (tenant.config or {}).get("optouts")
    if isinstance(legado, dict):
        return set(filas) | {k for k in legado if k}
    return set(filas)


def mark_opt_out(session, tenant, phone: str, via: str = "whatsapp") -> bool:
    """Registra la baja. Devuelve False si el destinatario no da una llave usable.

    Idempotente: si ya existe la fila no la duplica ni le mueve la fecha (la primera
    vez que el cliente lo pidió es el dato que importa)."""
    key = contact_key(phone)
    if not key:
        return False
    ya = session.scalar(
        select(OptOut).where(OptOut.tenant_id == tenant.id, OptOut.contact_key == key)
    )
    if ya is None:
        session.add(OptOut(tenant_id=tenant.id, contact_key=key, via=via))
        session.flush()
    return True


def clear_opt_out(session, tenant, phone: str) -> bool:
    """Quita la baja (el dueño reactiva desde la ficha, p.ej. si el cliente se lo
    pidió). Devuelve True si había registro que quitar, por cualquiera de las dos vías."""
    key = contact_key(phone)
    if not key:
        return False
    habia = False
    row = session.scalar(
        select(OptOut).where(OptOut.tenant_id == tenant.id, OptOut.contact_key == key)
    )
    if row is not None:
        session.delete(row)
        habia = True
    # Y del blob legado, si quedó algo ahí: si no, reactivar no reactivaría nada.
    cfg = dict(tenant.config or {})
    optouts = dict(cfg.get("optouts") or {})
    if optouts.pop(key, None) is not None:
        cfg["optouts"] = optouts
        tenant.config = cfg
        session.add(tenant)
        habia = True
    if habia:
        session.flush()
    return habia


def migrar_optouts_del_config(session) -> int:
    """Pasa las bajas del blob legado a la tabla. Idempotente; devuelve cuántas movió.

    NO borra el blob: la lectura sigue consultándolo mientras dure la transición, y una
    baja perdida es exactamente lo que este cambio viene a evitar. Se limpia después,
    cuando esta función lleve semanas devolviendo cero."""
    movidas = 0
    for tenant in session.scalars(select(Tenant)).all():
        optouts = (tenant.config or {}).get("optouts")
        if not isinstance(optouts, dict):
            continue
        for key, entry in optouts.items():
            if not key:
                continue
            ya = session.scalar(
                select(OptOut).where(OptOut.tenant_id == tenant.id, OptOut.contact_key == key)
            )
            if ya is not None:
                continue
            via = entry.get("via") if isinstance(entry, dict) else None
            session.add(OptOut(tenant_id=tenant.id, contact_key=key, via=via or "whatsapp"))
            movidas += 1
    if movidas:
        session.flush()
    return movidas
