# Changelog

Formato: [Keep a Changelog](https://keepachangelog.com/es/1.1.0/). Versionado:
[SemVer](https://semver.org/lang/es/).

## [Sin publicar]

## [0.1.0-alpha.2] - 2026-10-06

Segundo corte alfa. Todavía no hay ninguna versión publicada ni firmada por
Apple: todo lo de abajo es lo que trae el código en este corte.

### Agregado

La base:

- Runtime local-first: un proceso, un puerto, SQLite y scheduler integrado.
- App de escritorio Tauri con el servidor y la consola estática embebidos.
- Ayudantes configurables con propuestas, aprobación humana y bitácora.
- Cobranza, mensajes, conciliación bancaria y write-back con procedencia.
- Tu IA propia: tu llave (Claude u OpenAI), el Claude Code o Codex que ya tienes
  instalado, o un modelo local compatible con OpenAI.
- Conexiones cifradas, conectores a la medida y catálogo por capacidades.
- Acceso opcional de aparatos en la red local, con permisos y topes.
- Bóveda SAT para hasta tres RFCs: XML/ZIP, e.firma cifrada, Descarga Masiva,
  PPD/PUE, pagos, egresos, deduplicación e intercompañía.
- Manual sin conexión generado desde `docs/`.
- Builds de wheels y del instalador para macOS.

La consola de este corte:

- Menú de seis destinos: Hoy, Cartera, Mensajes, Clientes, Ayudantes y Ajustes.
  Productos y Agenda aparecen solo si hay un ayudante de Ventas o de Recepción.
  El menú, el buscador y el "Volver a" salen de una sola lista.
- Hoy, el inicio y la pantalla de trabajo: en una lista, lo que tus ayudantes
  redactaron y espera tu aprobación, las promesas vencidas, los pagos por
  confirmar y lo que no salió. Actividad es el historial que queda detrás.
- Cartera con pestañas: Facturas, Promesas y Pagos en una sola pantalla, con las
  acciones en el panel de cada factura.
- Ajustes en cuatro secciones: Negocio, Conexiones, Tu IA y Teléfono y equipo.
- Portales, dentro de Ayudantes: organizado alrededor de los documentos del SAT,
  y dice cuándo no está disponible en esta instalación.
- Modo de prueba de fábrica: toda instalación nueva nace con él prendido y nada
  sale a un cliente real hasta apagarlo. Una franja lo dice en toda la consola;
  se apaga ahí mismo o desde Ajustes, y aiuda pregunta qué hacer con lo ya
  aprobado.
- Asistente de primer arranque rehecho: nombre del negocio, tu IA y tu cartera
  sin salir de él.
- Clientes y prospectos en una sola lista, con las etiquetas administradas ahí.
- La ficha del ayudante dice qué hace cada tarea, cuándo y si pide aprobación.
- Cambiar la llave o el modelo de tu IA sin desconectarla.
- Aviso en Hoy cuando la IA se pausa por el tope de gasto del mes.

Lo demás:

- Entrar con ChatGPT: usar tu plan de ChatGPT como la IA de tus ayudantes por el
  flujo oficial de OpenAI para programas abiertos que corren en tu computadora.
  aiuda se registra con su propio nombre. Sin estrenar: probada contra un
  servidor de pruebas, todavía no con una cuenta real.
- Sello "Sin estrenar" en cada integración que nadie ha usado todavía con una
  cuenta real. Hoy están estrenadas Odoo, Excel/CSV, WhatsApp con tu número y el
  SAT con e.firma.
- WhatsApp con tu número sin terminal: la consola instala el conector con un
  clic y el servidor mantiene viva la sesión. Solo se atiende a los clientes del
  negocio y al dueño; lo de cualquier otro número no se lee ni se guarda.
- Al registrar o conciliar un pago, aiuda lo manda a su sistema de origen (Odoo,
  por ejemplo) en ese momento y dice si llegó; antes esperaba a la revisión de
  cada hora. Registrar un pago pide confirmación.
- Una promesa de pago vencida se puede dar por incumplida ("No cumplió") sin
  registrar un pago: sale de Hoy y la factura se sigue cobrando.
- SAT: aiuda revisa una vez al día qué facturas tuyas se cancelaron en el SAT,
  las saca de la cartera y retira sus recordatorios pendientes.
- Portales sin IA para el SAT: bajar la opinión de cumplimiento (32-D) y la
  constancia de situación fiscal en PDF con la e.firma guardada, con tu permiso
  una vez por RFC. Estrenadas contra el SAT real el 5 de octubre de 2026 (una
  opinión Positiva y una constancia, con una e.firma). La app de escritorio
  todavía no trae el navegador que usan.
- App de iPhone (repo aparte): se empareja por QR en la red de la oficina. Aún no
  está en la App Store.
- Página pública nueva (`landing/`): rehecha con capturas de la consola de hoy,
  la página "Cómo funciona" con los cinco pasos reales y la imagen social al día.

### Cambiado

- Dirección visual "Atelier claro": jerarquía por tamaño y peso, rayas finas en
  vez de fichas grises, un solo botón relleno por pantalla.
- Consola legible para quien no es técnico: escala tipográfica semántica de siete
  niveles con el cuerpo en 15px como piso, en lugar de 1012 tamaños clavados en
  píxeles (el más chico, de 9px).
- Los nombres de las pantallas: Hoy reemplaza a Centro de mando, Aprobaciones y
  Resumen; Mensajes a Conversaciones; Portales a Rutinas; y Ajustes junta
  Configuración, Integraciones, Tu IA y Tus aparatos. Las direcciones viejas
  siguen llegando.
- Pesos y dólares separados: ninguna cifra suma monedas distintas. Cartera,
  clientes, SAT y Hoy dicen cada moneda por su lado.
- En teléfono, todo lo que se toca mide al menos 44 px y las pestañas caben.
- Una conexión dice "Conectado" solo con credenciales guardadas o una sesión
  viva.
- El binario de la app pesa menos: ya no arrastra tres paquetes que nunca usaba.

### Corregido

- Las horas de la consola salían seis horas adelantadas (el servidor manda UTC).
- Un recordatorio aprobado de una factura que después se pagó o se canceló ya no
  puede salir, y sus promesas se dan por cumplidas.
- Con una base de pruebas (`AIUDA_DATABASE_URL`) y el HOME real, aiuda podía
  tomar la sesión de WhatsApp del dueño en `~/.wacli`. Una base que no es la del
  dueño ya nunca usa ese store.
- Codex ya trabaja aunque aiuda no corra dentro de un repositorio de git.
- Los velos de paneles y diálogos cubren toda la ventana.

### Retirado

- Windows y Linux: aiuda se reparte solo para Mac.
- Docker y Postgres: aiuda corre solo sobre SQLite local.
- El servidor MCP y la página de API: aiuda es su propia app.
- El conector de Slack y los avisos al equipo por ese canal.
- El canal de voz por Twilio.
- El conector de generación de imágenes y su capacidad.
- Evolution, el conector legado de WhatsApp.
- Prospección y el conector DENUE.
- Los perfiles de ayudante que no tenían ninguna capacidad viva.
- La pantalla "Datos del negocio", que nunca tuvo servidor detrás.
- El modo suscripción de la IA, que se hacía pasar por el programa oficial del
  proveedor. Quedan tu llave, el Claude Code o Codex que ya tienes instalado, un
  modelo local y Entrar con ChatGPT.
- Del catálogo visible, hasta probarlas con una cuenta real: todos los conectores
  de pago (Stripe, Belvo, Mercado Pago, Clip y Conekta) y la API oficial de
  WhatsApp Business. El código y sus pruebas se quedan, y quien ya tenga una
  conectada la sigue viendo.
- Cinco rutas del API que ya no usaba ninguna pantalla, ni la CLI, ni el iPhone:
  los sistemas de un ayudante, el estado de activación, la lista de portales a
  la medida, cambiar el papel de un aparato ya emparejado y la importación en un
  solo paso (queda la de dos pasos, que es la que usa la consola).
- Tres guiones de demostración de `scripts/` que ya no corrían.

### Seguridad

- Token nuevo por arranque para la consola local.
- Llave Fernet separada de la base y credenciales nunca devueltas por el API.
- Permisos cerrados por default para aparatos invitados.
- Acciones sensibles sujetas a aprobación y registradas por aparato.
- Las pruebas de punta a punta de `scripts/` corren sobre una casa desechable:
  ya no dejan ni borran nada en `~/.aiuda`.

### Pendiente antes de 0.1.0

- SAT: probar en vivo complementos de pago y notas de crédito emitidos, y un
  periodo de más de un paquete.
- Firmar con Developer ID y notarizar el instalador de macOS.
