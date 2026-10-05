# Changelog

Formato: [Keep a Changelog](https://keepachangelog.com/es/1.1.0/). Versionado:
[SemVer](https://semver.org/lang/es/).

## [Sin publicar]

Todavía no hay ninguna versión publicada: todo lo de abajo es lo que trae el
código hoy.

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
  modelo local y, nueva, Entrar con ChatGPT (ver Agregado).
- Del catálogo visible, hasta probarlas con una cuenta real: todos los conectores
  de pago (Stripe, Belvo, Mercado Pago, Clip y Conekta) y la API oficial de
  WhatsApp Business. El código y sus pruebas se quedan, y quien ya tenga una
  conectada la sigue viendo.

### Agregado

- Entrar con ChatGPT: usar tu plan de ChatGPT como la IA de tus ayudantes por el
  flujo oficial de OpenAI para programas abiertos que corren en tu computadora.
  aiuda se registra con su propio nombre. Sin estrenar: probada contra un
  servidor de pruebas, todavía no con una cuenta real.
- Sello "Sin estrenar" en cada integración que nadie ha usado todavía con una
  cuenta real. Hoy están estrenadas Odoo, Excel/CSV, WhatsApp con tu número y el SAT con
  e.firma.
- SAT: aiuda revisa una vez al día qué facturas tuyas se cancelaron en el SAT,
  las saca de la cartera y retira sus recordatorios pendientes.
- Portales sin IA para el SAT: bajar la opinión de cumplimiento (32-D) y la
  constancia de situación fiscal en PDF con la e.firma guardada, con tu permiso
  una vez por RFC. Estrenadas contra el SAT real el 5 de octubre de 2026 (una
  opinión Positiva y una constancia, con una e.firma). La app de escritorio
  todavía no trae el navegador que usan.
- Aviso en Hoy cuando la IA se pausa por el tope de gasto del mes.
- Una promesa de pago vencida se puede dar por incumplida ("No cumplió") sin
  registrar un pago: sale de Hoy y la factura se sigue cobrando.
- Al registrar o conciliar un pago, aiuda lo manda a su sistema de origen en ese
  momento y dice si llegó; antes esperaba a la revisión de cada hora.
- App de iPhone (repo aparte): se empareja por QR en la red de la oficina. Aún no
  está en la App Store.

- Runtime local-first: un proceso, un puerto, SQLite y scheduler integrado.
- App de escritorio Tauri con el servidor y la consola estática embebidos.
- Ayudantes configurables con propuestas, aprobación humana y bitácora.
- Cobranza, conversaciones, conciliación bancaria y write-back con procedencia.
- Tu IA propia: Claude, OpenAI/Codex u OpenAI-compatible local.
- Conexiones cifradas, conectores a la medida y catálogo por capacidades.
- Acceso opcional de aparatos en la red local, con permisos y topes.
- Bóveda SAT para hasta tres RFCs: XML/ZIP, e.firma cifrada, Descarga Masiva,
  PPD/PUE, pagos, egresos, deduplicación e intercompañía.
- Manual sin conexión generado desde `docs/`.
- Builds de wheels y del instalador para macOS (aiuda se reparte solo para Mac).

### Cambiado

- Consola legible para quien no es técnico: escala tipográfica semántica de siete
  niveles con el cuerpo en 15px como piso, en lugar de 1012 tamaños clavados en
  píxeles (el más chico, de 9px).
- La consola se reorganizó en seis destinos: Hoy (el inicio y la pantalla de
  trabajo, antes Centro de mando, Aprobaciones y Resumen), Cartera (Facturas,
  Promesas y Pagos en una sola pantalla), Mensajes (antes Conversaciones),
  Clientes, Ayudantes (con Portales, antes Rutinas) y Ajustes (Negocio,
  Conexiones, Tu IA, Teléfono y equipo). Las direcciones viejas siguen llegando.
- Dirección visual "Atelier claro": jerarquía por tamaño y peso, rayas finas en
  vez de fichas grises, un solo botón relleno por pantalla.
- Pesos y dólares ya no se suman en ninguna cifra: cartera, clientes y SAT dicen
  cada moneda por separado.
- Toda instalación nueva nace en modo de prueba. Apagarlo pregunta qué hacer con
  lo ya aprobado, desde Ajustes y desde la franja.

### Corregido

- Las horas de la consola salían seis horas adelantadas (el servidor manda UTC).
- Un recordatorio aprobado de una factura que después se pagó ya no puede salir.
- Con una base de pruebas (`AIUDA_DATABASE_URL`) y el HOME real, aiuda podía
  tomar la sesión de WhatsApp del dueño en `~/.wacli`. Una base que no es la del
  dueño ya nunca usa ese store.

### Seguridad

- Token nuevo por arranque para la consola local.
- Llave Fernet separada de la base y credenciales nunca devueltas por el API.
- Permisos cerrados por default para aparatos invitados.
- Acciones sensibles sujetas a aprobación y registradas por aparato.

### Pendiente antes de 0.1.0

- SAT: probar en vivo complementos de pago y notas de crédito emitidos, y un
  periodo de más de un paquete.
- Firmar con Developer ID y notarizar el instalador de macOS.
