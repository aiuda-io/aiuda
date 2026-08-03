"""Qué hizo cada ayudante: una fila por unidad de trabajo, no un log suelto.

aiuda no tenía forma de contestar "¿qué hizo mi ayudante ayer?". `usage_events` guardaba
(modelo, tarea, tokens) sin nada de qué se leyó ni qué se propuso, `audit_logs` registra
las decisiones del HUMANO, y el resultado de la corrida diaria solo llegaba a stdout.

Tres tablas, todas NUEVAS: `create_all` las crea sin migración. Los enlaces apuntan
siempre de lo nuevo a lo viejo (`run_turns.usage_event_id`, `run_links`,
`Reminder.meta["run_id"]`), justo para no tener que agregar columnas a tablas que ya
existen en la base de alguien.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from aiuda_core.models.base import Base, TenantMixin, TimestampMixin, new_id


class Run(Base, TenantMixin, TimestampMixin):
    """Una unidad de trabajo que el dueño nombraría: "la corrida de anoche", "cuando le
    pregunté a Male", "el encargo al portal del SAT"."""

    __tablename__ = "runs"
    __table_args__ = (
        CheckConstraint(
            "status in ('running','done','failed','cortado')", name="ck_run_status"
        ),
        Index("ix_runs_tenant_started", "tenant_id", "started_at"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    # NULL = lo hizo el sistema (una sincronización, un barrido), no un ayudante.
    ayudante_id: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, index=True)
    # SNAPSHOT del nombre: el dueño renombra y borra ayudantes, y la bitácora no puede
    # quedar huérfana ni cambiar de golpe lo que dice que pasó.
    ayudante_nombre: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    aiudita_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    # corrida | manual | chat | entrante | rutina
    disparo: Mapped[str] = mapped_column(String(16), default="corrida")
    status: Mapped[str] = mapped_column(String(16), default="running", index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # UNA frase, escrita por CÓDIGO. Si el modelo narra su propio trabajo, la bitácora
    # deja de ser evidencia y pasa a ser otra cosa que hay que verificar.
    resumen: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # {"leidos": 12, "propuestos": 4, "omitidos": 8, "fallidos": 1}
    conteos: Mapped[dict] = mapped_column(JSON, default=dict)
    # [{"codigo": "sin_whatsapp", "n": 1, "detalle": "Ferretería R. sin teléfono"}]
    motivos: Mapped[list] = mapped_column(JSON, default=list)
    input_tokens: Mapped[int] = mapped_column(default=0)
    output_tokens: Mapped[int] = mapped_column(default=0)
    # Denormalizado a propósito: la lista no debe hacer GROUP BY por fila.
    costo_usd: Mapped[Optional[float]] = mapped_column(Numeric(10, 6), nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)


class RunTurn(Base, TenantMixin, TimestampMixin):
    """Una ida y vuelta al modelo. Es la parte cara y sensible, y la que se poda."""

    __tablename__ = "run_turns"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    idx: Mapped[int] = mapped_column(default=0)
    # redaccion | clasificacion | agent_loop (el mismo `role` que ya viaja al runner)
    role: Mapped[str] = mapped_column(String(16), default="redaccion")
    # El MISMO `task` de usage_events: "draft_reminder", "ayudante_chat"…
    task: Mapped[str] = mapped_column(String(64), default="")
    model: Mapped[str] = mapped_column(String(64), default="")
    # Ya redactados según Tenant.config["observabilidad"]["guardar_prompts"].
    system_prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    user_prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    output_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # [{"nombre", "args", "resultado_resumen", "ms", "error"}]
    tools: Mapped[list] = mapped_column(JSON, default=list)
    input_tokens: Mapped[int] = mapped_column(default=0)
    output_tokens: Mapped[int] = mapped_column(default=0)
    latencia_ms: Mapped[int] = mapped_column(default=0)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Enlace duro con lo que YA existe, en esta dirección para no tocar usage_events.
    usage_event_id: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, index=True)


class RunLink(Base, TenantMixin, TimestampMixin):
    """Qué entidades del negocio tocó el run. Sin esto, la pantalla no puede llevarte
    al trabajo real: enseñaría "propuso 4" sin poder abrir ninguno."""

    __tablename__ = "run_links"
    __table_args__ = (UniqueConstraint("run_id", "entity_type", "entity_id", "rol"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    # reminder | payment | invoice | outbox | cua_mission | audit_log | message
    entity_type: Mapped[str] = mapped_column(String(32))
    entity_id: Mapped[str] = mapped_column(String(32), index=True)
    # leyo | propuso | escribio
    rol: Mapped[str] = mapped_column(String(16), default="leyo")
