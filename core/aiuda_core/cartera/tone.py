"""Tono graduado por bucket. Determinístico: el código decide el tono, el LLM redacta."""

from aiuda_core.cartera.aging import Bucket

# Buckets en los que se permite recordatorio automático (con aprobación HITL por defecto)
REMINDER_BUCKETS = (
    Bucket.VENCE_PRONTO,
    Bucket.VENCIDA_RECIENTE,
    Bucket.VENCIDA,
    Bucket.CRITICA,
)

TONE_BY_BUCKET: dict[Bucket, str] = {
    Bucket.POR_VENCER: "ninguno",
    Bucket.VENCE_PRONTO: "amable",
    Bucket.VENCIDA_RECIENTE: "amable_directo",
    Bucket.VENCIDA: "firme",
    Bucket.CRITICA: "urgente_escalado",
}

# Guía que recibe el LLM al redactar. El agente NUNCA negocia solo en crítica:
# ahí el mensaje avisa que el dueño contactará personalmente.
TONE_GUIDANCE: dict[str, str] = {
    "amable": (
        "Recordatorio cordial y breve de que la factura está por vencer. "
        "Tono cálido mexicano profesional, sin presión. Agradece la preferencia."
    ),
    "amable_directo": (
        "La factura ya venció hace pocos días. Tono amable pero directo: menciona "
        "la fecha de vencimiento y pide amablemente realizar el pago o avisar si ya se hizo."
    ),
    "firme": (
        "Atraso considerable. Tono firme y profesional, sin agresividad: indica los días "
        "de atraso, solicita acordar una fecha de pago concreta y ofrece facilidades de contacto."
    ),
    "urgente_escalado": (
        "Atraso crítico. Tono serio y formal: informa que el asunto se escaló y que el "
        "responsable del negocio se pondrá en contacto personalmente. NO negocies términos."
    ),
}


def tone_for(bucket: Bucket) -> str:
    return TONE_BY_BUCKET[bucket]
