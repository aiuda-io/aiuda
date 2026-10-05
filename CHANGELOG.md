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
- Del catálogo visible, hasta probarlas con una cuenta real: Mercado Pago, Clip,
  Conekta y la API oficial de WhatsApp Business. El código y sus pruebas se
  quedan, y quien ya tenga una conectada la sigue viendo.

### Agregado

- Entrar con ChatGPT: usar tu plan de ChatGPT como la IA de tus ayudantes por el
  flujo oficial de OpenAI para programas abiertos que corren en tu computadora.
  aiuda se registra con su propio nombre. Sin estrenar: probada contra un
  servidor de pruebas, todavía no con una cuenta real.
- Sello "Sin estrenar" en cada integración que nadie ha usado todavía con una
  cuenta real. Hoy están estrenadas Odoo, Excel/CSV y WhatsApp con tu número.
- Aviso en el Centro de mando cuando la IA se pausa por el tope de gasto del mes.
- App de iPhone (repo aparte): se empareja por QR en la red de la oficina. Aún no
  está en la App Store.

- Runtime local-first: un proceso, un puerto, SQLite y scheduler integrado.
- App de escritorio Tauri con el servidor y la consola estática embebidos.
- Ayudantes configurables con propuestas, aprobación humana y bitácora.
- Cobranza, conversaciones, conciliación bancaria y write-back con procedencia.
- Proveedor de IA propio: Claude, OpenAI/Codex u OpenAI-compatible local.
- Integraciones cifradas, conectores a la medida y catálogo por capacidades.
- Acceso opcional de aparatos en la red local, con permisos y topes.
- Bóveda SAT para hasta tres RFCs: XML/ZIP, e.firma cifrada, Descarga Masiva,
  PPD/PUE, pagos, egresos, deduplicación e intercompañía.
- Manual sin conexión generado desde `docs/`.
- Builds de wheels y del instalador para macOS (aiuda se reparte solo para Mac).

### Cambiado

- Consola legible para quien no es técnico: escala tipográfica semántica de siete
  niveles con el cuerpo en 15px como piso, en lugar de 1012 tamaños clavados en
  píxeles (el más chico, de 9px). Integraciones deja de plegar sus diez
  necesidades: las opciones se ven sin dar un clic.

### Seguridad

- Token nuevo por arranque para la consola local.
- Llave Fernet separada de la base y credenciales nunca devueltas por el API.
- Permisos cerrados por default para aparatos invitados.
- Acciones sensibles sujetas a aprobación y registradas por aparato.

### Pendiente antes de 0.1.0

- Verificar autenticación y descarga completa contra el SAT vivo.
- Firmar con Developer ID y notarizar el instalador de macOS.
