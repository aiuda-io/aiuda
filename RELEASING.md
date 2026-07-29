# Cómo se libera aiuda

Todo release sale de este repo, con estos comandos. No hay pasos secretos.

Se publican dos cosas distintas:

- **Wheels** (`aiuda-core` y `aiuda-server`) para quien instala con Python.
- **Instaladores de escritorio** (.dmg y .app, .exe de NSIS, .deb y .AppImage)
  para quien no quiere terminal.

## Versión

La misma versión en cinco archivos, más el changelog:

- `core/pyproject.toml`
- `server/pyproject.toml`
- `desktop/src-tauri/tauri.conf.json`
- `desktop/src-tauri/Cargo.toml`
- `desktop/package.json`
- `CHANGELOG.md`

El `pyproject.toml` de la raíz no se publica (es solo el workspace).

## Wheels

La consola viaja DENTRO del wheel del server, para que el usuario no necesite
Node. El manual del dueño va con ella: `npm run export` arma primero
`web/public/manual/` desde `docs/` (`web/scripts/manual.mjs`) y el export lo
lleva a `out/`. No hay paso aparte que se pueda olvidar. Por eso el export va
primero:

```sh
cd web && npm ci && npm run export && cd ..
rm -rf server/aiuda_server/static && cp -R web/out server/aiuda_server/static
uv build --package aiuda-core   --wheel -o dist
uv build --package aiuda-server --wheel -o dist   # embebe la consola copiada
```

Probarlo como lo recibiría un usuario:

```sh
uv tool install --with dist/aiuda_core-*.whl dist/aiuda_server-*.whl
aiuda doctor && aiuda start
uv tool uninstall aiuda-server
```

Sobre PyPI: el nombre `aiuda` ya está tomado por otro proyecto, así que el
comando no va a ser `uvx aiuda` sino `uvx --from aiuda-server aiuda`. Todavía no
publicamos nada.

## Instaladores de escritorio

```sh
scripts/build-app.sh
```

Hace las cuatro etapas: exporta la consola, la copia al paquete del server,
arma el binario único con PyInstaller (`packaging/aiuda.spec`) y construye la app
con Tauri usando ese binario como sidecar. Salida en
`desktop/src-tauri/target/release/bundle/`.

Requisitos: node, uv y Rust. Playwright no viaja en el binario (pesa cientos de
MB), así que la app no trae el CUA.

## Firma en macOS

Antes de repartir un `.dmg`, revísalo con la misma herramienta que usa Apple:

```sh
scripts/prueba-app.sh          # incluye el veredicto de syspolicy_check
```

Hoy sale con **firma ad-hoc**: la firma es válida y sella el contenido, pero no
tiene identidad. macOS dirá que el desarrollador no está identificado y se abre
con clic derecho > Abrir, sin escribir nada en una terminal. Falta el ticket de
notarización, que **solo se consigue con cuenta de Apple Developer**.

La diferencia importa y costó encontrarla: hasta el 27 de julio de 2026 el
paquete salía con la firma que deja el enlazador de Rust y **sin sellar sus
recursos**. Para macOS eso no es "sin firmar" sino **dañado**: `syspolicy_check`
lo marcaba fatal, el sistema mataba el proceso al arrancar con el bit de
cuarentena, y el truco de clic derecho > Abrir no lo salvaba. Lo que faltaba era
`bundle.macOS.signingIdentity` en `tauri.conf.json`: sin esa llave Tauri no firma
nada.

El hardened runtime va prendido porque Apple lo exige para notarizar, y bloquea
tres cosas que el server sí necesita (viaja empaquetado con PyInstaller). Esos
permisos están en `desktop/src-tauri/entitlements.plist`, uno por uno y con su
motivo.

Cuando existan los certificados, se agregan como secrets del repo y
`release.yml` los usa sin cambiar nada más; los nombres están anotados ahí.
Después de un release firmado, `codesign -dv` debe decir Developer ID y no adhoc.

En Windows los instaladores siguen sin firmar: SmartScreen mostrará su aviso.

## Publicar

1. Subir la versión en los cinco archivos de arriba.
2. Commit, tag `vX.Y.Z`, push del tag.
3. `.github/workflows/release.yml` se dispara: construye los instaladores para
   macOS (arm64 e Intel), Windows y Linux, crea el GitHub Release en **borrador**
   con ellos, y arma los wheels (los publica a PyPI si existe el secret
   `PYPI_TOKEN`).
4. Revisar el borrador, pegar las notas del changelog y publicarlo.

`.github/workflows/ci.yml` construye los mismos wheels en cada push y PR: el
artefacto `wheels` de un run verde es exactamente lo publicable.

Lo que hoy no existe: auto-update de la app y notarización. Cada versión nueva se
descarga a mano.

## Cadencia

La que aguante la realidad: se libera cuando hay algo terminado y probado, no por
calendario. Sin telemetría, las únicas señales de adopción son los issues y las
descargas.
