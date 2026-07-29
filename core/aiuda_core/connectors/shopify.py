"""Conector Shopify — tienda en línea del negocio.

Para qué lo usa aiuda: obtener los pedidos pendientes de pago de la tienda
para alimentar la cartera de Mariana. Cuando un cliente ordenó pero no pagó,
Shopify lo sabe antes de que la dueña lo note; aiuda lo convierte en tarea de
cobranza automáticamente. También deja rastro de gestión (notas) en cada
pedido para que el historial quede dentro de Shopify.

Auth: Custom App de la tienda — header X-Shopify-Access-Token.
Docs: https://shopify.dev/docs/api/admin-rest/2024-01/resources/order
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


@dataclass
class ContactoTienda:
    id: int
    name: str
    phone: str
    email: str


class ShopifyClient:
    def __init__(
        self,
        store_domain: str | None = None,
        access_token: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ):
        domain = store_domain or settings.shopify_store_domain
        token = access_token or settings.shopify_access_token
        if not domain:
            raise RuntimeError(
                "SHOPIFY_STORE_DOMAIN no configurado — ver .env.example"
            )
        if not token:
            raise RuntimeError(
                "SHOPIFY_ACCESS_TOKEN no configurado — ver .env.example"
            )
        self.base_url = f"https://{domain.rstrip('/')}"
        self._http = httpx.Client(
            base_url=self.base_url,
            headers={"X-Shopify-Access-Token": token},
            timeout=30,
            transport=transport,
        )

    def list_unpaid_orders(self) -> list[PedidoPorCobrar]:
        """Pedidos abiertos con pago pendiente — la cartera activa de Mariana."""
        response = self._http.get(
            "/admin/api/2024-01/orders.json",
            params={"financial_status": "pending", "status": "open"},
        )
        response.raise_for_status()
        pedidos = []
        for o in response.json().get("orders", []):
            customer = o.get("customer") or {}
            first = customer.get("first_name") or ""
            last = customer.get("last_name") or ""
            customer_name = f"{first} {last}".strip()

            # El teléfono puede venir del cliente o de su dirección predeterminada
            phone = (
                customer.get("phone")
                or (customer.get("default_address") or {}).get("phone")
                or ""
            )

            pedidos.append(
                PedidoPorCobrar(
                    id=o["id"],
                    name=o.get("name", ""),
                    total=float(o.get("total_price") or 0),
                    currency=o.get("currency", ""),
                    customer_name=customer_name,
                    customer_phone=phone,
                    created_at=o.get("created_at", ""),
                )
            )
        return pedidos

    def list_products(self) -> list[ProductoTienda]:
        """Catálogo activo de la tienda — productos con precio y existencia. Capacidad
        `catalogo_productos` (toma la primera variante de cada producto)."""
        response = self._http.get(
            "/admin/api/2024-01/products.json",
            params={"status": "active"},
        )
        response.raise_for_status()
        productos = []
        for p in response.json().get("products", []):
            variants = p.get("variants") or []
            v = variants[0] if variants else {}
            productos.append(
                ProductoTienda(
                    id=p["id"],
                    name=p.get("title", ""),
                    sku=(v.get("sku") or ""),
                    price=float(v.get("price") or 0),
                    stock=float(v.get("inventory_quantity") or 0),
                )
            )
        return productos

    def list_customers(self) -> list[ContactoTienda]:
        """Clientes de la tienda — para el directorio. Capacidad `directorio_clientes`
        (nombre de first+last, teléfono del cliente o de su dirección, correo)."""
        response = self._http.get("/admin/api/2024-01/customers.json")
        response.raise_for_status()
        contactos = []
        for c in response.json().get("customers", []):
            first = c.get("first_name") or ""
            last = c.get("last_name") or ""
            phone = c.get("phone") or (c.get("default_address") or {}).get("phone") or ""
            contactos.append(
                ContactoTienda(
                    id=c["id"],
                    name=f"{first} {last}".strip(),
                    phone=phone,
                    email=(c.get("email") or ""),
                )
            )
        return contactos

    def test_connection(self) -> dict:
        """Prueba ligera para 'Probar conexión': valida el access token contra la
        tienda (shop.json) y devuelve conteos honestos, sin bajar los pedidos. Los
        pedidos se cuentan con el MISMO filtro de list_unpaid_orders (pendientes de
        pago y abiertos), no todos los del historial."""
        base = "/admin/api/2024-01"
        shop = self._http.get(f"{base}/shop.json")
        shop.raise_for_status()
        nombre = (shop.json().get("shop") or {}).get("name", "")
        productos = self._http.get(f"{base}/products/count.json")
        productos.raise_for_status()
        pendientes = self._http.get(
            f"{base}/orders/count.json",
            params={"financial_status": "pending", "status": "open"},
        )
        pendientes.raise_for_status()
        return {
            "shop": nombre,
            "productos": int(productos.json().get("count") or 0),
            "pedidos_sin_pagar": int(pendientes.json().get("count") or 0),
        }

    def mark_note(self, order_id: int, note: str) -> dict:
        """Deja rastro escrito de la gestión de cobranza en el pedido de Shopify."""
        response = self._http.put(
            f"/admin/api/2024-01/orders/{order_id}.json",
            json={"order": {"id": order_id, "note": note}},
        )
        response.raise_for_status()
        return response.json()
