# Portales sin API (CUA)

Buena parte de lo que una PyME mexicana necesita no tiene API usable: el portal
del SAT, la banca en línea de casi cualquier banco, portales de tribunales, ERPs
viejos. El CUA (Computer Use Agent) es la salida: si un humano puede operarlo en
pantalla, un agente puede hacerlo también, en un navegador de tu computadora,
con evidencia y de solo lectura por default.

Es la parte más experimental de aiuda. La consola lo marca como experimental y
aquí también.

Hay dos maneras de operar un portal, y conviene no confundirlas:

- **Rutinas sin IA** (guion fijo). Hoy son dos, las dos del SAT: bajar tu opinión
  de cumplimiento y tu constancia de situación fiscal. Van primero porque son lo
  más firme.
- **El asistente con IA** (el CUA propiamente dicho), que ve la pantalla y decide
  qué hacer. Es el resto de este documento.

## Rutinas sin IA: los documentos del SAT

En **Rutinas** aparece un bloque por cada RFC con e.firma conectada, con dos
rutinas:

| Rutina | Qué te deja |
|---|---|
| Opinión de cumplimiento (32-D) | El PDF, su sentido (Positivo, Negativo), su folio y la fecha |
| Constancia de situación fiscal | El PDF y la fecha |

Pulsas **Bajar ahora**, tarda cerca de un minuto y el PDF queda guardado en esta
computadora. Lo abres con **Ver PDF** ahí mismo o en **SAT · Bóveda fiscal**, en
el bloque Documentos.

Lo que las hace distintas del asistente con IA:

- **No usan IA.** Siguen un guion escrito paso por paso. Funcionan con cualquier
  IA conectada y también sin ninguna. No gastan de tu tope.
- **No llevan instrucción.** No hay nada que interpretar: siempre hacen lo mismo.
- **Entran con tu e.firma guardada**, la misma de la Descarga Masiva. Aquí aiuda
  sí escribe la contraseña de tu e.firma, en el campo de contraseña del portal del
  SAT y en ningún otro lado. La firma del acceso se hace en el navegador de esta
  computadora: la llave y la contraseña no se mandan a nadie.
- **Piden tu permiso una vez por RFC.** Antes de la primera corrida aceptas un
  texto que dice justo eso. Queda guardado con fecha y en la bitácora. Sin ese
  permiso el servidor se niega a correrlas. Si borras la e.firma o la cambias
  por otra (una renovación), el permiso se olvida y se vuelve a pedir.
- **Solo consultan y descargan.** No presentan, no firman ni aceptan nada.

Se detienen, con una captura y el motivo en la bitácora, cuando:

- el SAT pide un captcha;
- el portal pide aceptar, firmar o confirmar algo (aiuda no le da clic). Un
  aviso que solo informa se cierra y queda anotado en la bitácora, sin detener;
- el portal contesta con un error o no responde;
- el SAT rechaza la e.firma (revocada, vencida, o contraseña que no coincide);
- lo descargado no es un PDF, no menciona tu RFC o no es el documento pedido.

No reintentan por su cuenta. La entrada al portal se intenta dos veces como
mucho (a veces contesta un error pasajero); el acceso con la e.firma, una sola.
Tampoco se despacha dos veces la misma rutina para el mismo RFC mientras una
sigue corriendo.

Tres cosas que conviene saber:

- Cada vez que bajas la opinión de cumplimiento, el SAT le pone un folio nuevo.
- Las capturas de la bitácora se toman antes de escribir la contraseña. Aun así
  enseñan tus datos fiscales; viven en tu base, en tu computadora.
- **La app de escritorio todavía no trae el navegador** que estas rutinas
  necesitan. Ahí la pantalla lo dice y apaga los botones. Hoy solo corren en la
  instalación desde el código (ver Instalar, abajo).

**Estrenadas el 5 de octubre de 2026.** Las dos se corrieron contra el portal
real del SAT ya dentro de aiuda: el servidor normal, la e.firma guardada desde la
pantalla del SAT, el permiso dado y la rutina despachada como lo hace **Bajar
ahora**. Se usó la e.firma vigente de una persona moral. Lo que se comprobó:

- sin el permiso, el servidor se negó a correrlas;
- la constancia bajó a la primera, en unos 20 segundos;
- la opinión de cumplimiento bajó en unos 30 segundos, con sentido Positivo y su
  folio. En el intento anterior el SAT contestó un error 500 antes de mostrar la
  pantalla de acceso: la rutina lo intentó una vez más, se detuvo con la captura
  y el motivo, y no mandó la e.firma;
