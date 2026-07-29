"""Conector Mercado Libre — ventas del marketplace del negocio.

Para qué lo usa aiuda: traer a la cartera las ventas con pago pendiente, el
catálogo (publicaciones con precio y existencia) y los compradores recientes al
directorio. Mismas dataclasses de forma que Shopify/WooCommerce para reusar los
upserts del motor (engine/sync).

Auth: OAuth del dueño (API oficial). El access_token de ML dura ~6 horas; con
client_id + client_secret + refresh_token aiuda lo REFRESCA solo cuando la API
responde 401 (POST /oauth/token, grant_type=refresh_token). OJO: el refresh_token
de ML es de UN SOLO USO — al refrescar, ML devuelve un access_token nuevo Y un
refresh_token nuevo, e invalida el anterior. Por eso el cliente expone
`token_refreshed` + el par nuevo: la corrida (engine/sync) lo persiste cifrado
para que la siguiente no use un refresh_token ya invalidado. Sin persistencia se
refresca en memoria por corrida (queda documentado el porqué).

Contrato: API REST oficial (https://api.mercadolibre.com), documentada. PENDIENTE
de verificar en vivo: requiere una app y credenciales OAuth del vendedor.
Docs: https://developers.mercadolibre.com.mx/es_ar/orders  ·  /items  ·  /users
"""

from dataclasses import dataclass

import httpx

from aiuda_core.config import settings

API_BASE = "https://api.mercadolibre.com"

# Estado de orden de ML que significa "esperando pago" (lo útil para cobranza). ML
# suele cobrar antes de liberar el envío, así que esta lista es el subconjunto
# genuinamente por cobrar (p.ej. transferencia/efectivo aún no acreditado). Se
# consulta con el filtro `order.status` documentado; se deja como constante para
# ser explícito sobre el criterio.
ESTADO_POR_COBRAR = "payment_required"


@dataclass
class PedidoPorCobrar:
    id: int
    name: str          # folio tipo #2000003508123456
    total: float
    currency: str
    customer_name: str
    customer_phone: str
    created_at: str


@dataclass
class ProductoTienda:
    id: str
    name: str
    sku: str
    price: float
    stock: float


@dataclass
class ContactoTienda:
    id: str
    name: str
    phone: str
    email: str


def _chunks(seq, size):
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def _buyer_name(buyer: dict) -> str:
    nick = (buyer.get("nickname") or "").strip()
    if nick:
        return nick
    nombre = f"{buyer.get('first_name') or ''} {buyer.get('last_name') or ''}".strip()
    return nombre or "Comprador"


def _buyer_phone(buyer: dict) -> str:
    """Teléfono del comprador si ML lo expone (a menudo lo oculta por privacidad)."""
    phone = buyer.get("phone") or {}
    if isinstance(phone, dict):
        return str(phone.get("number") or "")
    return ""


def _item_sku(body: dict) -> str:
    """SKU de una publicación: `seller_custom_field` o el atributo SELLER_SKU."""
    scf = body.get("seller_custom_field")
    if scf:
        return str(scf)
    for attr in body.get("attributes") or []:
        if attr.get("id") == "SELLER_SKU" and attr.get("value_name"):
            return str(attr["value_name"])
    return ""


