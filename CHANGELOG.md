# Changelog

Formato: [Keep a Changelog](https://keepachangelog.com/es/1.1.0/). Versionado:
[SemVer](https://semver.org/lang/es/).

## [Unreleased]

### Agregado

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
- Builds de wheels e instaladores para macOS, Windows y Linux.

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
- Probar los instaladores de Windows y Linux en equipos reales.