- cada PDF quedó guardado, se abre con **Ver PDF** en Rutinas y en SAT · Bóveda
  fiscal, es un PDF válido y menciona el RFC;
- la bitácora quedó en español, y la contraseña no aparece en la bitácora, en las
  capturas, en el registro del servidor ni en claro en la base.

Lo que **no** se ha visto contra el SAT real, solo contra el portal de prueba:
una opinión en sentido Negativo, una persona física, un captcha, un aviso que
pida aceptar algo, una e.firma rechazada y más de un RFC. Fueron tres visitas al
portal en total; si el SAT cambia sus pantallas, la rutina se detiene y lo dice.

El código vive en `core/aiuda_core/cua/deterministas/sat_documentos.py` y el
registro (`RUTINAS_DETERMINISTAS`) en `core/aiuda_core/cua/fallback.py`.

## Cómo está armado el asistente con IA

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

Sin eso nada truena ni se inventa: la misión termina diciendo que falta el
navegador, `GET /v1/cua/estado` lo reporta y la consola lo dice antes de encolar,
sin comandos. El comando lo repite `aiuda doctor`, para quien instala.

Dos límites honestos:

- **El binario de la app de escritorio no trae Playwright** (pesa cientos de MB y
  es opcional). Hoy nada de esto corre ahí, ni el asistente ni las rutinas sin
  IA: solo en la instalación desde el código.
- **El asistente necesita una llave de Anthropic (Claude).** Las rutinas sin IA
  del SAT no. El asistente tiene que ver la
  captura de pantalla del portal y contestar con un clic o una tecla, decenas de
  veces seguidas, y aiuda solo sabe hacer eso con la herramienta de computer-use
  de Anthropic. Con las otras formas de conectar la IA no corre, y lo dice antes
  de abrir el navegador:

  | Tu IA conectada | Opera portales | Por qué |
  |---|---|---|
  | Llave de Anthropic | Sí | Es la única vía con computer-use |
  | Llave de OpenAI | No | aiuda no tiene escrito el manejo de pantalla con OpenAI |
  | Claude Code o Codex instalados | No | Con aiuda solo intercambian texto, no reciben la captura |
  | Modelo local (Ollama) | No | No ve la pantalla ni devuelve acciones |

  El gasto de cada misión cuenta para tu tope mensual de IA, igual que el resto.

## El login lo haces tú (handoff)

En el handoff aiuda nunca toca tu contraseña (la única excepción en todo aiuda
son las dos rutinas sin IA del SAT, que usan la e.firma que guardaste y te piden
permiso antes). Para operar un portal real el asistente hace un handoff: abre
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

## Qué puede hacer hoy el asistente

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

Las rutinas sin IA del SAT tienen su propio portal falso, `core/tests/fake_sat.py`:
un servidor local que imita el acceso con e.firma, la consulta de la opinión y la
constancia, con PDF sintéticos y modos para captcha, avisos de aceptar, errores y
e.firma rechazada. `core/tests/test_sat_documentos.py` corre el guion contra él y
`server/tests/test_rutinas_sat.py` el camino completo por la API. Que pasen prueba
que el guion hace lo que dice; no prueba que el SAT siga igual.

Demo a mano contra un portal local de una sola página:

```sh
ANTHROPIC_API_KEY=sk-... uv run python scripts/cua_demo.py
```

## Estado

Listos: las dos rutinas sin IA del SAT (estrenadas contra el SAT real el 5 de
octubre de 2026, ver arriba), el contrato, el runner con Playwright, las tres plantillas, los
portales a la medida, el handoff de login, el CUA como fuente, la detección
honesta y la evidencia visible en la consola.

Verificado: las plantillas contra los portales de prueba locales, y una corrida
real de punta a punta (un modelo de Anthropic operando el portal de prueba del
tribunal, obedeciendo la indicación del dueño y dejando 6 capturas de
evidencia). **Nadie ha operado todavía un portal real del SAT o de un banco con
el asistente con IA.**

Falta: medir el costo por misión (computer-use gasta bastante más que texto),
límites de dominio, redacción de secretos en la evidencia y reintentos. Por costo
y latencia, estas misiones están pensadas como corridas programadas, no
interactivas.
