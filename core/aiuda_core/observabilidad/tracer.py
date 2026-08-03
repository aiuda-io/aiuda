"""Grabar qué hizo un ayudante, sin que el motor se entere.

DÓNDE SE INSTRUMENTA, Y POR QUÉ AHÍ. En `make_runner`, no en `tenant_runner`.
`make_runner` se llama en nueve lugares y `tenant_runner` es solo uno: la corrida diaria
(`engine/engine.py:161`), las cotizaciones (`agents/carlos/engine.py:63`), el importador
inteligente y el lector de estados de cuenta lo llaman directo. Envolver en `tenant_runner`
dejaría ciegos justo los runs que el dueño más quiere ver.

EL PELIGRO DEL WRAPPER. `budget_check` y `_usage_callback` se ASIGNAN DESDE FUERA después
de construir (`engine.py:167-168`, `worker/main.py:141`). Un wrapper normal se quedaría con
esa asignación y el runner de adentro nunca vería el tope de gasto: se apagaría el corte de
presupuesto en silencio, que es peor que no tener trazas. Por eso `_TracedRunner` proxya
`__getattr__` y `__setattr__` hacia el runner interno, y hay un test que lo fija.
"""

from __future__ import annotations

import contextlib
import time
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from aiuda_core.models import Customer, Run, RunLink, RunTurn

# Atributos propios del wrapper. Todo lo demás viaja al runner de adentro.
_MIOS = {"_interno", "_run", "_db", "_idx", "_nombres", "_pendiente"}


def _modelo_de(runner, role: str) -> str:
    """El id del modelo, si el runner lo sabe decir. Si no, cadena vacía: la traza es
    secundaria y jamás debe romper el trabajo real."""
    try:
        return runner.model_for(role) or ""
    except Exception:
        return ""


