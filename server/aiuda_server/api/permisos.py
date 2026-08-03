"""Quién entra a cada endpoint cuando la petición viene de un APARATO.

Regla invertida y CERRADA por default: un aparato invitado solo toca lo que está
declarado en ``INVITADO`` (leer el negocio y el trabajo del día: aprobar,
rechazar, conciliar, cumplir promesas). Todo lo demás es del dueño — incluida
cualquier ruta NUEVA que todavía no aparezca aquí. Antes la regla era al revés
(una lista de prefijos prohibidos y el resto abierto): cada router nuevo quedaba
accesible al invitado por accidente.

Agregar un endpoint OBLIGA a decidir quién entra: la prueba
``server/tests/test_permisos.py`` truena si una ruta /v1 no está declarada (o si
se declara una que ya no existe). El dueño (consola local o su aparato) entra a
todo; los montos los sigue validando cada endpoint (``puede_aprobar``) y los
roles finos ``require_role``/``solo_el_dueno`` — esto es la red de la puerta de
la red local, no el único candado.
"""

from __future__ import annotations

from starlette.routing import Match

# Lo que un aparato INVITADO sí puede tocar: lectura del negocio y trabajo del día.
INVITADO: frozenset[tuple[str, str]] = frozenset({
    ("GET", "/v1/aiuditas/catalog"),
    ("GET", "/v1/appointments"),
    ("GET", "/v1/ayudantes"),
    ("GET", "/v1/ayudantes/{ayudante_id}"),
    ("GET", "/v1/ayudantes/{ayudante_id}/systems"),
    ("GET", "/v1/cartera"),
    ("GET", "/v1/conversations"),
    ("GET", "/v1/conversations/{conversation_id}"),
    ("GET", "/v1/customers"),
    ("GET", "/v1/customers/{customer_id}"),
    ("GET", "/v1/dispositivos/yo"),
    ("GET", "/v1/invoices"),
    ("GET", "/v1/invoices/{invoice_id}"),
    ("GET", "/v1/invoices/{invoice_id}/cfdi.pdf"),
    ("GET", "/v1/invoices/{invoice_id}/cfdi.xml"),
    ("GET", "/v1/learning/summary"),
    ("GET", "/v1/products"),
    ("GET", "/v1/promises"),
    ("GET", "/v1/reconciliation"),
    ("GET", "/v1/reconciliation/resueltos"),
    ("GET", "/v1/reminders"),
    ("GET", "/v1/search"),
    ("GET", "/v1/tags"),
    ("GET", "/v1/usage"),
    ("GET", "/v1/workspace"),
    ("POST", "/v1/invoices/{invoice_id}/pay"),
    ("POST", "/v1/promises/{promise_id}/fulfill"),
    ("POST", "/v1/reconciliation/{payment_id}/confirm"),
    ("POST", "/v1/reconciliation/{payment_id}/ignore"),
    ("POST", "/v1/reminders/{reminder_id}/approve"),
    ("POST", "/v1/reminders/{reminder_id}/reject"),
    ("POST", "/v1/reminders/{reminder_id}/send"),
})

