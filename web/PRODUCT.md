# PRODUCT.md: aiuda Consola

register: product

## Qué es

Consola web de aiuda: plataforma para crear tu propio ayudante de IA, potenciado por tu
propia IA, para PyMEs mexicanas. La primera capacidad activa es cobranza: el ayudante
redacta recordatorios de pago por WhatsApp con tono graduado por atraso; el dueño aprueba
antes de cualquier envío (HITL).

## Cómo está armada

Seis puertas, en un menú plano: **Hoy** (lo que espera tu aprobación, y donde abre la
consola), **Cartera** (con Promesas y Pagos como pestañas), **Mensajes**, **Clientes**,
**Ayudantes** y **Ajustes** (Negocio, Conexiones, Tu IA, Teléfono y equipo). Productos y
Agenda aparecen solo cuando existe un ayudante de Ventas o de Recepción. Un lugar tiene un
solo nombre, y el menú, el buscador y el "Volver a" lo dicen igual: la lista vive en
`lib/sections.ts`. Nada sale del menú sin una puerta visible en otra pantalla.

## Usuarios

Dueños y administradores de PyMEs mexicanas (5 a 50 empleados) y despachos legales/fiscales.
No técnicos. Revisan la consola en laptop durante el día de trabajo. En el teléfono usan
la app de iPhone (repo aparte): se empareja por QR dentro de la red de la oficina y sirve
para ver el negocio y aprobar; todavía no está en la App Store. Fuera de la oficina, su
canal móvil sigue siendo WhatsApp. Confían su dinero y la relación con SUS clientes a su ayudante: la
interfaz debe sentirse seria, precisa y sin teatro.

## Tono

Profesional cálido en español mexicano. Directo, sin anglicismos innecesarios. Los números
son el contenido principal: siempre exactos, siempre alineados.

## Anti-referencias

- Dashboards de template SaaS (hero metrics con gradiente, tarjetas con glow, blur orbs).
- Chats juguetones o animaciones que distraigan (la consola es seria; la mascota es solo el avatar del ayudante, no un personaje que hable).
- Lo "enterprise gris" tipo SAP: denso está bien, hostil no.

## Principios

1. Confianza antes que delicia: el dueño aprueba dinero aquí.
2. Lo que tu ayudante hizo y va a hacer siempre es visible y explicable.
3. Serena antes que densa: una pantalla, un trabajo, un botón relleno. La jerarquía la
   da la letra, no las cajas (ver `DESIGN.md`).
4. Solo se enseña lo que corre. Lo planeado no se pinta, y la integración que nadie ha
   usado todavía con una cuenta real lleva el sello "Sin estrenar".
