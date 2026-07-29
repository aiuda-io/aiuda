"""CarlosEngine (ventas): genera cotizaciones con aprobación humana (HITL).

Qué PROPONE este runtime (proponer, nunca ejecutar sin humano): cotizaciones
(`draft_quote`) que quedan en pending_approval en la bandeja; aprobar y enviar
reusa el flujo de recordatorios. En el chat, Carlos solo CONSULTA (catálogo y
clientes, ver tools.py) — no escribe nada.

Mismo molde que cobranza (CleoEngine): el código decide los NÚMEROS (precios reales
del catálogo, descuento topado, IVA, total — nunca inventados); el LLM solo redacta
la presentación con la voz y las reglas del negocio. La config (vigencia, IVA, tope
de descuento, reglas) vive por-ayudante; la cotización queda atribuida al ayudante
que gobierna esa aiudita (meta.ayudante_id), lo que alimenta su plan de carrera.
"""

from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from aiuda_core.aiuditas.resolve import ayudante_con_aiudita, config_or_none
from aiuda_core.engine import approval
from aiuda_core.engine.llm import BudgetExceeded, strip_emojis, strip_markdown
from aiuda_core.engine.provider import resolve_credential
from aiuda_core.engine.runner import ProviderRunner, make_runner
from aiuda_core.models import Customer, Product, Reminder, Tenant, UsageEvent

IVA_RATE = 0.16


class QuoteError(ValueError):
    """Datos inválidos para cotizar (producto inexistente, sin partidas, etc.)."""


def _money(n: float) -> str:
    return f"${n:,.2f}"


def _procedencia(products: list[Product]) -> dict:
    """De dónde salieron los precios: las fuentes de los productos usados y su
    presencia (archivo/fecha/liga). Para que quien aprueba vea la trazabilidad, no
    para el cliente. Si los precios mezclan fuentes, se listan todas."""
    sources: list[str] = []
    presence: dict = {}
    for p in products:
        if p.source and p.source not in sources:
            sources.append(p.source)
        for sys, info in (p.presence or {}).items():
            prev = presence.get(sys)
            # conserva la presencia más reciente por sistema
            if prev is None or str(info.get("at", "")) > str(prev.get("at", "")):
                presence[sys] = info
    return {
        "que": "Precios de tu catálogo",
        "source": sources[0] if sources else "excel",
        "sources": sources,
        "presence": presence,
    }


