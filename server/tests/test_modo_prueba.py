"""Modo de prueba: encendido de fábrica solo en instalaciones nuevas, y al
apagarlo el dueño decide qué pasa con lo que aprobó mientras no salía nada."""

from datetime import date, datetime, timezone

from aiuda_core.models import Customer, Invoice, Reminder, Tenant

from .test_api import client, db_session  # noqa: F401  (fixtures)


def _negocio(db_session, **config) -> Tenant:  # noqa: F811
    t = Tenant(name="Mi negocio", owner_phone="", evolution_instance="nuevo", config=config)
    db_session.add(t)
    db_session.flush()
    return t


def _recordatorio(db_session, tenant, status="approved", folio="F-1", sent_at=None) -> Reminder:  # noqa: F811
    # Un teléfono por folio: (negocio, teléfono) es único.
    telefono = f"52155000000{folio[-1].zfill(2)}"
    customer = Customer(tenant_id=tenant.id, name=f"C {folio}", phone=telefono)
    db_session.add(customer)
    db_session.flush()
    invoice = Invoice(
        tenant_id=tenant.id,
        customer_id=customer.id,
        folio=folio,
        amount=100,
        issued_date=date(2026, 5, 1),
        due_date=date(2026, 5, 31),
    )
    db_session.add(invoice)
    db_session.flush()
    reminder = Reminder(
        tenant_id=tenant.id,
        invoice_id=invoice.id,
        bucket="vencida",
        tone="firme",
        message="Recordatorio",
        status=status,
        sent_at=sent_at,
    )
    db_session.add(reminder)
    db_session.flush()
    return reminder


# --- De fábrica, solo para quien empieza -------------------------------------


def test_un_negocio_nuevo_nace_en_modo_de_prueba(client, db_session):  # noqa: F811
    tenant = _negocio(db_session)
    assert client.get("/v1/settings/modo-sombra").json()["modo_sombra"] is False

    res = client.put("/v1/setup/negocio", json={"nombre": "Taquería La Esquina"})
    assert res.status_code == 200

    db_session.refresh(tenant)
    assert tenant.config["modo_sombra"] is True
    assert client.get("/v1/settings/modo-sombra").json()["modo_sombra"] is True
    # El cierre del asistente lo dice en una línea: lo lee de aquí.
    assert client.get("/v1/setup/estado").json()["modo_prueba"] is True


def test_el_default_de_lectura_no_cambia(client, db_session):  # noqa: F811
    """Sin la llave en `tenant.config`, el modo de prueba se lee APAGADO. Cambiar ese
    default le apagaría los envíos a quien ya envía de verdad y nunca lo tocó."""
    _negocio(db_session, setup_negocio=True, setup_terminado=True)
    body = client.get("/v1/settings/modo-sombra").json()
    assert body == {"modo_sombra": False, "retenidos": 0}
    assert client.get("/v1/setup/estado").json()["modo_prueba"] is False


def test_quien_ya_paso_por_el_asistente_no_se_toca(client, db_session):  # noqa: F811
    """Cambiar el nombre después (o volver a pasar por el paso) no enciende nada."""
    tenant = _negocio(db_session, setup_negocio=True)
    client.put("/v1/setup/negocio", json={"nombre": "Otro nombre"})
    db_session.refresh(tenant)
    assert "modo_sombra" not in tenant.config


def test_quien_ya_lo_apago_no_se_le_vuelve_a_encender(client, db_session):  # noqa: F811
    tenant = _negocio(db_session, modo_sombra=False)
    client.put("/v1/setup/negocio", json={"nombre": "Taquería"})
    db_session.refresh(tenant)
    assert tenant.config["modo_sombra"] is False


