#!/usr/bin/env bash
# ¿De verdad sirve la IA que el dueño conectó?
#
#   scripts/prueba-ia.sh                       # Codex, que es lo conectado
#   scripts/prueba-ia.sh claude_cli codex_cli  # los dos
#
# No pregunta si el programa existe: lo CONECTA como lo haría el dueño desde su
# consola, le pide una respuesta de verdad, y luego pone a un ayudante a redactar
# cobranza sobre facturas reales. Que `probar` conteste ok no significa que el
# ayudante vaya a poder trabajar: son dos caminos distintos del código y el
# segundo es el que le importa al negocio.
#
# Corre sobre una casa desechable (un $HOME temporal con su propia base): no toca
# ~/.aiuda, ni tu cartera, ni tu WhatsApp. Lo único tuyo que usa es la sesión de
# tu CLI de IA, que se le presta por enlace. Al terminar borra la casa completa.

set -uo pipefail
set +m
cd "$(dirname "$0")/.."

BASE=$(cd "${TMPDIR:-/tmp}" && pwd -P)
PORT=4747
FALLAS=0
paso() { printf '  ok    %s\n' "$1"; }
falla() { printf '  FALLA %s\n' "$1"; FALLAS=$((FALLAS + 1)); }
nota() { printf '        %s\n' "$1"; }
titulo() { printf '\n== %s\n' "$1"; }

CASA=""
SERVIDOR=""
limpiar() {
  # Solo el servidor que levantó ESTA prueba. Antes era `pkill -f "aiuda start"`,
  # que apagaba cualquier aiuda de la computadora, el del dueño incluido.
  if [ -n "$SERVIDOR" ]; then
    pkill -P "$SERVIDOR" 2>/dev/null
    kill "$SERVIDOR" 2>/dev/null
  fi
  sleep 1   # que suelte la base antes de borrar
  # Los enlaces a la sesión de los CLIs se borran como enlaces: lo enlazado no se toca.
  [ -n "$CASA" ] && rm -rf "$CASA" 2>/dev/null
}
trap limpiar EXIT

if lsof -nP -iTCP:$PORT -sTCP:LISTEN >/dev/null 2>&1; then
  echo "El puerto $PORT está ocupado. Cierra aiuda y vuelve a correr esto."
  exit 1
fi

CASA=$(mktemp -d "$BASE/aiuda-ia.XXXXXX")
titulo "Una casa desechable, con la sesión de tu IA prestada"
# La casa es desechable: el servidor escribe su llave y su nota de sesión en
# $HOME/.aiuda, y con el HOME de verdad esa nota caía en la del dueño (y al
# terminar se la borrábamos). A la casa prestada solo se le enlaza lo que los CLIs
# de IA necesitan para encontrar su sesión, igual que scripts/prueba-app.sh
# --con-mi-ia. Codex la guarda en ~/.codex. Claude Code en Mac la guarda en el
# llavero del sistema: si con la casa prestada pide iniciar sesión, la falla es
# de este aislamiento y no de aiuda.
CASA_REAL="$HOME"
for c in .claude .claude.json .codex .local .nvm; do
  [ -e "$CASA_REAL/$c" ] && ln -s "$CASA_REAL/$c" "$CASA/$c"
done
# El entorno de Python se resuelve antes de cambiar de casa: uv guarda su caché
# en el HOME y con uno vacío volvería a bajar todo.
[ -x .venv/bin/aiuda ] || uv sync --quiet
PY="$PWD/.venv/bin/python"
AIUDA="$PWD/.venv/bin/aiuda"
export HOME="$CASA"
export AIUDA_DATABASE_URL="sqlite:///$CASA/prueba.db"
# El WhatsApp tampoco es el de verdad: ni su store ni su programa.
export WACLI_STORE_ROOT="$CASA/wacli"
export WACLI_BIN="$CASA/sin-wacli"

# Se comprueba el aislamiento ANTES de escribir nada. Ya pasó una vez que esta
# variable se ignoraba en silencio y se acabó escribiendo en la base del dueño.
REAL=$("$PY" -c "from aiuda_core.db import resolved_database_url; print(resolved_database_url())" 2>/dev/null)
case "$REAL" in
  *"$CASA"*) paso "base aislada: $(basename "$CASA")/prueba.db" ;;
  *) falla "la base NO quedó aislada (apunta a $REAL). No sigo."; exit 1 ;;
esac
nota "tu ~/.aiuda no se toca; el CLI sí usa tu sesión de verdad"

"$PY" scripts/seed.py >/dev/null 2>&1 \
  && paso "cartera de prueba sembrada" || { falla "no se pudo sembrar"; exit 1; }

"$AIUDA" start --no-browser --quiet --port $PORT >"$CASA/log" 2>&1 &
SERVIDOR=$!
for _ in $(seq 1 40); do curl -fsS "http://127.0.0.1:$PORT/health" >/dev/null 2>&1 && break; sleep 1; done
TOK=$(python3 -c "import json,pathlib;print(json.load(open(pathlib.Path.home()/'.aiuda/sesion.json'))['token'])" 2>/dev/null)
[ -n "$TOK" ] && paso "servidor arriba" || { falla "el servidor no levantó"; exit 1; }
API="http://127.0.0.1:$PORT"

