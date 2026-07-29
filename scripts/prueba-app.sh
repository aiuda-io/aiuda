#!/usr/bin/env bash
# Prueba de punta a punta del .dmg, como lo vive quien lo baja de internet.
#
#   scripts/prueba-app.sh                   # el .dmg ya construido
#   scripts/prueba-app.sh ruta/a/aiuda.dmg
#   scripts/prueba-app.sh --con-mi-ia       # además le presta tu Claude Code/Codex
#
# Corre sobre una CASA LIMPIA (un $HOME temporal): no toca ~/.aiuda, ni tu base,
# ni tus credenciales. Al terminar apaga la app, borra lo que creó y desmonta.
#
# Arranca la app con el entorno pelado con el que macOS abre una app desde el
# Finder (PATH sin Homebrew, sin ~/.local/bin, sin nvm). Ese fue el bug real:
# dentro del paquete no se puede confiar en el PATH.
#
# El veredicto de Gatekeeper lo da `syspolicy_check`, la misma herramienta de
# Apple que revisa una app antes de repartirla. Lo que NO puede decir esta prueba
# es qué ve una persona al hacer doble clic en el Finder de una Mac ajena: eso
# necesita una cuenta de usuario limpia y unos ojos.

set -uo pipefail
set +m   # sin avisos de "Terminated" del control de trabajos al apagar la app
cd "$(dirname "$0")/.."

PORT=4747
CON_MI_IA=false
DMG=""
for arg in "$@"; do
  case "$arg" in
    --con-mi-ia) CON_MI_IA=true ;;
    *) DMG="$arg" ;;
  esac