def test_quien_ya_envio_de_verdad_no_cae_en_modo_de_prueba(client, db_session):  # noqa: F811
    """Un negocio armado por otra vía (un respaldo, la API) que ya mandó mensajes
    reales y por lo que sea ve el asistente: no se le apagan los envíos."""
    tenant = _negocio(db_session)
    _recordatorio(db_session, tenant, status="sent", sent_at=datetime.now(timezone.utc))
    client.put("/v1/setup/negocio", json={"nombre": "Ya trabajaba"})
    db_session.refresh(tenant)
    assert "modo_sombra" not in tenant.config


def test_volver_al_paso_del_negocio_respeta_lo_que_el_dueno_decidio(client, db_session):  # noqa: F811
    """Nace en prueba, el dueño lo apaga y regresa a corregir el nombre: sigue apagado."""
    tenant = _negocio(db_session)
    client.put("/v1/setup/negocio", json={"nombre": "Taquería"})
    client.put("/v1/settings/modo-sombra", json={"activo": False})
    client.put("/v1/setup/negocio", json={"nombre": "Taquería La Esquina"})
    db_session.refresh(tenant)
    assert tenant.config["modo_sombra"] is False


def test_quien_salta_el_paso_del_negocio_tambien_nace_en_modo_de_prueba(client, db_session):  # noqa: F811
    """El paso del nombre se puede saltar. Sin esto, saltarlo era la manera de
    estrenar aiuda mandando de verdad sin haberlo decidido."""
    tenant = _negocio(db_session)
    # El cierre ya lo anuncia, aunque todavía no esté escrito.
    assert client.get("/v1/setup/estado").json()["modo_prueba"] is True
    assert "modo_sombra" not in (tenant.config or {})

    client.post("/v1/setup/terminar")
    db_session.refresh(tenant)
    assert tenant.config["modo_sombra"] is True
    assert client.get("/v1/settings/modo-sombra").json()["modo_sombra"] is True


def test_cerrar_el_asistente_no_enciende_nada_a_quien_ya_decidio(client, db_session):  # noqa: F811
    tenant = _negocio(db_session, modo_sombra=False)
    client.post("/v1/setup/terminar")
    db_session.refresh(tenant)
    assert tenant.config["modo_sombra"] is False


# --- Al apagarlo: lo retenido -------------------------------------------------


def test_cuenta_lo_retenido_mientras_esta_encendido(client, db_session):  # noqa: F811
    tenant = _negocio(db_session, modo_sombra=True)
    _recordatorio(db_session, tenant, folio="F-1")
    _recordatorio(db_session, tenant, folio="F-2")
    _recordatorio(db_session, tenant, status="pending_approval", folio="F-3")
    _recordatorio(
        db_session, tenant, status="sent", folio="F-4", sent_at=datetime.now(timezone.utc)
    )
    assert client.get("/v1/settings/modo-sombra").json() == {"modo_sombra": True, "retenidos": 2}


def test_apagar_y_mandar_lo_retenido(client, db_session):  # noqa: F811
    from aiuda_server.api.main import app

    tenant = _negocio(db_session, modo_sombra=True)
    a = _recordatorio(db_session, tenant, folio="F-1")
    b = _recordatorio(db_session, tenant, folio="F-2")
    pendiente = _recordatorio(db_session, tenant, status="pending_approval", folio="F-3")

    res = client.put("/v1/settings/modo-sombra", json={"activo": False, "retenidos": "enviar"})
    assert res.status_code == 200
    assert res.json() == {"modo_sombra": False, "retenidos": 2, "retenidos_accion": "enviando"}

    # Salen por la ruta de envío de siempre, los dos aprobados y nada más.
    enviados = [args for nombre, args in app.state.test_jobs if nombre == "send_reminder"]
    assert sorted(enviados) == sorted([(tenant.id, a.id), (tenant.id, b.id)])
    assert (tenant.id, pendiente.id) not in enviados
    db_session.refresh(tenant)
    assert tenant.config["modo_sombra"] is False


