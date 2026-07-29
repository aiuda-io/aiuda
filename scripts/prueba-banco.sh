#!/usr/bin/env bash
# ¿De verdad funciona la importación de estados de cuenta, de punta a punta?
#
#   scripts/prueba-banco.sh
#
# Prueba el camino completo contra el servidor real: un PDF tipo Banorte se
# parsea directo (sin IA), sus depósitos entran a conciliación con procedencia,
# re-subirlo no duplica, dos depósitos del mismo importe son DOS pagos, un
# estado manipulado que no cuadra se rechaza, y un banco desconocido se lee con
# la IA que el dueño tiene conectada (Codex), también de verdad.
#
# Los PDFs son SINTÉTICOS (core/tests/pdf_sintetico.py): datos inventados con la
# misma geometría que los estados reales. Ningún dato financiero real se toca.
#
# Usa TU entorno de verdad (por eso el CLI de Codex encuentra su sesión) pero
# una base desechable: tu ~/.aiuda/aiuda.db no se toca. Al terminar limpia.

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
limpiar() {
  pkill -f "aiuda start" 2>/dev/null
  sleep 1   # que suelte la base antes de borrar
  [ -n "$CASA" ] && rm -rf "$CASA" 2>/dev/null
  # El servidor anota su sesión en ~/.aiuda aunque la base esté en otro lado.
  rm -f "$HOME/.aiuda/sesion.json" 2>/dev/null
}
trap limpiar EXIT

if lsof -nP -iTCP:$PORT -sTCP:LISTEN >/dev/null 2>&1; then
  echo "El puerto $PORT está ocupado. Cierra aiuda y vuelve a correr esto."
  exit 1
fi

CASA=$(mktemp -d "$BASE/aiuda-banco.XXXXXX")
titulo "Tu entorno de verdad, con una base desechable"
# El HOME NO se aísla, a propósito: Codex guarda su sesión en el HOME real y con
# una casa prestada contestaría "no has iniciado sesión". Se aísla la BASE.
export AIUDA_DATABASE_URL="sqlite:///$CASA/prueba.db"

# Se comprueba el aislamiento ANTES de escribir nada. Ya pasó una vez que esta
# variable se ignoraba en silencio y se acabó escribiendo en la base del dueño.
REAL=$(uv run python -c "from aiuda_core.db import resolved_database_url; print(resolved_database_url())" 2>/dev/null)
case "$REAL" in
  *"$CASA"*) paso "base aislada: $(basename "$CASA")/prueba.db" ;;
  *) falla "la base NO quedó aislada (apunta a $REAL). No sigo."; exit 1 ;;
esac
nota "tu ~/.aiuda/aiuda.db no se toca; Codex sí usa tu sesión de verdad"

uv run python scripts/seed.py >/dev/null 2>&1 \
  && paso "cartera de prueba sembrada" || { falla "no se pudo sembrar"; exit 1; }

uv run python core/tests/pdf_sintetico.py "$CASA" >/dev/null 2>&1 \
  && paso "PDFs sintéticos fabricados (Banorte, BBVA, banco desconocido)" \
  || { falla "no se pudieron fabricar los PDFs sintéticos"; exit 1; }

uv run aiuda start --no-browser --quiet --port $PORT >"$CASA/log" 2>&1 &
for _ in $(seq 1 40); do curl -fsS "http://127.0.0.1:$PORT/health" >/dev/null 2>&1 && break; sleep 1; done
TOK=$(python3 -c "import json,pathlib;print(json.load(open(pathlib.Path.home()/'.aiuda/sesion.json'))['token'])" 2>/dev/null)
[ -n "$TOK" ] && paso "servidor arriba" || { falla "el servidor no levantó"; exit 1; }
API="http://127.0.0.1:$PORT"

# ---------------------------------------------------------------- Banorte ----
titulo "Banorte sintético: parseo directo, sin gastar IA"
PREVIA=$(curl -fsS -X POST "$API/v1/banco/analizar?token=$TOK" \
  -F "file=@$CASA/banorte-sintetico.pdf;type=application/pdf" 2>&1)
echo "$PREVIA" > "$CASA/previa-banorte.json"
LEIDO=$(echo "$PREVIA" | python3 -c "
import json,sys
try:
    d = json.load(sys.stdin)
    print(f\"{d['banco']}|{d['metodo']}|{d['cuadra']}|{d['depositos']['n']}|{d['depositos']['total']}\")
except Exception: print('')")
case "$LEIDO" in
  "Banorte|banorte|True|3|20200.0")
    paso "leído directo: 3 depósitos por \$20,200.00 y cuadra al centavo" ;;
  *) falla "la previa no es la esperada: $(echo "$PREVIA" | head -c 200)"; exit 1 ;;
esac

IMPORTA=$(curl -fsS -X POST "$API/v1/banco/importar?token=$TOK" \
  -H 'Content-Type: application/json' -d @"$CASA/previa-banorte.json" 2>&1)
echo "$IMPORTA" | grep -q '"creados": *3' \
  && paso "el dueño aprobó: 3 depósitos entraron a conciliación" \
  || { falla "no importó: $(echo "$IMPORTA" | head -c 200)"; exit 1; }

