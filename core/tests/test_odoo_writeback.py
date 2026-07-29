"""Contrato del write-back de Odoo a nivel XML-RPC.

Un Odoo de mentiras contesta lo que contestaría uno real y GRABA cada request
(modelo, método, args, kwargs): así el test fija el contrato del write — qué se
manda y qué se espera de vuelta. Con la credencial real de José solo cambia el
endpoint; el conector no cambia.
"""

import pytest
from sqlalchemy import select

import aiuda_core.connectors.odoo as odoo_mod
from aiuda_core.connectors.odoo import OdooConnector
from aiuda_core.engine.writeback import process_outbox, queue_payment_writeback
from aiuda_core.models import OutboxEntry


class FakeOdooServer:
    """Doble del servidor: despacha execute_kw como Odoo y registra las llamadas."""

    def __init__(self):
        self.calls = []  # (model, method, args, kwargs) — el contrato grabado
        self.moves = {
            7: {
                "id": 7,
                "name": "F-001",
                "state": "posted",
                "amount_residual": 12500.5,
                "payment_state": "not_paid",
            },
            9: {
                "id": 9,
                "name": "/",
                "state": "draft",
                "amount_residual": 800.0,
                "payment_state": "not_paid",
            },
        }
        self.partners = {
            12: {"id": 12, "name": "Odoo Cliente", "email": "viejo@x.mx", "phone": "5215511112222"}
        }
        self.messages = []  # (move_id, body) — chatter
        self.payments = []  # vals del wizard por cada pago asentado
        self._next_id = 100

    # --- transporte ---------------------------------------------------------
    def execute_kw(self, db, uid, key, model, method, args, kwargs=None):
        assert uid == 2 and key == "api-key"  # autenticado con la credencial
        kwargs = dict(kwargs or {})
        self.calls.append((model, method, args, kwargs))
        handler = getattr(self, f"_{model.replace('.', '_')}_{method}")
        return handler(args, kwargs)

    # --- account.move ---------------------------------------------------------
    def _account_move_search(self, args, kwargs):
        (campo, _, valor), *_ = args[0]
        llave = {"name": "name", "id": "id"}[campo]
        return [m["id"] for m in self.moves.values() if m[llave] == valor]

    def _account_move_read(self, args, kwargs):
        fields = kwargs.get("fields") or []
        return [
            {"id": mid, **{f: self.moves[mid].get(f) for f in fields}} for mid in args[0]
        ]

    def _account_move_message_post(self, args, kwargs):
        self.messages.append((args[0][0], kwargs.get("body", "")))
        return self._next()

    # --- account.payment.register (wizard estándar de "Registrar pago") -------
    def _account_payment_register_create(self, args, kwargs):
        ctx = kwargs.get("context") or {}
        assert ctx.get("active_model") == "account.move"  # sin contexto el wizard no sabe qué pagar
        assert ctx.get("active_ids")
        self._wizard = {"vals": args[0], "move_id": ctx["active_ids"][0]}
        return self._next()

    def _account_payment_register_action_create_payments(self, args, kwargs):
        move = self.moves[self._wizard["move_id"]]
        monto = float(self._wizard["vals"].get("amount") or move["amount_residual"])
        self.payments.append({**self._wizard["vals"], "move_id": move["id"]})
        move["amount_residual"] = round(move["amount_residual"] - monto, 2)
        move["payment_state"] = "paid" if move["amount_residual"] <= 0 else "partial"
        pid = self._next()
        # Lo que Odoo devuelve: una acción apuntando al pago creado
        return {"type": "ir.actions.act_window", "res_model": "account.payment", "res_id": pid}

    # --- res.partner -----------------------------------------------------------
    def _res_partner_fields_get(self, args, kwargs):
        return {"name": {"type": "char"}, "email": {"type": "char"}, "phone": {"type": "char"}}

    def _res_partner_create(self, args, kwargs):
        pid = self._next()
        self.partners[pid] = {"id": pid, **args[0]}
        return pid

    def _res_partner_write(self, args, kwargs):
        for pid in args[0]:
            self.partners[pid].update(args[1])
        return True

    def _res_partner_read(self, args, kwargs):
        fields = kwargs.get("fields") or []
        return [
            {"id": pid, **{f: self.partners[pid].get(f, False) for f in fields}}
            for pid in args[0]
        ]

    def _next(self) -> int:
        self._next_id += 1
        return self._next_id


class _FakeCommon:
    def authenticate(self, db, user, key, opts):
        return 2


@pytest.fixture()
def servidor(monkeypatch):
    server = FakeOdooServer()

    class _FakeModels:
        def execute_kw(self, *a):
            return server.execute_kw(*a)

    monkeypatch.setattr(
        odoo_mod,
        "_proxy",
        lambda url: _FakeCommon() if url.endswith("/common") else _FakeModels(),
    )
    return server


@pytest.fixture()
def conector():
    return OdooConnector("https://odoo.ejemplo.mx", "ejemplo", "dueno@ejemplo.mx", "api-key")