# Todo lo demás: solo el dueño. Enumerado a propósito (nada queda sin declarar).
DUENO: frozenset[tuple[str, str]] = frozenset({
    ("DELETE", "/v1/ayudantes/{ayudante_id}"),
    ("DELETE", "/v1/ayudantes/{ayudante_id}/aiuditas/{aiudita_id}"),
    ("DELETE", "/v1/cua/portales/{portal_id}"),
    ("DELETE", "/v1/cua/rutinas/{rutina_id}"),
    ("DELETE", "/v1/custom-connectors/{cid}"),
    ("DELETE", "/v1/dispositivos/invitacion"),
    ("DELETE", "/v1/integrations/whatsapp/session"),
    ("DELETE", "/v1/integrations/{key}/config"),
    ("DELETE", "/v1/provider"),
    ("DELETE", "/v1/sat/efirma/{rfc}"),
    ("DELETE", "/v1/sat/empresas/{rfc}"),
    ("DELETE", "/v1/tags/{tag_id}"),
    ("GET", "/v1/audit"),
    ("GET", "/v1/ayudantes/{ayudante_id}/prompt"),
    ("GET", "/v1/cua/capacidades"),
    ("GET", "/v1/cua/estado"),
    ("GET", "/v1/cua/misiones"),
    ("GET", "/v1/cua/misiones/{mission_id}"),
    ("GET", "/v1/cua/portales"),
    ("GET", "/v1/cua/rutinas"),
    ("GET", "/v1/cua/sesion/{session_id}"),
    ("GET", "/v1/custom-connectors"),
    ("GET", "/v1/custom-connectors/fields"),
    ("GET", "/v1/custom-connectors/{cid}/receta"),
    ("GET", "/v1/dispositivos"),
    ("GET", "/v1/export/{entidad}.xlsx"),
    ("GET", "/v1/integrations"),
    ("GET", "/v1/integrations/whatsapp/status"),
    ("GET", "/v1/integrations/{key}"),
    ("GET", "/v1/integrations/{key}/config"),
    ("GET", "/v1/inyectar/destinos"),
    ("GET", "/v1/objects/{tipo}/source"),
    ("GET", "/v1/onboarding/state"),
    ("GET", "/v1/prospeccion/fuente"),
    ("GET", "/v1/provider"),
    ("GET", "/v1/reconciliation/config"),
    ("GET", "/v1/red-local"),
    ("GET", "/v1/sat/boveda"),
    ("GET", "/v1/sat/estado"),
    ("GET", "/v1/settings/contexto"),
    ("GET", "/v1/settings/modo-sombra"),
    ("GET", "/v1/settings/ventana-envio"),
    ("GET", "/v1/setup/estado"),
    ("GET", "/v1/setup/maquina"),
    ("GET", "/v1/setup/modelo/progreso"),
    ("GET", "/v1/webhooks/whatsapp-cloud"),
    ("GET", "/v1/writeback"),
    ("PATCH", "/v1/sat/empresas/{rfc}"),
    ("PATCH", "/v1/dispositivos/{dispositivo_id}"),
    ("POST", "/v1/appointments"),
    ("POST", "/v1/ayudantes"),
    ("POST", "/v1/banco/analizar"),
    ("POST", "/v1/banco/importar"),
    ("POST", "/v1/ayudantes/{ayudante_id}/chat"),
    ("POST", "/v1/ayudantes/{ayudante_id}/correr"),
    ("POST", "/v1/cobro/link"),
    ("POST", "/v1/conversations/{conversation_id}/dismiss"),
    ("POST", "/v1/conversations/{conversation_id}/messages"),
    ("POST", "/v1/conversations/{conversation_id}/messages/{message_id}/resend"),
    ("POST", "/v1/conversations/{conversation_id}/registrar-cliente"),
    ("POST", "/v1/conversations/{conversation_id}/takeover"),
    ("POST", "/v1/conversations/{conversation_id}/undismiss"),
    ("POST", "/v1/cua/misiones"),
    ("POST", "/v1/cua/portales"),
    ("POST", "/v1/cua/rutinas"),
    ("POST", "/v1/cua/sesion"),
    ("POST", "/v1/cua/sesion/olvidar"),
    ("POST", "/v1/cua/sesion/{session_id}/cancelar"),
    ("POST", "/v1/cua/sesion/{session_id}/confirmar"),
    ("POST", "/v1/custom-connectors"),
    ("POST", "/v1/custom-connectors/importar"),
    ("POST", "/v1/custom-connectors/test"),
    ("POST", "/v1/custom-connectors/{cid}/test"),
    ("POST", "/v1/customers"),
    ("POST", "/v1/customers/{customer_id}/attachments"),
    ("POST", "/v1/customers/{customer_id}/messages"),
    ("POST", "/v1/customers/{customer_id}/optout"),
    ("POST", "/v1/daily/run"),
    ("POST", "/v1/dispositivos/invitacion"),
    ("POST", "/v1/dispositivos/{dispositivo_id}/revocar"),
    ("POST", "/v1/emparejar"),
    ("POST", "/v1/import"),
    ("POST", "/v1/import/analyze"),
    ("POST", "/v1/import/commit"),
    ("POST", "/v1/integration-requests"),
    ("POST", "/v1/integrations/whatsapp-cloud/activate"),
    ("POST", "/v1/integrations/whatsapp/qr"),
    ("POST", "/v1/integrations/{key}/test"),
    ("POST", "/v1/invoices"),
    ("POST", "/v1/invoices/{invoice_id}/remind"),
    ("POST", "/v1/inyectar"),
    ("POST", "/v1/payments"),
    ("POST", "/v1/products"),
    ("POST", "/v1/prospeccion/buscar"),
    ("POST", "/v1/prospeccion/importar"),
    ("POST", "/v1/provider/test"),
    ("POST", "/v1/quotes"),
    ("POST", "/v1/sat/efirma"),
    ("POST", "/v1/sat/efirma/{rfc}/probar"),
    ("POST", "/v1/sat/empresas"),
    ("POST", "/v1/sat/importar"),
    ("POST", "/v1/setup/modelo/descargar"),
    ("POST", "/v1/setup/red/buscar"),
    ("POST", "/v1/setup/terminar"),
    ("POST", "/v1/sync"),
    ("POST", "/v1/tags"),
    ("POST", "/v1/webhooks/evolution"),
    ("POST", "/v1/webhooks/twilio-voz"),
    ("POST", "/v1/webhooks/wacli"),
    ("POST", "/v1/webhooks/whatsapp-cloud"),
    ("POST", "/v1/writeback/{entry_id}/retry"),
    ("PUT", "/v1/ayudantes/{ayudante_id}"),
    ("PUT", "/v1/ayudantes/{ayudante_id}/aiuditas/{aiudita_id}"),
    ("PUT", "/v1/cua/portales/builtin/{capacidad}"),
    ("PUT", "/v1/custom-connectors/{cid}"),
    ("PUT", "/v1/customers/{customer_id}"),
    ("PUT", "/v1/customers/{customer_id}/tags"),
    ("PUT", "/v1/integrations/{key}/capabilities"),
    ("PUT", "/v1/integrations/{key}/config"),
    ("PUT", "/v1/provider"),
    ("PUT", "/v1/reconciliation/config"),
    ("PUT", "/v1/red-local"),
    ("PUT", "/v1/settings/contexto"),
    ("PUT", "/v1/settings/modo-sombra"),
    ("PUT", "/v1/settings/ventana-envio"),
    ("PUT", "/v1/setup/negocio"),
    ("PUT", "/v1/tags/{tag_id}"),
})


PERMISOS: frozenset[tuple[str, str]] = INVITADO | DUENO


def _ruta_declarable(app, scope) -> str | None:
    """La PLANTILLA de la ruta que atendería esta petición (p.ej.
    ``/v1/reminders/{reminder_id}/approve``), o None si ninguna matchea. Se usa
    la plantilla y no la URL cruda para que el permiso se declare una vez por
    endpoint, no por cada id."""
    for route in app.router.routes:
        match, _ = route.matches(scope)
        if match == Match.FULL:
            return getattr(route, "path", None)
    return None


def invitado_puede(app, request) -> bool:
    """¿Este método+ruta está declarado como trabajo de invitado?

    Fuera de /v1 (la consola estática y el manual) un invitado solo lee. Una
    ruta /v1 no declarada está CERRADA: fallar cerrado es el punto."""
    metodo = "GET" if request.method == "HEAD" else request.method
    ruta = _ruta_declarable(app, request.scope)
    if ruta is None or not ruta.startswith("/v1"):
        return metodo in ("GET", "OPTIONS")
    return (metodo, ruta) in INVITADO