BANDEJA=$(curl -fsS "$API/v1/reconciliation?token=$TOK" 2>&1)
RESUMEN=$(echo "$BANDEJA" | python3 -c "
import json,sys
d = json.load(sys.stdin)
pagos = [p for p in d['pending'] if p['source'] == 'banco']
rentas = [p for p in pagos if abs(p['amount'] - 8500.0) < 0.01]
con_origen = [p for p in pagos if p.get('origen') and 'estado de cuenta' in p['origen']]
print(f'{len(pagos)}|{len(rentas)}|{len(con_origen)}')")
case "$RESUMEN" in
  "3|2|3") paso "en la bandeja: 3 pagos del banco, con procedencia visible" ;;
  *) falla "la bandeja no trae lo esperado (pagos|rentas|con_origen = $RESUMEN)" ;;
esac

# El bug que NO se reproduce: dos rentas del mismo importe son DOS pagos.
DOS=$(echo "$RESUMEN" | cut -d'|' -f2)
[ "$DOS" = "2" ] \
  && paso "dos depósitos de \$8,500.00 en fechas distintas son DOS pagos (no se pisan)" \
  || falla "las dos rentas del mismo importe se pisaron: quedó $DOS"

REIMPORTA=$(curl -fsS -X POST "$API/v1/banco/importar?token=$TOK" \
  -H 'Content-Type: application/json' -d @"$CASA/previa-banorte.json" 2>&1)
echo "$REIMPORTA" | grep -q '"creados": *0' \
  && paso "re-subir el mismo estado no duplica (0 nuevos)" \
  || falla "re-importar duplicó: $(echo "$REIMPORTA" | head -c 160)"

# ------------------------------------------------------------------- BBVA ----
titulo "BBVA sintético: el otro formato verificado"
PREVIA_BBVA=$(curl -fsS -X POST "$API/v1/banco/analizar?token=$TOK" \
  -F "file=@$CASA/bbva-sintetico.pdf;type=application/pdf" 2>&1)
echo "$PREVIA_BBVA" | python3 -c "
import json,sys
d = json.load(sys.stdin)
assert d['banco'] == 'BBVA' and d['metodo'] == 'bbva' and d['cuadra'], d
print('ok')" >/dev/null 2>&1 \
  && paso "leído directo y cuadra" \
  || falla "BBVA no se leyó bien: $(echo "$PREVIA_BBVA" | head -c 200)"

# ------------------------------------------------- estado que no cuadra ------
titulo "Un estado manipulado que no cuadra"
python3 -c "
import json
d = json.load(open('$CASA/previa-banorte.json'))
d['saldo_final'] = 99999.99
json.dump(d, open('$CASA/previa-mala.json', 'w'))"
MALA=$(curl -sS -o /dev/null -w '%{http_code}' -X POST "$API/v1/banco/importar?token=$TOK" \
  -H 'Content-Type: application/json' -d @"$CASA/previa-mala.json" 2>&1)
[ "$MALA" = "409" ] \
  && paso "se rechaza con 409: no se importa nada a ciegas" \
  || falla "un estado que no cuadra contestó $MALA en vez de 409"

# ------------------------------------------- banco desconocido, con Codex ----
titulo "Banco desconocido: lo lee la IA de verdad (Codex)"
CONECTA=$(curl -fsS -X PUT "$API/v1/provider?token=$TOK" -H 'Content-Type: application/json' \
  -d '{"name":"codex_cli","mode":"cli"}' 2>&1)
echo "$CONECTA" | grep -q '"connected": *true' \
  && paso "Codex conectado (la sesión del programa del dueño, sin llaves)" \
  || { falla "no conectó Codex: $(echo "$CONECTA" | head -c 160)"; exit 1; }

INICIO=$(date +%s)
PREVIA_IA=$(curl -fsS -X POST "$API/v1/banco/analizar?token=$TOK" --max-time 300 \
  -F "file=@$CASA/generico-sintetico.pdf;type=application/pdf" 2>&1)
SEG=$(( $(date +%s) - INICIO ))
echo "$PREVIA_IA" > "$CASA/previa-ia.json"
LEIDO_IA=$(echo "$PREVIA_IA" | python3 -c "
import json,sys
try:
    d = json.load(sys.stdin)
    print(f\"{d['metodo']}|{d['cuadra']}|{d['depositos']['n']}|{d['depositos']['total']}\")
except Exception: print('')")
case "$LEIDO_IA" in
  "ia|True|2|16850.0")
    paso "Codex lo estandarizó en ${SEG}s: 2 depósitos por \$16,850.00 y cuadra" ;;
  *) falla "la lectura con IA no es la esperada (${SEG}s): $(echo "$PREVIA_IA" | head -c 250)" ;;
esac

if echo "$LEIDO_IA" | grep -q '^ia|True'; then
  IMPORTA_IA=$(curl -fsS -X POST "$API/v1/banco/importar?token=$TOK" \
    -H 'Content-Type: application/json' -d @"$CASA/previa-ia.json" 2>&1)
  echo "$IMPORTA_IA" | grep -q '"creados": *2' \
    && paso "sus 2 depósitos entraron a conciliación" \
    || falla "no importó lo de la IA: $(echo "$IMPORTA_IA" | head -c 160)"
fi

titulo "Resultado"
[ "$FALLAS" -eq 0 ] \
  && echo "  el estado de cuenta entra de punta a punta: directo, con IA, sin duplicar y sin cuadres falsos" \
  || echo "  $FALLAS fallas"
exit $((FALLAS > 0))