def test_apagar_sin_mandar_lo_retenido_lo_deja_en_no_salio(client, db_session):  # noqa: F811
    """ "No mandarlos" tiene que ser verdad: aprobados se irían solos en la siguiente
    revisión horaria. Quedan en `failed` con su motivo, y se pueden reintentar."""
    from aiuda_server.api.main import MOTIVO_NO_ENVIADO_EN_PRUEBA, app

    tenant = _negocio(db_session, modo_sombra=True)
    a = _recordatorio(db_session, tenant, folio="F-1")
    pendiente = _recordatorio(db_session, tenant, status="pending_approval", folio="F-2")

    res = client.put("/v1/settings/modo-sombra", json={"activo": False, "retenidos": "no_enviar"})
    assert res.json() == {"modo_sombra": False, "retenidos": 1, "retenidos_accion": "no_enviados"}

    db_session.refresh(a)
    db_session.refresh(pendiente)
    assert a.status == "failed" and a.sent_at is None
    assert a.meta["motivo_fallo"] == MOTIVO_NO_ENVIADO_EN_PRUEBA
    assert pendiente.status == "pending_approval"  # lo que no se aprobó no se toca
    assert not [j for j in app.state.test_jobs if j[0] == "send_reminder"]


def test_lo_no_enviado_ya_no_lo_levanta_el_barrido_horario(client, db_session, monkeypatch):  # noqa: F811
    """La razón de ser de "no_enviar": el barrido de aprobados varados no lo manda."""
    from contextlib import contextmanager
    from datetime import timedelta

    import aiuda_server.worker.main as worker

    tenant = _negocio(db_session, modo_sombra=True)
    a = _recordatorio(db_session, tenant, folio="F-1")
    client.put("/v1/settings/modo-sombra", json={"activo": False, "retenidos": "no_enviar"})

    @contextmanager
    def misma_sesion():
        yield db_session

    monkeypatch.setattr(worker, "session_scope", misma_sesion)
    futuro = datetime.now(timezone.utc) + timedelta(hours=2)
    assert worker._sweep_stranded_approved(futuro) == 0
    db_session.refresh(a)
    assert a.status == "failed"


def test_apagar_sin_decidir_conserva_el_comportamiento_de_siempre(client, db_session):  # noqa: F811
    """Sin `retenidos` (un cliente viejo de la API): se quedan aprobados, como antes."""
    from aiuda_server.api.main import app

    tenant = _negocio(db_session, modo_sombra=True)
    a = _recordatorio(db_session, tenant, folio="F-1")
    res = client.put("/v1/settings/modo-sombra", json={"activo": False})
    assert res.json() == {"modo_sombra": False, "retenidos": 1, "retenidos_accion": None}
    db_session.refresh(a)
    assert a.status == "approved"
    assert not [j for j in app.state.test_jobs if j[0] == "send_reminder"]


def test_encender_no_toca_lo_aprobado(client, db_session):  # noqa: F811
    tenant = _negocio(db_session)
    a = _recordatorio(db_session, tenant, folio="F-1")
    res = client.put("/v1/settings/modo-sombra", json={"activo": True, "retenidos": "no_enviar"})
    assert res.json() == {"modo_sombra": True, "retenidos": 0, "retenidos_accion": None}
    db_session.refresh(a)
    assert a.status == "approved"


# --- El asistente no se esfuma a medio paso -----------------------------------


def test_el_estado_distingue_cerrado_por_el_dueno(client, db_session):  # noqa: F811
    """`terminado` se cumple solo en cuanto hay negocio, IA, datos y ayudante, y eso
    pasa justo al cargar la cartera, antes del cierre. El asistente necesita saber si
    el dueño de verdad llegó al final para no desaparecer con la cifra a medio ver."""
    tenant = _negocio(db_session)
    estado = client.get("/v1/setup/estado").json()
    assert estado["cerrado_por_el_dueno"] is False

    assert client.post("/v1/setup/terminar").json() == {"terminado": True}
    db_session.refresh(tenant)
    estado = client.get("/v1/setup/estado").json()
    assert estado["cerrado_por_el_dueno"] is True and estado["terminado"] is True
