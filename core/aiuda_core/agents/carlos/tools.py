"""Tools de Carlos (Ventas): solo lectura sobre el catálogo y el directorio.

Carlos no inventa precios ni saldos: los consulta. Estas herramientas aterrizan
sus respuestas en datos reales del negocio (Product, Customer, Invoice) con el
tenant obligatorio en cada query.
"""

from sqlalchemy import func, or_, select

from aiuda_core.agents.base import ToolExecutor
from aiuda_core.models import Customer, Invoice, Product

CARLOS_TOOLS: list[dict] = [
    {
        "name": "consultar_catalogo",
        "description": (
            "Consulta el catálogo de productos con precio y existencia. Úsala SIEMPRE "
            "antes de mencionar un precio o disponibilidad — nunca los inventes. Puedes "
            "filtrar por nombre o SKU; sin filtro, lista el catálogo."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "busqueda": {
                    "type": "string",
                    "description": "Texto para filtrar por nombre o SKU (opcional)",
                }
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "consultar_cliente",
        "description": (
            "Busca un cliente por nombre o teléfono y devuelve su contacto y su saldo "
            "pendiente (suma de facturas abiertas). Úsala antes de hablar de lo que un "
            "cliente debe o de su historial — nunca inventes cifras."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "busqueda": {
                    "type": "string",
                    "description": "Nombre o teléfono del cliente a buscar",
                }
            },
            "required": ["busqueda"],
            "additionalProperties": False,
        },
    },
]


class CarlosToolExecutor(ToolExecutor):
    """Ejecuta los tools de ventas. Solo lectura, tenant obligatorio."""

    _LIMIT = 30

    def _consultar_catalogo(self, busqueda: str | None = None) -> str:
        query = select(Product).where(Product.tenant_id == self.tenant.id)
        if busqueda:
            like = f"%{busqueda.strip()}%"
            query = query.where(or_(Product.name.ilike(like), Product.sku.ilike(like)))
        rows = self.session.scalars(query.order_by(Product.name).limit(self._LIMIT)).all()
        if not rows:
            return "Sin productos con ese criterio."
        lines = []
        for p in rows:
            precio = f"${float(p.price):,.2f}" if p.price is not None else "sin precio"
            existencia = (
                f"{float(p.stock):g} {p.unit or 'u'}" if p.stock is not None else "sin existencia"
            )
            sku = f" | SKU {p.sku}" if p.sku else ""
            lines.append(f"{p.name}{sku} | {precio} | {existencia}")
        return "\n".join(lines)

    def _consultar_cliente(self, busqueda: str) -> str:
        like = f"%{busqueda.strip()}%"
        clientes = self.session.scalars(
            select(Customer)
            .where(
                Customer.tenant_id == self.tenant.id,
                or_(Customer.name.ilike(like), Customer.phone.ilike(like)),
            )
            .order_by(Customer.name)
            .limit(self._LIMIT)
        ).all()
        if not clientes:
            return "Sin clientes con ese criterio."
        lines = []
        for c in clientes:
            saldo = self.session.scalar(
                select(func.coalesce(func.sum(Invoice.amount), 0)).where(
                    Invoice.tenant_id == self.tenant.id,
                    Invoice.customer_id == c.id,
                    Invoice.status == "open",
                )
            )
            tipo = "prospecto" if c.kind == "prospecto" else "cliente"
            contacto = c.phone or c.email or "sin contacto"
            lines.append(
                f"{c.name} ({tipo}) | {contacto} | saldo pendiente: ${float(saldo):,.2f}"
            )
        return "\n".join(lines)
