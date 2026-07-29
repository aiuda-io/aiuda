"""Conector WooCommerce — tienda WordPress del negocio.

Para qué lo usa aiuda: traer los pedidos pendientes de pago del negocio
para que Mariana tenga su cartera completa, incluyendo a quienes compraron
en la tienda propia (WordPress) y no han pagado. Complementa Shopify cuando
el negocio migró o tiene ambas plataformas.

Auth: HTTP Basic con (consumer_key, consumer_secret) del wp-admin.
Docs: https://woocommerce.github.io/woocommerce-rest-api-docs/#orders
"""

from dataclasses import dataclass

import httpx

from aiuda_core.config import settings


@dataclass
class PedidoPorCobrar:
    id: int
    name: str          # folio tipo #1001
    total: float
    currency: str
    customer_name: str
    customer_phone: str
    created_at: str


@dataclass
class ProductoTienda:
    id: int
    name: str
    sku: str
    price: float
    stock: float


class WooCommerceClient:
    def __init__(
        self,
        base_url: str | None = None,
        consumer_key: str | None = None,
        consumer_secret: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ):
        url = base_url or settings.woocommerce_base_url
        key = consumer_key or settings.woocommerce_consumer_key
        secret = consumer_secret or settings.woocommerce_consumer_secret
        if not url:
            raise RuntimeError(
                "WOOCOMMERCE_BASE_URL no configurado — ver .env.example"
            )
        if not key:
            raise RuntimeError(
                "WOOCOMMERCE_CONSUMER_KEY no configurado — ver .env.example"
            )
        self.base_url = url.rstrip("/")
        self._http = httpx.Client(
            base_url=self.base_url,
            auth=(key, secret),
            timeout=30,
            transport=transport,
        )

    def list_unpaid_orders(self) -> list[PedidoPorCobrar]:
        """Pedidos en estado pending u on-hold — los que todavía no pagaron."""
        response = self._http.get(
            "/wp-json/wc/v3/orders",
            params={"status": "pending,on-hold", "per_page": 50},
        )
        response.raise_for_status()
        pedidos = []
        for o in response.json():
            billing = o.get("billing") or {}
            first = billing.get("first_name") or ""
            last = billing.get("last_name") or ""
            customer_name = f"{first} {last}".strip()
            phone = billing.get("phone") or ""

            pedidos.append(
                PedidoPorCobrar(
                    id=o["id"],
                    name=f"#{o.get('number', o['id'])}",
                    total=float(o.get("total") or 0),
                    currency=o.get("currency", ""),
                    customer_name=customer_name,
                    customer_phone=phone,
                    created_at=o.get("date_created", ""),
                )
            )
        return pedidos

    def test_connection(self) -> dict:
        """Prueba ligera para 'Probar conexión': valida las llaves (Basic) pidiendo
        una página mínima (per_page=1) y lee el total del encabezado X-WP-Total, sin
        traer todo. Reporta catálogo y pedidos pendientes (el MISMO filtro de
        list_unpaid_orders: pending y on-hold)."""
        productos = self._http.get(
            "/wp-json/wc/v3/products", params={"per_page": 1}
        )
        productos.raise_for_status()
        pendientes = self._http.get(
            "/wp-json/wc/v3/orders",
            params={"per_page": 1, "status": "pending,on-hold"},
        )
        pendientes.raise_for_status()

        def _total(resp: httpx.Response) -> int:
            # Woo devuelve el total en el encabezado; si falta, cae al tamaño de la
            # página traída (no peor que hoy).
            try:
                return int(resp.headers.get("X-WP-Total", len(resp.json())))
            except (TypeError, ValueError):
                return len(resp.json())

        return {
            "productos": _total(productos),
            "pedidos_pendientes": _total(pendientes),
        }

    def list_products(self) -> list[ProductoTienda]:
        """Catálogo publicado de la tienda — productos con precio y existencia.
        Capacidad `catalogo_productos` (Woo da precio y SKU a nivel producto)."""
        response = self._http.get(
            "/wp-json/wc/v3/products",
            params={"status": "publish", "per_page": 50},
        )
        response.raise_for_status()
        productos = []
        for p in response.json():
            productos.append(
                ProductoTienda(
                    id=p["id"],
                    name=p.get("name", ""),
                    sku=(p.get("sku") or ""),
                    price=float(p.get("price") or 0),
                    stock=float(p.get("stock_quantity") or 0),
                )
            )
        return productos