class _TracedRunner:
    """Envuelve un ProviderRunner y graba un turno por llamada. Cumple el mismo Protocol
    porque delega todo lo que no sabe hacer."""

    def __init__(self, interno, run: "RunRecorder", db, nombres: list[str]):
        object.__setattr__(self, "_interno", interno)
        object.__setattr__(self, "_run", run)
        object.__setattr__(self, "_db", db)
        object.__setattr__(self, "_idx", 0)
        object.__setattr__(self, "_nombres", nombres)
        # El uso llega DURANTE la llamada, y el turno se escribe DESPUÉS: se acumula
        # aquí y se vuelca al turno cuando se crea.
        object.__setattr__(self, "_pendiente", {"in": 0, "out": 0, "model": ""})
        # El uso (tokens) no vuelve por el valor de retorno: el runner lo reporta por su
        # usage_callback. Se envuelve para atribuírselo al turno que lo generó.
        if getattr(interno, "_usage_callback", None) is not None:
            interno._usage_callback = self._contando(interno._usage_callback)

    def _contando(self, original):
        """Envuelve un usage_callback para anotar los tokens en el turno en curso."""

        def cb(model, task, input_tokens, output_tokens):
            p = object.__getattribute__(self, "_pendiente")
            p["in"] += int(input_tokens or 0)
            p["out"] += int(output_tokens or 0)
            p["model"] = p["model"] or (model or "")
            return original(model, task, input_tokens, output_tokens)

        return cb

    # -- proxy: sin esto, asignar budget_check apagaría el tope de gasto -------
    def __getattr__(self, nombre: str) -> Any:
        return getattr(object.__getattribute__(self, "_interno"), nombre)

    def __setattr__(self, nombre: str, valor: Any) -> None:
        if nombre in _MIOS:
            object.__setattr__(self, nombre, valor)
            return
        # Si alguien reemplaza el callback de uso DESPUÉS de envolver (el engine lo hace
        # cuando le inyectan un runner sin callback), se vuelve a envolver o los tokens
        # de ese runner dejarían de contarse.
        if nombre == "_usage_callback" and valor is not None:
            valor = self._contando(valor)
        setattr(object.__getattribute__(self, "_interno"), nombre, valor)

    # -- lo que sí se graba ---------------------------------------------------
    def _turno(self, *, role, task, model, system, user, salida, tools, ms, error=None):
        from aiuda_core.observabilidad.redact import redactar

        run = object.__getattribute__(self, "_run")
        db = object.__getattribute__(self, "_db")
        nombres = object.__getattribute__(self, "_nombres")
        idx = object.__getattribute__(self, "_idx")
        object.__setattr__(self, "_idx", idx + 1)

        pend = object.__getattribute__(self, "_pendiente")
        guardar = run.guardar_prompts
        fila = RunTurn(
                tenant_id=run.tenant_id,
                run_id=run.id,
                idx=idx,
                role=role,
                task=task or "",
                model=model or "",
                system_prompt=redactar(system, nombres) if guardar else None,
                user_prompt=redactar(user, nombres) if guardar else None,
                output_text=redactar(salida, nombres) if guardar else None,
                tools=tools or [],
                latencia_ms=ms,
                error=error,
                input_tokens=pend["in"],
                output_tokens=pend["out"],
        )
        if not fila.model:
            fila.model = pend["model"]
        db.add(fila)
        object.__setattr__(self, "_pendiente", {"in": 0, "out": 0, "model": ""})
        return fila

    def complete(self, system: str, user: str, **kw):
        interno = object.__getattribute__(self, "_interno")
        t0 = time.monotonic()
        try:
            salida = interno.complete(system, user, **kw)
        except Exception as exc:
            self._turno(
                role=kw.get("role", "redaccion"), task=kw.get("task", ""),
                model=kw.get("model") or "", system=system, user=user,
                salida=None, tools=[], ms=int((time.monotonic() - t0) * 1000), error=repr(exc)[:400],
            )
            raise
        self._turno(
            role=kw.get("role", "redaccion"), task=kw.get("task", ""),
            # Anotar el modelo no puede exigirle al runner un método opcional: grabar
            # nunca debe poder tumbar la corrida que está grabando.
            model=kw.get("model") or _modelo_de(interno, kw.get("role", "redaccion")),
            system=system, user=user, salida=salida, tools=[],
            ms=int((time.monotonic() - t0) * 1000),
        )
        return salida

    def classify(self, system: str, user: str, **kw):
        interno = object.__getattribute__(self, "_interno")
        t0 = time.monotonic()
        salida = interno.classify(system, user, **kw)
        self._turno(
            role="clasificacion", task=kw.get("task", ""), model="",
            system=system, user=user, salida=salida, tools=[],
            ms=int((time.monotonic() - t0) * 1000),
        )
        return salida

    def run_tool_loop(self, *, system, user_message, tools, execute_tool, **kw):
        """Envuelve `execute_tool` para cronometrar cada herramienta y capturar sus
        argumentos ANTES de pasársela al runner real."""
        from aiuda_core.observabilidad.redact import redactar_args

        interno = object.__getattribute__(self, "_interno")
        nombres = object.__getattribute__(self, "_nombres")
        llamadas: list[dict] = []

        def espiado(nombre: str, args: dict) -> str:
            t = time.monotonic()
            try:
                res = execute_tool(nombre, args)
            except Exception as exc:
                llamadas.append({
                    "nombre": nombre, "args": redactar_args(args, nombres),
                    "resultado_resumen": "", "ms": int((time.monotonic() - t) * 1000),
                    "error": repr(exc)[:200],
                })
                raise
            llamadas.append({
                "nombre": nombre, "args": redactar_args(args, nombres),
                # Solo el tamaño y el arranque: el resultado completo ES la cartera.
                "resultado_resumen": (redactar(str(res), nombres) or "")[:280],
                "ms": int((time.monotonic() - t) * 1000), "error": None,
            })
            return res

        from aiuda_core.observabilidad.redact import redactar

        t0 = time.monotonic()
        salida = interno.run_tool_loop(
            system=system, user_message=user_message, tools=tools,
            execute_tool=espiado, **kw,
        )
        self._turno(
            role=kw.get("role", "redaccion"), task=kw.get("task", "agent_loop"),
            model=kw.get("model") or "", system=system, user=user_message,
            salida=salida, tools=llamadas, ms=int((time.monotonic() - t0) * 1000),
        )
        return salida


class RunRecorder:
    """El run vivo. El motor le cuenta lo que va pasando en el lenguaje del dueño."""

    def __init__(self, db, fila: Run, guardar_prompts: bool):
        self._db = db
        self._fila = fila
        self.guardar_prompts = guardar_prompts

    @property
    def id(self) -> str:
        return self._fila.id

    @property
    def tenant_id(self) -> str:
        return self._fila.tenant_id

    def contar(self, **conteos: int) -> None:
        """`run.contar(leidos=12, propuestos=4)`. Se acumula."""
        actual = dict(self._fila.conteos or {})
        for k, v in conteos.items():
            actual[k] = int(actual.get(k, 0)) + int(v)
        self._fila.conteos = actual

    def motivo(self, codigo: str, detalle: str = "") -> None:
        """Por qué algo NO se hizo. Es la mitad honesta del reporte: sin esto el dueño
        ve "propuse 4 de 12" y no sabe qué pasó con las otras 8."""
        motivos = list(self._fila.motivos or [])
        for m in motivos:
            if m.get("codigo") == codigo:
                m["n"] = int(m.get("n", 0)) + 1
                return
        motivos.append({"codigo": codigo, "n": 1, "detalle": detalle})
        self._fila.motivos = motivos

    def liga(self, entity_type: str, entity_id: str, rol: str = "leyo") -> None:
        if not entity_id or not entity_type:
            return
        self._db.add(
            RunLink(
                tenant_id=self._fila.tenant_id, run_id=self._fila.id,
                entity_type=entity_type, entity_id=entity_id, rol=rol,
            )
        )

    def cortar(self, motivo: str) -> None:
        """Terminó sin error pero sin hacer el trabajo: se acabó el tope de IA, no hay
        proveedor, quedó fuera de la ventana de envío. Antes esto se perdía."""
        self._fila.status = "cortado"
        self._fila.error = motivo