# Qué CLIs hay de verdad en esta computadora.
titulo "Qué tienes instalado"
INSTALADOS=$(curl -fsS "$API/v1/setup/maquina?token=$TOK" | python3 -c "
import json,sys
clis = json.load(sys.stdin).get('clis') or {}
print(' '.join(k for k, v in clis.items() if v))")
[ -n "$INSTALADOS" ] && paso "$INSTALADOS" || nota "ninguno; esta prueba no aplica en esta máquina"

# Por default se prueba SOLO Codex: es el que el dueño tiene conectado en su
# aiuda, y probar el otro le dejaría una sesión de Claude Code abierta que no
# pidió. Para probar los dos: scripts/prueba-ia.sh claude_cli codex_cli
CUALES="${*:-codex_cli}"
[ -z "${CUALES// /}" ] && { echo; echo "  nada que probar"; exit 0; }

for PROVEEDOR in $CUALES; do
  titulo "$PROVEEDOR"

  # 1. Conectar, como lo hace el dueño con un clic en su consola.
  CONECTA=$(curl -fsS -X PUT "$API/v1/provider?token=$TOK" -H 'Content-Type: application/json' \
    -d "{\"name\":\"$PROVEEDOR\",\"mode\":\"cli\"}" 2>&1)
  echo "$CONECTA" | grep -q '"connected": *true' \
    && paso "conectado (sin llave, con la sesión del programa del dueño)" \
    || { falla "no conectó: $(echo "$CONECTA" | head -c 160)"; continue; }

  # 2. Una respuesta de verdad. La primera tarda: el programa está despertando.
  INICIO=$(date +%s)
  PRUEBA=$(curl -fsS -X POST "$API/v1/provider/test?token=$TOK" --max-time 200 2>&1)
  SEG=$(( $(date +%s) - INICIO ))
  if echo "$PRUEBA" | grep -q '"ok": *true'; then
    paso "contestó en ${SEG}s"
  else
    falla "no contestó: $(echo "$PRUEBA" | head -c 200)"
    continue
  fi

  # 3. Lo que de verdad importa: que un ayudante trabaje con esa IA sobre la
  #    cartera. Es otro camino del código, con herramientas de por medio.
  AYU=$(curl -fsS -X POST "$API/v1/ayudantes?token=$TOK" -H 'Content-Type: application/json' \
    -d '{"name":"Prueba","perfil":"cobranza"}' 2>&1 | python3 -c "
import json,sys
try: print(json.load(sys.stdin).get('id',''))
except Exception: print('')")
  [ -n "$AYU" ] && paso "ayudante de cobranza creado" || { falla "no se pudo crear el ayudante"; continue; }

  # Un ayudante recién creado viene vacío: hay que darle la aiudita que corre.
  # Es la única que trabaja en tanda hoy, y sin ella la corrida no hace nada.
  AGREGA=$(curl -fsS -X PUT "$API/v1/ayudantes/$AYU/aiuditas/cobranza.redactar_recordatorio?token=$TOK" \
    -H 'Content-Type: application/json' -d '{"config":{}}' 2>&1)
  echo "$AGREGA" | grep -q "cobranza.redactar_recordatorio" \
    && paso "se le dio la aiudita de redactar recordatorios" \
    || { falla "no se le pudo dar la aiudita: $(echo "$AGREGA" | head -c 160)"; continue; }

  INICIO=$(date +%s)
  CORRIDA=$(curl -fsS -X POST "$API/v1/ayudantes/$AYU/correr?token=$TOK" --max-time 400 2>&1)
  SEG=$(( $(date +%s) - INICIO ))
  REDACTADAS=$(echo "$CORRIDA" | python3 -c "
import json,sys
try:
    d = json.load(sys.stdin)
    print(d.get('propuestas', d.get('drafted', 0)))
except Exception: print(0)")
  if [ "${REDACTADAS:-0}" -gt 0 ]; then
    paso "el ayudante redactó $REDACTADAS propuestas en ${SEG}s"
  else
    falla "el ayudante no redactó nada: $(echo "$CORRIDA" | head -c 200)"
    continue
  fi

  # 4. Que lo redactado sea texto de verdad y no un JSON crudo ni un error.
  MUESTRA=$(curl -fsS "$API/v1/reminders?token=$TOK" | python3 -c "
import json,sys
d = [r for r in json.load(sys.stdin) if r['status'] in ('pending_approval','draft')]
print(d[0]['message'][:150].replace(chr(10),' ') if d else '')")
  if [ -n "$MUESTRA" ] && ! echo "$MUESTRA" | grep -qiE '^\{|error|traceback|no pude'; then
    paso "lo que escribió se lee como un mensaje a un cliente"
    nota "\"$(echo "$MUESTRA" | head -c 110)…\""
  else
    falla "lo redactado no sirve: $(echo "$MUESTRA" | head -c 120)"
  fi
done

titulo "Resultado"
[ "$FALLAS" -eq 0 ] && echo "  la IA del dueño trabaja de punta a punta" || echo "  $FALLAS fallas"
exit $((FALLAS > 0))