def test_registrar_pago_asienta_con_el_wizard(servidor, conector):
    evidencia = conector.register_invoice_payment(
        "F-001", amount=12500.5, memo="aiuda: pago confirmado (banco).", payment_date="2026-07-07"
    )
    # Request esperado: el wizard se crea con el contexto de la factura activa
    modelo, metodo, args, kwargs = next(
        c for c in servidor.calls if c[0] == "account.payment.register" and c[1] == "create"
    )
    assert args[0] == {
        "amount": 12500.5,
        "communication": "aiuda: pago confirmado (banco).",
        "payment_date": "2026-07-07",
    }
    assert kwargs["context"] == {"active_model": "account.move", "active_ids": [7]}
    assert ("account.payment.register", "action_create_payments") in [
        (c[0], c[1]) for c in servidor.calls
    ]
    # Respuesta grabada: Odoo quedó saldado y la evidencia lo reporta
    assert evidencia["modo"] == "pago"
    assert evidencia["payment_state"] == "paid"
    assert evidencia["saldo_odoo"] == 0.0
    assert evidencia["payment_id"] and evidencia["move_id"] == 7
    assert servidor.moves[7]["amount_residual"] == 0.0


def test_monto_se_acota_al_saldo_de_odoo(servidor, conector):
    servidor.moves[7]["amount_residual"] = 8000.0  # allá ya abonaron parte
    evidencia = conector.register_invoice_payment("F-001", amount=12500.5, memo="x")
    assert servidor.payments[0]["amount"] == 8000.0  # no duplica el cobro
    assert evidencia["monto"] == 8000.0


def test_borrador_deja_nota_honesta(servidor, conector):
    """La cartera de Hanova vive en borrador: Odoo no asienta pagos sobre
    borradores, así que queda constancia en el chatter y se dice tal cual. El
    folio provisional (borrador-9) resuelve por id, no por name."""
    evidencia = conector.register_invoice_payment("borrador-9", amount=800.0, memo="aiuda: pago confirmado.")
    assert evidencia["modo"] == "nota"
    assert servidor.messages == [(9, "aiuda: pago confirmado.")]
    assert servidor.payments == []  # ningún wizard: no se puede asentar
    # Se buscó por id (folio provisional), no por name
    assert ("account.move", "search", [[("id", "=", 9)]], {"limit": 1}) in servidor.calls


def test_ya_pagada_en_odoo_no_escribe_nada(servidor, conector):
    servidor.moves[7].update({"amount_residual": 0.0, "payment_state": "paid"})
    evidencia = conector.register_invoice_payment("F-001", amount=12500.5, memo="x")
    assert evidencia["modo"] == "ya_pagada"
    assert servidor.payments == [] and servidor.messages == []


def test_factura_inexistente_lanza(servidor, conector):
    with pytest.raises(LookupError):
        conector.register_invoice_payment("NO-EXISTE", amount=1.0, memo="x")


def test_upsert_partner_actualiza(servidor, conector):
    evidencia = conector.upsert_partner("12", {"name": "Ferretería SA", "email": "nuevo@x.mx"})
    assert servidor.partners[12]["name"] == "Ferretería SA"
    assert servidor.partners[12]["email"] == "nuevo@x.mx"
    assert evidencia["creado"] is False
    assert evidencia["en_odoo"]["name"] == "Ferretería SA"
    # Vaciar un campo en aiuda lo vacía en Odoo (False, como lo guarda Odoo)
    conector.upsert_partner("12", {"email": None})
    assert servidor.partners[12]["email"] is False


def test_upsert_partner_da_de_alta_sin_liga(servidor, conector):
    evidencia = conector.upsert_partner(None, {"name": "Cliente Nuevo", "phone": "5215587654321"})
    assert evidencia["creado"] is True
    pid = evidencia["partner_id"]
    assert servidor.partners[pid]["customer_rank"] == 1  # entra como cliente
    assert servidor.partners[pid]["name"] == "Cliente Nuevo"


def test_criterio_maestro_pago_aprobado_llega_a_odoo(servidor, conector, session, tenant, customer, invoice):
    """El criterio del backlog §3: aprobar un pago en aiuda lo escribe de vuelta
    en Odoo (fake) y la cola queda inyectada con evidencia. Con la credencial
    real solo cambia el endpoint."""
    invoice.source = "odoo"
    invoice.paid_source = "banco"
    queue_payment_writeback(session, tenant, invoice)

    result = process_outbox(session, tenant, odoo_client=conector)

    assert result.processed == 1
    assert len(servidor.payments) == 1  # el pago quedó asentado en Odoo
    assert servidor.payments[0]["amount"] == 12500.5
    assert "F-001" in servidor.payments[0]["communication"]
    entry = session.scalar(select(OutboxEntry))
    assert entry.status == "done"  # la UI lo pinta "inyectada"
    assert entry.payload["evidencia"]["respuesta"]["payment_state"] == "paid"