@contextlib.contextmanager
def abrir_run(db, tenant, *, ayudante=None, aiudita: str = "", disparo: str = "corrida"):
    """Abre un run, lo cierra pase lo que pase, y devuelve el grabador.

        with abrir_run(db, tenant, ayudante=a, disparo="manual") as run:
            runner = tenant_runner(db, tenant, run=run)
            ...
            run.contar(leidos=12)
    """
    cfg = ((tenant.config or {}).get("observabilidad") or {})
    guardar = cfg.get("guardar_prompts", "redactado") != "no"

    fila = Run(
        tenant_id=tenant.id,
        ayudante_id=getattr(ayudante, "id", None),
        ayudante_nombre=getattr(ayudante, "name", None),
        aiudita_id=aiudita or None,
        disparo=disparo,
        status="running",
        started_at=datetime.now(timezone.utc),
        conteos={},
        motivos=[],
        meta={},
    )
    db.add(fila)
    db.flush()
    run = RunRecorder(db, fila, guardar)
    try:
        yield run
    except Exception as exc:
        fila.status = "failed"
        fila.error = repr(exc)[:500]
        _cerrar(db, fila, con_error=True)
        raise
    else:
        if fila.status == "running":
            fila.status = "done"
        _cerrar(db, fila, con_error=False)


def _cerrar(db, fila: Run, *, con_error: bool) -> None:
    """Cierra la fila del run. NUNCA relanza.

    Cuando algo tronó, la sesión va camino al rollback: un flush aquí puede fallar y
    enmascarar el error original, que es el que de verdad importa. Grabar la traza no
    puede costarle al dueño saber qué se rompió."""
    fila.finished_at = datetime.now(timezone.utc)
    try:
        if not con_error:
            _sumar_tokens(db, fila)
        fila.resumen = fila.resumen or _narrar(fila)
        db.flush()
    except Exception:  # noqa: BLE001 — la traza es secundaria, el trabajo real no
        pass


def _narrar(fila: Run) -> str:
    """La frase que el dueño lee. La escribe CÓDIGO, nunca el modelo: si el modelo narra
    su propio trabajo, la bitácora deja de ser evidencia."""
    if fila.status == "cortado":
        return f"Se detuvo: {fila.error}" if fila.error else "Se detuvo antes de terminar."
    if fila.status == "failed":
        return "No pudo terminar."

    c = fila.conteos or {}
    if fila.disparo == "chat":
        # Contestarte ES el trabajo aquí. Decir "no había nada que hacer" después de
        # responderte sería mentir en la única frase que el dueño lee.
        return "Te contestó." if c.get("respuestas") else "No alcanzó a contestar."

    partes = []
    if c.get("leidos"):
        partes.append(f"leyó {c['leidos']} facturas")
    if c.get("propuestos"):
        partes.append(f"propuso {c['propuestos']}")
    if c.get("omitidos"):
        partes.append(f"omitió {c['omitidos']}")
    if c.get("fallidos"):
        partes.append(f"{c['fallidos']} no pudo")
    if not partes:
        return "No había nada que hacer."
    return ", ".join(partes).capitalize() + "."


def _sumar_tokens(db, fila: Run) -> None:
    from sqlalchemy import func

    tot = db.execute(
        select(
            func.coalesce(func.sum(RunTurn.input_tokens), 0),
            func.coalesce(func.sum(RunTurn.output_tokens), 0),
        ).where(RunTurn.run_id == fila.id)
    ).one()
    fila.input_tokens, fila.output_tokens = int(tot[0]), int(tot[1])


def envolver(runner, run: RunRecorder | None, db, tenant):
    """Envuelve un runner para que grabe en `run`. Sin run, lo devuelve tal cual."""
    if run is None:
        return runner
    nombres = [
        n for (n,) in db.execute(
            select(Customer.name).where(Customer.tenant_id == tenant.id)
        ).all() if n
    ]
    return _TracedRunner(runner, run, db, nombres)