class CarlosEngine:
    def __init__(self, session: Session, tenant: Tenant, runner: ProviderRunner | None = None):
        self.session = session
        self.tenant = tenant
        self.runner = runner or make_runner(
            resolve_credential(session=session, tenant_id=tenant.id),
            usage_callback=self._record_usage,
        )
        if self.runner._usage_callback is None:
            self.runner._usage_callback = self._record_usage

    def _record_usage(self, model: str, task: str, input_tokens: int, output_tokens: int) -> None:
        self.session.add(
            UsageEvent(
                tenant_id=self.tenant.id, model=model, task=task,
                input_tokens=input_tokens, output_tokens=output_tokens,
            )
        )

    def _cfg(self) -> dict:
        return config_or_none(self.session, self.tenant, "ventas.generar_cotizacion") or {}

    def draft_quote(
        self,
        customer: Customer,
        items: list[dict],
        descuento_pct: float = 0.0,
        today: date | None = None,
    ) -> Reminder:
        """Arma una cotización para `customer` con `items` = [{product_id, cantidad}].

        Los precios salen del catálogo real; el descuento se topa al máximo que el
        dueño permitió; el IVA se calcula según su perilla. Devuelve un Reminder
        pending_approval (no envía nada)."""
        cfg = self._cfg()
        validez = int(cfg.get("validez_dias", 15))
        iva_incluido = bool(cfg.get("iva_incluido", True))
        desc_max = float(cfg.get("descuento_max", 0))
        reglas = (cfg.get("reglas") or "").strip()
        today = today or datetime.now().date()

        if not items:
            raise QuoteError("La cotización necesita al menos un producto.")
        # El descuento que pida el dueño nunca pasa del tope configurado.
        desc = min(max(float(descuento_pct), 0.0), desc_max)

        lines: list[str] = []
        subtotal = 0.0
        usados: list[Product] = []
        for it in items:
            product = self.session.get(Product, it.get("product_id", ""))
            if product is None or product.tenant_id != self.tenant.id:
                raise QuoteError(f"Producto no encontrado: {it.get('product_id')}")
            if product.price is None:
                raise QuoteError(f"«{product.name}» no tiene precio en el catálogo.")
            qty = float(it.get("cantidad", 1) or 1)
            line_total = float(product.price) * qty
            subtotal += line_total
            usados.append(product)
            lines.append(f"- {product.name} x{qty:g} · {_money(float(product.price))} = {_money(line_total)}")

        descuento_monto = subtotal * desc / 100
        base = subtotal - descuento_monto
        if iva_incluido:
            total = base
            iva = base - base / (1 + IVA_RATE)  # IVA contenido (informativo)
            nota_iva = f"IVA incluido (16%): {_money(iva)}"
        else:
            iva = base * IVA_RATE
            total = base + iva
            nota_iva = f"IVA (16%): {_money(iva)}"

        cuerpo_lineas = [
            f"Cotización para {customer.name}",
            "",
            *lines,
            "",
            f"Subtotal: {_money(subtotal)}",
        ]
        if desc > 0:
            cuerpo_lineas.append(f"Descuento ({desc:g}%): -{_money(descuento_monto)}")
        cuerpo_lineas.append(nota_iva)
        cuerpo_lineas.append(f"Total: {_money(total)}")
        cuerpo_lineas.append(f"Vigencia: {validez} días (hasta {today + timedelta(days=validez)})")
        cuerpo = "\n".join(cuerpo_lineas)

        intro = self._intro(customer, reglas)
        # Misma red que el chat de cobranza: la cotización va al WhatsApp del cliente,
        # texto plano (la intro es del LLM; el cuerpo determinista ya lo es).
        message = strip_markdown(strip_emojis(f"{intro}\n\n{cuerpo}")).strip()

        # Procedencia para quien aprueba + atribución: qué ayudante del dueño gobierna
        # la aiudita de cotizar (su config decidió vigencia/IVA/tope) — alimenta su
        # plan de carrera con trabajo real. Sin ayudante, sin atribución (sin fingir).
        meta: dict = {"procedencia": _procedencia(usados)}
        autor = ayudante_con_aiudita(self.session, self.tenant, "ventas.generar_cotizacion")
        if autor is not None:
            meta["ayudante_id"] = autor.id
            meta["ayudante_name"] = autor.name

        reminder = Reminder(
            tenant_id=self.tenant.id,
            agent="carlos",
            invoice_id=None,
            title=f"Cotización para {customer.name}",
            recipient_phone=customer.phone,
            bucket="comercial",
            tone="comercial",
            message=message,
            status="draft",
            meta=meta,
        )
        self.session.add(reminder)
        approval.advance(reminder, "pending_approval")
        self.session.flush()
        return reminder

    def _intro(self, customer: Customer, reglas: str) -> str:
        """Saludo breve de presentación de la cotización, con la voz del negocio. Si no
        hay proveedor de IA, cae a una intro neutra (el cuerpo es lo que importa)."""
        system = (
            f'Eres el área de ventas de "{self.tenant.name}", un negocio mexicano. Escribes a '
            f"un cliente para presentarle una cotización. Una o dos frases, cálidas y "
            f"profesionales, en español de México. No repitas precios ni totales (van abajo). "
            f"Texto plano, sin emojis ni markdown."
        )
        if reglas:
            system += f"\nReglas del negocio (respétalas): {reglas}"
        try:
            return self.runner.complete(
                system=system,
                user=f"Cliente: {customer.name}. Redacta solo el saludo de presentación.",
                role="redaccion",
                task="generar_cotizacion",
                max_tokens=160,
            ).strip()
        except BudgetExceeded:
            # El tope del mes manda sobre el fallback: cotizar con saludo neutro
            # ocultaría que la IA está pausada. El endpoint lo traduce a 402.
            raise
        except Exception:
            return f"Hola {customer.name}, con gusto le comparto su cotización:"
