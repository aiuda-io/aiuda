# Portales sin API (CUA)

Buena parte de lo que una PyME mexicana necesita no tiene API usable: el portal
del SAT, la banca en línea de casi cualquier banco, portales de tribunales, ERPs
viejos. El CUA (Computer Use Agent) es la salida: si un humano puede operarlo en
pantalla, un agente puede hacerlo también, en un navegador de tu computadora,
con evidencia y de solo lectura por default.

Es la parte más experimental de aiuda. La consola lo marca como experimental y
aquí también.

## Cómo está armado

```
Mission (declarativa)            Chromium local (Playwright, headless)
  objetivo                  -->    LocalComputer
  datos_a_extraer                    ejecuta click/type/key/scroll
  solo_lectura              <--      y devuelve capturas PNG
  max_pasos (40 por default)
        |
        v
  CuaRunner: loop de computer-use de Anthropic. El modelo ve la captura,
  responde una acción, el runner la ejecuta y le manda la siguiente captura,
  hasta que entrega el JSON pedido.
```

- `core/aiuda_core/cua/mission.py`: el contrato. Una misión dice QUÉ extraer, no
  cómo hacer clic, y produce un resultado con datos, bitácora y evidencia.
- `core/aiuda_core/cua/computer.py`: el navegador como "display", más la
  detección honesta de qué falta en esta computadora.
- `core/aiuda_core/cua/runner.py`: el loop real y las misiones plantilla.
- `core/aiuda_core/cua/handoff.py`: el login lo haces tú (abajo).
- `core/aiuda_core/cua/fallback.py`: el CUA cableado como una fuente más de una
  capacidad, con su recado, su estado y su evidencia.

No hay VM ni sandbox remoto: es un Chromium en tu máquina.

## Instalar

```sh
uv sync --extra cua
.venv/bin/playwright install chromium
```

Sin eso nada truena ni se inventa: la misión termina con el faltante exacto y el
comando para instalarlo, `GET /v1/cua/estado` lo reporta y la consola lo dice
antes de encolar.

Dos límites honestos:

- **El binario de la app de escritorio no trae Playwright** (pesa cientos de MB y
  es opcional). Hoy el CUA solo corre en la instalación desde el código.
- **Necesita una IA con acceso a computer-use**, que hoy significa Anthropic. Un
  modelo local con Ollama no sirve para esto.

## El login lo haces tú (handoff)

aiuda nunca toca tu contraseña. Para operar un portal real hace un handoff: abre
el portal en una ventana **visible** del navegador, tú entras como siempre
(usuario, e.firma, 2FA, lo que sea) y le dices "listo". En ese momento se guarda
tu sesión ya autenticada (cookies y storage), cifrada, y las misiones siguientes
arrancan con la sesión puesta. La contraseña no se guarda ni se ve nunca.

La ventana visible solo puede abrirse donde hay pantalla, o sea tu computadora.
La sesión dura lo que el portal le dé: cuando caduque, repites el handoff. Hay 8
minutos de margen para entrar antes de que la ventana se cierre sola.

## Reglas que no se negocian

1. **Local y en su propio navegador.** El agente nunca opera tu pantalla ni tu
   sesión abierta. No descarga ni ejecuta binarios.
2. **Solo lectura por default.** Escribir es opt-in por misión y el prompt lo
   dice explícito.
3. **Evidencia obligatoria.** Capturas por paso y bitácora por misión, guardadas
   en el recado (las últimas 8 capturas).
4. **La URL del portal es tuya.** Tu banco o tu juzgado los registras tú, en la
   configuración del negocio. Sin URL, el recado corta antes de abrir el
   navegador o gastar IA.
5. **Presupuesto de pasos.** `max_pasos` corta las misiones que se pierden.

## Qué puede hacer hoy

Tres plantillas incluidas:

| Plantilla | Portal | Para qué |
|---|---|---|
| `sat_cfdi_recibidos` | Portal del SAT | CFDIs recibidos, respaldo fiscal y conciliación |
| `banca_movimientos` | Banca en línea | Depósitos recibidos, cuando el banco no está en Belvo |
| `tribunal_acuerdos` | Portales de tribunales | Acuerdos publicados de un expediente |

Solo la del SAT trae URL propia (el portal es único); las otras dos toman la URL
que registres. Además puedes registrar **portales a la medida** por URL
(cualquier sitio tuyo: un proveedor, un municipio) y encargarles misiones.

Al encolar puedes escribir una indicación en tus palabras ("revisa el expediente
77/2025"). Esa indicación viaja en el prompt y cambia lo que el agente hace en el
portal.

Cuando eliges CUA como fuente de una capacidad, lo extraído entra a tu cartera
con procedencia `cua:<sistema>` y su evidencia. Los depósitos entran como pagos
pendientes de conciliación: el ayudante propone, tú concilias.

## Probar sin tocar un portal real

Hay tres portales estáticos de prueba en `core/aiuda_core/cua/portales/` (banca,
SAT y tribunal, con datos ficticios y el letrero "Portal de prueba local") que se
sirven por HTTP en un puerto efímero. `core/tests/test_cua_portales.py` corre las
plantillas contra ellos con Chromium real y verifica el DOM final, no lo que el
agente dice que pasó. Los tests que abren navegador se saltan solos si falta el
extra.

`cua/scripted.py` es un agente de guion determinista, sin IA, con la misma
interfaz que el cliente de Anthropic: lee el prompt real que arma el runner, así
que sirve para probar que la instrucción del dueño llega hasta el portal.

Demo a mano contra un portal local de una sola página:

```sh
ANTHROPIC_API_KEY=sk-... uv run python scripts/cua_demo.py
```

## Estado

Listos: el contrato, el runner con Playwright, las tres plantillas, los portales
a la medida, el handoff de login, el CUA como fuente, la detección honesta y la
evidencia visible en la consola.

Verificado: las plantillas contra los portales de prueba locales, y una corrida
real de punta a punta (un modelo de Anthropic operando el portal de prueba del
tribunal, obedeciendo la indicación del dueño y dejando 6 capturas de
evidencia). **Nadie ha operado todavía un portal real del SAT o de un banco con
esto.**

Falta: medir el costo por misión (computer-use gasta bastante más que texto),
límites de dominio, redacción de secretos en la evidencia y reintentos. Por costo
y latencia, estas misiones están pensadas como corridas programadas, no
interactivas.
