# Cuando algo falla

Busca aquí tu caso. Están de lo que más pasa a lo que menos, y casi todos se
arreglan sin salir de la consola.

Una nota honesta que ahorra tiempo: aiuda todavía **no tiene una pantalla** que
te diga de un vistazo qué está listo y qué falta. Ese chequeo hoy solo existe
como comando de terminal, al final de este documento. Es un pendiente.

## Lo que pasa seguido

**La app abre una ventana que dice "aiuda no pudo arrancar".**
Casi siempre es el puerto 4747 ocupado por otra copia de aiuda. Ciérrala y
vuelve a abrir. Si fue el primer arranque, pudo tardar de más creando la base:
abrir otra vez suele bastar. Tus datos no se tocan.

**La consola no abre y dice que no hay export.**
Falta construir la consola una vez: `cd web && npm ci && npm run export`. Sin
eso el API corre pero la raíz no tiene qué servir.

**"Esta ventana no tiene la llave de tu sesión".**
Cada arranque genera un token y la consola se abre con él. Si llegaste con una
URL vieja o desde otro navegador, cierra esa pestaña y abre la app otra vez (o
corre `aiuda start`, que abre el navegador con la llave del momento).

**El ayudante no redacta nada.**
Puede ser que no haya IA conectada (`aiuda doctor` lo dice), que el tope mensual
de tokens que te pusiste ya se haya agotado (la bitácora deja el aviso), o que
el modelo local elegido no soporte tool calling. Ver [IA.md](IA.md).

**Al conectar Codex sale `env: node: No such file or directory`.**
Era un defecto nuestro, arreglado el 27 de julio de 2026. Codex por dentro
necesita Node, y una app abierta desde el Finder arranca sin saber dónde vive.
Actualiza aiuda. Si lo sigues viendo, es información útil para un issue.

**La primera respuesta de la IA tarda mucho.**
Con Claude Code o Codex, la primera llamada arranca el programa y revisa tu
sesión antes de contestar. Las siguientes son más rápidas. No está trabado.

**El modelo local responde lento o traba la computadora.**
El modelo no le queda a este equipo. Baja a uno más chico: el asistente de
primer arranque te dice cuál te queda bien.

**No entra la cartera desde Odoo.**
Revisa la credencial en la consola y usa "Probar conexión": el error que
devuelve es el del servidor de Odoo, tal cual. Cada dato importado guarda su
procedencia, así que en la ficha se ve de dónde vino y cuándo.

**WhatsApp no envía.**
El envío usa wacli, que se pelea consigo mismo si tienes un `wacli sync
--follow` retenido en el store. El envío espera el lock unos segundos y si no lo
suelta, falla. Cierra el sync y reintenta.

**"No se pudo descifrar" o 409 al guardar una credencial.**
La llave con la que se guardó ese secreto ya no está. Si tienes respaldo de
`~/.aiuda/key`, restáuralo; si no, vuelve a capturar la credencial en la
consola. No hay puerta trasera. Ver [DATOS.md](DATOS.md).

**El CUA dice que falta el navegador.**
Es opcional y no viaja en la app de escritorio. Desde el repo:
`uv sync --extra cua && .venv/bin/playwright install chromium`.

**macOS dice que el desarrollador no está identificado.**
La app sí está firmada, pero con una firma sin identidad: falta el certificado
de Apple y, con él, la notarización. Se abre con clic derecho y luego **Abrir**,
solo la primera vez. Los pasos están en [INSTALAR.md](INSTALAR.md).

**macOS dice que aiuda "está dañada y no se puede abrir".**
Si tu instalador es de antes del 27 de julio de 2026, es ese defecto: el paquete
salía firmado a medias y macOS lo trataba como dañado. Bájalo otra vez. Con un
instalador nuevo, ese mensaje significa que el archivo se corrompió al
descargarse.

**Mi teléfono no encuentra esta computadora.**
Primero: hoy **no existe todavía la app del teléfono**, así que el emparejamiento
no se completa por más que todo lo demás esté bien. Cuando exista, la causa
número uno en Mac es el permiso de red local. Está explicado con sus pasos en
[APARATOS.md](APARATOS.md).

## El chequeo completo (necesita terminal)

`aiuda doctor` revisa la instalación y dice en una línea qué está listo y qué
falta. No manda nada a ningún lado. Si no usas terminal, sáltate esta parte o
pídele a quien te ayuda con la computadora que la corra.

```sh
uv run aiuda doctor                                          # desde el repo
/Applications/aiuda.app/Contents/MacOS/aiuda-server doctor   # desde la app en macOS
```

Ejemplo de salida:

```
aiuda doctor (0.1.0)
  [ok] Carpeta de datos: /Users/tu/.aiuda
  [ok] Base de datos: /Users/tu/.aiuda/aiuda.db
  [ok] Llave de cifrado: /Users/tu/.aiuda/key
  [--] Proveedor de IA: sin conectar, hazlo en la consola (/proveedor)
  [ok] Claude Code / Codex instalados: claude, conéctalos con un clic en la consola
  [ok] Ollama (IA local): respondiendo (200)
  [ok] Consola: .../aiuda_server/static
  [--] CUA (Playwright/Chromium): el navegador del asistente no está instalado
  [ok] wacli (WhatsApp local): /opt/homebrew/bin/wacli
```

`[--]` no siempre es un problema: los CLIs, Ollama, el CUA y wacli son
opcionales. Lo que sí importa es que la carpeta de datos, la base y la llave
digan `[ok]`, y que haya un proveedor de IA si esperas que el ayudante redacte.

## Si nada de eso aplica

- Corre `aiuda start` desde la terminal en vez de la app: ahí ves los errores
  completos.
- Abre un issue en https://github.com/aiuda-io/aiuda/issues con lo que salió de
  `aiuda doctor`, tu sistema operativo y qué estabas haciendo. Quita nombres,
  teléfonos y llaves antes de pegar nada.
- Si lo que encontraste es una vulnerabilidad, no abras un issue público: sigue
  [SECURITY.md](../SECURITY.md).