done
[ -z "$DMG" ] && DMG=$(ls -t desktop/src-tauri/target/release/bundle/dmg/*.dmg 2>/dev/null | head -1)

# Ruta física, sin symlinks: Tauri se niega a arrancar si su propia ruta pasa por
# uno, y en macOS /tmp y /var lo son.
BASE=$(cd "${TMPDIR:-/tmp}" && pwd -P)

FALLAS=0
paso() { printf '  ok    %s\n' "$1"; }
falla() { printf '  FALLA %s\n' "$1"; FALLAS=$((FALLAS + 1)); }
nota() { printf '        %s\n' "$1"; }
titulo() { printf '\n== %s\n' "$1"; }

MONTAJE=""
CASA=""
COPIA=""
EJECUTABLE=""
limpiar() {
  [ -n "$EJECUTABLE" ] && pkill -f "$EJECUTABLE" 2>/dev/null
  sleep 1
  pkill -f "aiuda-server" 2>/dev/null
  [ -n "$MONTAJE" ] && hdiutil detach "$MONTAJE" -quiet 2>/dev/null
  [ -n "$COPIA" ] && rm -rf "$(dirname "$COPIA")"
  [ -n "$CASA" ] && rm -rf "$CASA"
}
trap limpiar EXIT

titulo "El paquete"
if [ ! -f "$DMG" ]; then
  falla "no encontré ningún .dmg. Constrúyelo con scripts/build-app.sh"
  exit 1
fi
paso "$(basename "$DMG") ($(du -h "$DMG" | cut -f1))"

if lsof -nP -iTCP:$PORT -sTCP:LISTEN >/dev/null 2>&1; then
  falla "el puerto $PORT ya está ocupado: cierra aiuda antes de probar"
  exit 1
fi
paso "el puerto $PORT está libre"

titulo "Montar, como quien abre el .dmg"
MONTAJE=$(mktemp -d "$BASE/aiuda-dmg.XXXXXX")
if hdiutil imageinfo "$DMG" 2>/dev/null | grep -q "Software License Agreement: true"; then
  falla "abre con un contrato de licencia que hay que aceptar"
  nota "lo primero que ve el dueño es la Apache 2.0 en inglés, no la ventana de instalar"
  nota "se quita sacando licenseFile del bundle en desktop/src-tauri/tauri.conf.json"
else
  paso "monta directo, sin contrato de por medio"
fi
# El "Y" acepta ese contrato sin ojos humanos, para que la prueba siga. Nada de
# -quiet aquí: con esa bandera hdiutil se niega a preguntar y falla en seco.
if ! printf 'Y\n' | hdiutil attach "$DMG" -nobrowse -readonly -mountpoint "$MONTAJE" >/dev/null 2>&1; then
  falla "el .dmg no montó"
  exit 1
fi
APP="$MONTAJE/aiuda.app"
[ -d "$APP" ] && paso "trae aiuda.app" || { falla "adentro no hay aiuda.app"; exit 1; }
[ -L "$MONTAJE/Applications" ] && paso "trae el atajo a Aplicaciones (arrastrar y soltar)" \
  || falla "no trae el atajo a /Applications: hay que arrastrar a ciegas"

titulo "Firma y Gatekeeper"
# La firma se revisa sobre una copia: montada de solo lectura, codesign no puede
# leer los atributos que necesita.
DESTINO=$(mktemp -d "$BASE/aiuda-apps.XXXXXX")
COPIA="$DESTINO/aiuda.app"
ditto "$APP" "$COPIA" 2>/dev/null && paso "instalada en una carpeta de Aplicaciones de prueba" \
  || { falla "no se pudo copiar el paquete"; exit 1; }

if codesign --verify --strict "$COPIA" 2>/dev/null; then
  paso "la firma del paquete verifica"
else
  falla "la firma del paquete NO verifica: $(codesign --verify --strict "$COPIA" 2>&1 | head -1 | sed 's|.*app: ||')"
  nota "una firma rota no es lo mismo que 'sin firmar': macOS dice que la app está DAÑADA"
  nota "y el truco de clic derecho > Abrir no la salva"
fi

if codesign -dv "$COPIA" 2>&1 | grep -q "Authority=Developer ID"; then
  paso "firmada con Developer ID"
else
  nota "firma ad-hoc: sirve para que no salga 'dañada', no para distribuir"
fi

# El veredicto de Apple, sin abrir ventanas ni pedirle clics a nadie.
VEREDICTO=$(syspolicy_check distribution "$COPIA" 2>&1)
if echo "$VEREDICTO" | grep -q "passed all pre-distribution checks"; then
  paso "pasa todas las revisiones de Apple: se puede repartir"
else
  # syspolicy_check imprime el nombre del problema en su propio renglón y la
  # gravedad unas líneas abajo; nos quedamos con los que dice Fatal.
  while IFS= read -r motivo; do falla "Apple lo rechaza: $motivo"; done < <(
    echo "$VEREDICTO" | awk '
      /^[A-Za-z].*[^-]$/ && !/^App has/ && !/^ / { nombre = $0 }
      /Severity: Fatal/ { if (nombre != "" && !(nombre in vistos)) { vistos[nombre]; print nombre } }'
  )
  echo "$VEREDICTO" | grep -q "Notary Ticket Missing" \
    && nota "el ticket de notarización NO se arregla con código: necesita cuenta de Apple Developer"
fi

titulo "Marcarla como bajada de internet"
xattr -w com.apple.quarantine "0083;00000000;Safari;" "$COPIA" 2>/dev/null \
  && paso "marcada en cuarentena (como un archivo bajado del navegador)" \
  || falla "no se pudo poner el bit de cuarentena"
nota "el veredicto de arriba es lo que decide Gatekeeper con este bit puesto"
nota "el doble clic en el Finder de una Mac ajena solo lo puede probar una persona"
# Para probar que la APP funciona hay que quitarlo: arrancar desde la terminal no
# es el camino del Finder, y con cuarentena el sistema mata el proceso sin decir
# nada, que no es lo que vive quien hace doble clic.
xattr -dr com.apple.quarantine "$COPIA" 2>/dev/null

NOMBRE=$(/usr/libexec/PlistBuddy -c "Print :CFBundleExecutable" "$COPIA/Contents/Info.plist" 2>/dev/null)
EJECUTABLE="$COPIA/Contents/MacOS/$NOMBRE"
[ -x "$EJECUTABLE" ] && paso "el ejecutable del paquete es $NOMBRE" \
  || { falla "el Info.plist apunta a $NOMBRE y ahí no hay nada ejecutable"; exit 1; }

titulo "Primer arranque en una máquina limpia"
CASA=$(mktemp -d "$BASE/aiuda-casa.XXXXXX")
nota "casa limpia: $CASA (tu ~/.aiuda no se toca)"
if [ "$CON_MI_IA" = true ]; then
  for c in .claude .local .nvm .codex; do
    [ -e "$HOME/$c" ] && ln -s "$HOME/$c" "$CASA/$c"
  done
  nota "le presté tu Claude Code y tu Codex desde $HOME"
fi

# El entorno con el que macOS abre una app desde el Finder: PATH pelado.
env -i \
  HOME="$CASA" \
  PATH="/usr/bin:/bin:/usr/sbin:/sbin" \
  USER="$(id -un)" LOGNAME="$(id -un)" SHELL=/bin/zsh \
  TMPDIR="$BASE" LANG=es_MX.UTF-8 \
  "$EJECUTABLE" >"$CASA/salida.log" 2>&1 &
PID_APP=$!

INICIO=$(date +%s)
LISTA=false
for _ in $(seq 1 60); do
  if curl -fsS "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then LISTA=true; break; fi
  kill -0 $PID_APP 2>/dev/null || break
  sleep 1
done
SEGUNDOS=$(( $(date +%s) - INICIO ))

if [ "$LISTA" = true ]; then
  paso "responde en ${SEGUNDOS}s (crea base, llave y sesión sola)"
else
  falla "no levantó en 60s"
  nota "bitácora: $(tail -3 "$CASA/salida.log" 2>/dev/null | tr '\n' ' ')"
  exit 1
fi

titulo "La sesión y la consola"
SESION="$CASA/.aiuda/sesion.json"
if [ -f "$SESION" ]; then
  paso "anotó la sesión en ~/.aiuda/sesion.json"
  PERMISOS=$(stat -f "%OLp" "$SESION")
  [ "$PERMISOS" = "600" ] && paso "solo el dueño la puede leer (0600)" \
    || falla "permisos $PERMISOS: el token queda legible para otros"
  TOKEN=$(/usr/bin/python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['token'])" "$SESION" 2>/dev/null)
else
  falla "no anotó sesion.json: abrir la app dos veces volvería a romperse"
  TOKEN=""
fi

# La llave de cifrado se genera hasta que hay un secreto que guardar, no al
# arrancar. Que no exista todavía es correcto; lo que no puede pasar es que
# exista y la pueda leer alguien más.
if [ -f "$CASA/.aiuda/key" ]; then
  [ "$(stat -f "%OLp" "$CASA/.aiuda/key")" = "600" ] \
    && paso "la llave de cifrado quedó en 0600" \
    || falla "la llave de cifrado quedó legible para otros"
else
  nota "aún no hay llave de cifrado: se crea con el primer secreto, no al arrancar"
fi
[ -f "$CASA/.aiuda/aiuda.db" ] && paso "creó la base en ~/.aiuda/aiuda.db" \
  || falla "no creó la base"

CODIGO=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:$PORT/")
[ "$CODIGO" = "401" ] && paso "sin token la consola cierra la puerta (401)" \
  || falla "sin token contestó $CODIGO: la consola no está protegida"
curl -s "http://127.0.0.1:$PORT/" | grep -q "llave de tu sesión" \
  && paso "y lo explica en español, no con un JSON crudo" \
  || falla "el 401 le enseña JSON al dueño (el bug que viste en pantalla)"

if [ -n "$TOKEN" ]; then
  curl -fsS "http://127.0.0.1:$PORT/?token=$TOKEN" | grep -qi "<html" \
    && paso "con el token entrega la consola" || falla "con el token no entregó la consola"
fi

titulo "Lo que ve el dueño el primer día"
if [ -n "$TOKEN" ]; then
  ESTADO=$(curl -fsS "http://127.0.0.1:$PORT/v1/setup/estado?token=$TOKEN")
  echo "$ESTADO" | grep -q "." && paso "el asistente de primer arranque contesta" \
    || falla "el asistente no contesta"
  nota "estado: $(echo "$ESTADO" | cut -c1-160)"

  MAQUINA=$(curl -fsS "http://127.0.0.1:$PORT/v1/setup/maquina?token=$TOKEN")
  nota "máquina: $(echo "$MAQUINA" | cut -c1-200)"
  if echo "$MAQUINA" | grep -q '"claude"'; then
    paso "detectó un CLI de IA ya instalado (la ruta de un clic)"
  else
    nota "no encontró CLIs de IA: correcto en una máquina limpia"
  fi

  AGENTES=$(curl -fsS "http://127.0.0.1:$PORT/v1/agents?token=$TOKEN")
  echo "$AGENTES" | grep -q "\[" && paso "la lista de ayudantes responde (vacía, sin datos demo)" \
    || falla "la lista de ayudantes falló"
fi

titulo "Abrirla dos veces (el bug que viste en pantalla)"
# Contar procesos NO sirve como medida: el server empaquetado con PyInstaller son
# siempre dos procesos (el que desempaca y el que corre). Lo que importa es que
# solo haya UNO escuchando el puerto y que el número no crezca.
ANTES=$(pgrep -f "aiuda-server" | wc -l | tr -d ' ')
env -i HOME="$CASA" PATH="/usr/bin:/bin:/usr/sbin:/sbin" \
  USER="$(id -un)" LOGNAME="$(id -un)" SHELL=/bin/zsh TMPDIR="$BASE" \
  "$EJECUTABLE" >"$CASA/salida2.log" 2>&1 &
PID_APP2=$!
sleep 10
DESPUES=$(pgrep -f "aiuda-server" | wc -l | tr -d ' ')
ESCUCHANDO=$(lsof -nP -iTCP:$PORT -sTCP:LISTEN 2>/dev/null | tail -n +2 | wc -l | tr -d ' ')
if [ "$DESPUES" -le "$ANTES" ] && [ "$ESCUCHANDO" = "1" ]; then
  paso "la segunda ventana se suma a la sesión viva (sigue habiendo un solo server)"
else
  falla "la segunda ventana levantó otro server (procesos $ANTES->$DESPUES, escuchando $ESCUCHANDO)"
fi
kill $PID_APP2 2>/dev/null

titulo "Cerrar sin dejar basura"
kill $PID_APP 2>/dev/null
for _ in $(seq 1 15); do
  pgrep -f "aiuda-server" >/dev/null 2>&1 || break
  sleep 1
done
if pgrep -f "aiuda-server" >/dev/null 2>&1; then
  falla "el server sigue vivo con la app cerrada (proceso huérfano)"
else
  paso "el server se apagó con la app"
fi
lsof -nP -iTCP:$PORT -sTCP:LISTEN >/dev/null 2>&1 \
  && falla "el puerto $PORT quedó ocupado" || paso "el puerto quedó libre"
[ -f "$CASA/.aiuda/sesion.json" ] && falla "sesion.json quedó tirado: la próxima ventana creerá que hay sesión" \
  || paso "borró sesion.json al salir"

titulo "Resultado"
if [ "$FALLAS" -eq 0 ]; then
  echo "  todo en verde"
else
  echo "  $FALLAS fallas"
fi
exit $((FALLAS > 0))