class MercadoLibreClient:
    def __init__(
        self,
        access_token: str | None = None,
        refresh_token: str = "",
        client_id: str = "",
        client_secret: str = "",
        seller_id: str = "",
        transport: httpx.BaseTransport | None = None,
    ):
        self.access_token = access_token or settings.mercadolibre_access_token
        self.refresh_token = refresh_token or settings.mercadolibre_refresh_token
        self.client_id = client_id or settings.mercadolibre_client_id
        self.client_secret = client_secret or settings.mercadolibre_client_secret
        self.seller_id = str(seller_id or settings.mercadolibre_seller_id or "")
        if not self.access_token and not self.refresh_token:
            raise RuntimeError(
                "Mercado Libre no configurado — captura el access token (o el refresh "
                "token con client_id/client_secret)."
            )
        # True si durante la corrida se rotó el token: el motor lo persiste (uso único).
        self.token_refreshed = False
        self._http = httpx.Client(base_url=API_BASE, timeout=30, transport=transport)

    # --- Auth ----------------------------------------------------------------

    def _auth(self) -> dict:
        return {"Authorization": f"Bearer {self.access_token}"}

    def _refresh(self) -> bool:
        """Cambia el refresh_token por un access_token nuevo (grant_type=refresh_token).
        ML rota el refresh_token: se guarda el nuevo. Devuelve False si no hay con qué
        refrescar o si ML rechaza (el llamador deja subir el error real)."""
        if not (self.refresh_token and self.client_id and self.client_secret):
            return False
        resp = self._http.post(
            "/oauth/token",
            data={
                "grant_type": "refresh_token",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "refresh_token": self.refresh_token,
            },
            headers={"Accept": "application/json"},
        )
        if resp.status_code != 200:
            return False
        body = resp.json()
        nuevo = body.get("access_token")
        if not nuevo:
            return False
        self.access_token = nuevo
        if body.get("refresh_token"):
            self.refresh_token = body["refresh_token"]  # uso único: ML lo rota
        self.token_refreshed = True
        return True

    def _get(self, path: str, params: dict | None = None):
        """GET autenticado con refresco reactivo: si el token caducó (401) se refresca
        UNA vez y se reintenta. Si no hay access_token, intenta refrescar primero."""
        if not self.access_token and not self._refresh():
            raise RuntimeError(
                "Mercado Libre: sin access token y sin poder refrescar (revisa "
                "client_id, client_secret y refresh_token)."
            )
        resp = self._http.get(path, params=params or {}, headers=self._auth())
        if resp.status_code == 401 and self._refresh():
            resp = self._http.get(path, params=params or {}, headers=self._auth())
        resp.raise_for_status()
        return resp.json()

    def _resolver_seller(self) -> str:
        """El id del vendedor. Si no vino en las credenciales, lo resuelve con /users/me."""
        if self.seller_id:
            return self.seller_id
        me = self._get("/users/me")
        self.seller_id = str(me.get("id") or "")
        return self.seller_id

    # --- Lecturas ------------------------------------------------------------

    def list_unpaid_orders(self) -> list[PedidoPorCobrar]:
        """Ventas con pago pendiente (order.status=payment_required) → cartera."""
        seller = self._resolver_seller()
        data = self._get(
            "/orders/search",
            params={"seller": seller, "order.status": ESTADO_POR_COBRAR, "sort": "date_desc"},
        )
        pedidos = []
        for o in data.get("results", []):
            buyer = o.get("buyer") or {}
            pedidos.append(
                PedidoPorCobrar(
                    id=o.get("id"),
                    name=f"#{o.get('id')}",
                    total=float(o.get("total_amount") or 0),
                    currency=o.get("currency_id") or "",
                    customer_name=_buyer_name(buyer),
                    customer_phone=_buyer_phone(buyer),
                    created_at=o.get("date_created") or "",
                )
            )
        return pedidos

    def list_products(self) -> list[ProductoTienda]:
        """Publicaciones del vendedor con precio y existencia. Capacidad
        `catalogo_productos`. Busca los IDs (una página) y hace multi-get de /items."""
        seller = self._resolver_seller()
        search = self._get(f"/users/{seller}/items/search", params={"limit": 50})
        ids = search.get("results", []) or []
        productos: list[ProductoTienda] = []
        for chunk in _chunks(ids, 20):
            items = self._get("/items", params={"ids": ",".join(chunk)})
            for entry in items or []:
                body = entry.get("body") if isinstance(entry, dict) else None
                if not body:
                    continue  # multi-get: una entrada sin body (p.ej. code!=200) se omite
                productos.append(
                    ProductoTienda(
                        id=body.get("id") or "",
                        name=body.get("title") or "",
                        sku=_item_sku(body),
                        price=float(body.get("price") or 0),
                        stock=float(body.get("available_quantity") or 0),
                    )
                )
        return productos

    def list_customers(self) -> list[ContactoTienda]:
        """Compradores de las ventas recientes → directorio. Dedup por id de comprador.
        ML suele ocultar teléfono/correo del comprador: se traen si vienen, sin inventar."""
        seller = self._resolver_seller()
        data = self._get("/orders/search", params={"seller": seller, "sort": "date_desc"})
        vistos: dict[str, ContactoTienda] = {}
        for o in data.get("results", []):
            buyer = o.get("buyer") or {}
            bid = str(buyer.get("id") or "")
            if not bid or bid in vistos:
                continue
            vistos[bid] = ContactoTienda(
                id=bid,
                name=_buyer_name(buyer),
                phone=_buyer_phone(buyer),
                email=buyer.get("email") or "",
            )
        return list(vistos.values())

    def test_connection(self) -> dict:
        """Prueba real: /users/me (nickname + id) y el conteo de publicaciones del
        vendedor. Verifica que el token (o el refresco) sirva."""
        me = self._get("/users/me")
        seller = str(me.get("id") or "")
        if seller and not self.seller_id:
            self.seller_id = seller
        items = self._get(f"/users/{seller}/items/search", params={"limit": 1})
        total = (items.get("paging") or {}).get("total", 0) if isinstance(items, dict) else 0
        return {"nickname": me.get("nickname") or "", "seller_id": seller, "items": total}
