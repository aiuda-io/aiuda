"""Runtimes de los aiudantes de referencia. Regla dura en todos: PROPONEN, el
humano aprueba (HITL); las tools de chat son SOLO LECTURA.

Qué puede PROPONER cada uno (proponer, nunca ejecutar sin humano):

  - cleo/ (Mariana, cobranza — la referencia): recordatorios de cobro
    (pending_approval en la bandeja); en la conversación con el deudor, registrar
    promesas de pago y pagos REPORTADOS (la factura no se cierra sola). Chat:
    consultar_cartera (lectura).
  - carlos/ (ventas): cotizaciones con precios reales del catálogo
    (pending_approval en la bandeja). Chat: consultar_catalogo, consultar_cliente
    (lectura).
  - diego/ (conciliación): el match depósito-factura con su razón
    (engine/reconcile.propose_matches); el humano confirma en /conciliacion.
    Chat: consultar_pagos (lectura). No redacta: propone matches, no mensajes.
  - valeria/ (recepción): nada todavía — solo consulta (consultar_agenda,
    buscar_cita). Agendar citas sigue "por conectar" en el catálogo.

Los ayudantes que el dueño CREA (modelo Ayudante) no tienen runtime propio: sus
aiuditas activas se ejecutan sobre estos runtimes (aiuditas/chat.py para el chat,
CleoEngine/CarlosEngine para proponer), con su config, sus reglas y su atribución
(meta.ayudante_id), que alimenta su plan de carrera (aiuda_core/carrera.py).
"""
