# Conectar tu IA

aiuda no incluye ni revende inferencia. Tú traes el modelo. Todo se conecta desde
la consola, en **Ajustes**, sección **Tu IA**, y el secreto queda cifrado en tu computadora
([DATOS.md](DATOS.md)).

Sin IA conectada, aiuda arranca y sincroniza, pero no redacta nada. `aiuda
doctor` lo dice.

## Si ya tienes Claude Code o Codex: un clic

Es la vía más corta y la que aiuda ofrece primero. Si en esta computadora ya está
instalado **Claude Code** o **Codex** con tu sesión iniciada, aiuda los detecta y
los usa tal cual: no hay llave que pegar, ni token que generar, ni terminal que
abrir. Tu sesión se queda dentro del CLI; aiuda nunca la ve ni la guarda.

Lo honesto de esta vía: aiuda ejecuta ese programa en tu máquina y lee lo que
responde, así que el modelo y la configuración los manda el CLI, no aiuda. En el
chat de los ayudantes las consultas a tus datos se piden en un formato más
simple que el nativo; si el modelo se sale de formato, el ayudante lo dice en vez
de inventar.

Dos cosas que pueden pasar la primera vez:

- Si macOS pregunta si aiuda puede usar la información guardada de Claude Code,
  dile que sí: es tu sesión, guardada en tu llavero por el propio CLI.
- Si el CLI está instalado pero nunca iniciaste sesión, aiuda te lo dice tal
  cual: ábrelo una vez, inicia sesión y regresa.

La primera respuesta tarda más que las demás: el CLI arranca, revisa tu sesión y
apenas entonces contesta. No está trabado.

**Si conectaste Codex antes del 27 de julio de 2026** y te salió un error raro
que decía `env: node: No such file or directory`, era un defecto nuestro, no
algo tuyo. Codex por dentro necesita Node, y una app abierta desde el Finder
arranca sin saber dónde vive. Ya está arreglado: aiuda le pasa esas rutas. Si lo
ves con una versión nueva, cuéntalo en un issue.

## Las otras vías

| Vía | Qué necesitas | Costo | Tus datos salen a |
|---|---|---|---|
| El programa que ya tienes | Claude Code o Codex instalado | Lo que ya pagas al mes | Anthropic u OpenAI |
| Entrar con ChatGPT (sin estrenar) | Tu cuenta de ChatGPT con un plan que lo admita | Lo que ya pagas al mes; gasta de tu mismo cupo | OpenAI |
| API key | Llave de Anthropic u OpenAI | Por token, lo cobra el proveedor | Anthropic u OpenAI |
| Modelo local | Ollama en tu máquina | Nada | Ningún lado |

### 1. API key

La vía recomendada: es la que los proveedores contemplan para uso programático.

- **Claude:** crea una llave en console.anthropic.com y pégala en Ajustes, en Tu IA.
- **OpenAI:** una llave `sk-...` de platform.openai.com, igual.

aiuda usa dos modelos: uno chico para clasificar y hacer triage, uno grande para
redactar. Con Claude y OpenAI esos modelos vienen fijos (se cambian por variable
de entorno, no desde la consola); con un modelo local sí eliges cuál corre.

### 2. El programa que ya tienes instalado

Si ya pagas Claude o ChatGPT y tienes `claude` o `codex` en tu computadora, esa es
la vía de un clic: aiuda detecta el programa, lo lanza como cualquier otra app lo
lanzaría, y lee su respuesta. **El programa se identifica con tu propia sesión;
aiuda nunca ve ni guarda tu token.**

#### Lo que se quitó, y por qué

Antes había una cuarta vía: pegar el token de `claude setup-token` (o entrar con
ChatGPT por código) y que aiuda hablara con la API directamente. Para que el
proveedor aceptara ese token, aiuda tenía que anteponer a cada mensaje la frase
"You are Claude Code, Anthropic's official CLI for Claude". No era un detalle de
estilo: era una afirmación falsa que viajaba en cada petición para pasar un
control de acceso, y correr en tu computadora no lo cambiaba.

aiuda es abierto y cualquiera lo puede instalar o forkear, así que ese riesgo se
le repartía a todos. Se retiró. Lo que se buscaba (usar la suscripción que ya
pagas sin llave aparte) lo da la vía de arriba, y esa sí es legítima.

Si ya la tenías configurada, la consola te lo dice al abrir Tu IA y te ofrece el
cambio; no se apaga en silencio.

### 3. Entrar con ChatGPT

**Sin estrenar: está construida y probada contra un servidor de pruebas que sigue
la documentación de OpenAI, pero todavía nadie ha entrado en aiuda con una cuenta
real.** Si con la tuya algo no sale, la consola te dice qué pasó y puedes conectar
tu IA por cualquiera de las otras vías.

Lo menos seguro es que tus ayudantes puedan consultar tus datos al platicar contigo
(lo que hacen sus aiuditas): OpenAI pide que esas consultas se le manden de una forma
particular en esta vía y no publica un ejemplo. aiuda sigue lo que dice su
documentación y, al probar la conexión en Tu IA, manda una consulta de esas para que
"Funciona" lo diga también de eso. Si OpenAI la rechaza, te lo dice ahí mismo.

Sirve para usar el plan de ChatGPT que ya pagas sin instalar Codex y sin sacar una
llave. En Tu IA eliges "Mi plan de ChatGPT" y picas **Continuar con ChatGPT**: se
abre tu navegador en la página de OpenAI, entras con tu cuenta, das permiso, y el
navegador te regresa a aiuda. Listo.

No es la vía que se quitó. Aquella se hacía pasar por el programa oficial; esta es
la que OpenAI abrió para programas abiertos que corren en tu computadora
([su documentación](https://developers.openai.com/siwc/token-sharing-open-source)):

- aiuda se registra **con su propio nombre**. En la configuración de ChatGPT la
  vas a ver como una aplicación conectada que se llama aiuda, y desde ahí la
  puedes limitar o quitar.
- Lo que redactan tus ayudantes va a la API pública de OpenAI, la misma de las
  llaves, identificado con el permiso que le diste.
- aiuda nunca ve tu contraseña. Guarda, cifrado en esta computadora, el permiso
  que le dio OpenAI, y lo renueva sola cada hora.

Lo que conviene saber antes:

- **Gasta de tu mismo plan.** Lo que usen tus ayudantes cuenta junto con lo que
  tú uses en ChatGPT. La corrida de cobranza es cada hora: si redacta mucho, a ti
  te queda menos para platicar con ChatGPT ese rato.
- **El límite se pone en ChatGPT, no en aiuda.** En Tu IA, "Administrar uso" te
  lleva a [chatgpt.com/settings/usage](https://chatgpt.com/settings/usage), donde
  decides cuánto de tu plan puede usar aiuda. Si se llega a ese límite o al de tu
  plan, aiuda deja de redactar y te lo dice; no se cambia sola a otra forma de
  cobro.
- **No todos los planes lo admiten.** Lo decide OpenAI según tu cuenta, y puede
  depender del país. Si la tuya no puede, el mensaje lo dice.
- **El modelo lo da tu cuenta.** aiuda le pregunta a OpenAI qué modelos tienes y
  usa uno de esos para todo; no se elige desde la consola.
- **Las rutinas de portales no funcionan por esta vía**, igual que con una llave
  de OpenAI: necesitan una llave de Claude.
- **Se hace en la computadora donde corre aiuda.** Desde el teléfono no se puede
  empezar, porque el navegador que se abre es el de la computadora.
- **La sesión dura mientras se use.** Si pasan 30 días sin que aiuda la renueve, o
  quitas la aplicación desde ChatGPT, te pedimos volver a entrar.

Esta vía existe porque aiuda es abierto, gratis y corre en tu computadora: esas
son las condiciones de OpenAI. Si eso cambiara, esta vía tendría que pedirse por
otro camino.

Todavía no sabemos si a OpenAI le gusta cómo aiuda le pide consultar tu cartera
desde el chat de un ayudante por esta vía: su documentación dice que las
herramientas se mandan agrupadas de cierta forma y no trae un ejemplo. Redactar y
clasificar no dependen de eso. Se sabrá con el primer login real.

### 4. Modelo local (Ollama)

La única vía donde ningún dato sale de tu computadora.

```sh
# instala Ollama desde https://ollama.com y luego:
ollama pull llama3.1
```

aiuda detecta el Ollama de la máquina solo, y el asistente de primer arranque
mira tu equipo (chip, memoria) para decirte qué modelo te queda bien, cuál te
queda justo y cuál no te cabe. Es una heurística sobre la memoria, no una
medición: si el equipo se siente lento, baja de modelo.

El modelo tiene que soportar **tool calling** o el ayudante no puede consultar
tu cartera. Los que sugiere el asistente cumplen: `llama3.1`, `qwen2.5`,
`mistral-nemo`, `firefunction-v2`.

Cualquier endpoint compatible con la API de OpenAI sirve (Ollama, LM Studio,
vLLM): se captura la URL base, el modelo y, si aplica, una llave.

### La IA de otra computadora de tu oficina

Variante de la anterior, para cuando hay una sola máquina buena y varias flojas:
esa comparte su modelo y las demás lo usan. En el asistente de primer arranque,
"En la red de tu oficina" barre tu subred local cuando tú lo pides (nunca sola) y
lista lo que encontró por nombre de equipo, listo para conectar.

Lo honesto de esta vía: lo que tus ayudantes leen y redactan viaja por tu red
hasta ese equipo. Se queda en tu oficina, pero ya no es solo tu máquina.

## Probar que quedó

En Ajustes, en Tu IA, el botón **Probar que responde** hace una llamada real y
dice si tu IA contestó o, si no, por qué (la llave, el permiso, el límite, la red). Desde
la terminal, `aiuda doctor` dice si hay proveedor conectado, si ya tienes Claude
Code o Codex instalados y si Ollama responde.

## Cuánto llevas gastado

Cada llamada a la IA deja un registro con modelo, tarea y tokens. El uso del mes,
con un costo estimado a partir de una tabla de precios local, se consulta en
`GET /v1/usage`. Todavía no hay una pantalla que lo muestre: está pendiente. Y
un hueco que conviene saber: para OpenAI con llave esa tabla todavía no trae
precio, así que ahí el uso se cuenta pero el costo sale en cero.

Con el programa que ya tienes y con Entrar con ChatGPT el costo también sale en
cero, y ahí sí es lo correcto: lo cubre el plan que ya pagas. Los tokens se
cuentan igual (los de ChatGPT aparecen como `chatgpt-plan`) y el tope mensual de
abajo aplica igual. Cuánto de tu plan llevas gastado lo dice ChatGPT, en
"Administrar uso", no aiuda.

También existe un tope mensual de tokens, y viene puesto de fábrica: 5 millones
de tokens al mes. No es un cobro nuestro (nosotros no cobramos nada y nunca vemos
tu llave): es el freno para que un mes raro, o una corrida que se atore, no te
sorprenda en el recibo de tu proveedor de IA. Un negocio normal no lo toca: una
corrida de cobranza gasta miles de tokens, no millones.

Cuando se agota, aiuda deja de llamar a la IA: no se cuelga a media iteración,
la corrida sigue sin IA, y el aviso queda en la bitácora y arriba del Centro de
mando, donde lo ves al abrir y lo puedes descartar. Para moverlo se escribe
`ia_tope_tokens_mes` en la configuración del negocio (todavía no hay pantalla
para eso); con `0` te quedas sin tope, bajo tu propio riesgo.

Y para que la primera corrida no se lleve el mes entero, cada corrida redacta
como máximo 20 recordatorios; lo que no cupo sale en la siguiente (son cada
hora). También se mueve, con `max_borradores_corrida`.

## Cambiar o desconectar

En Ajustes, en Tu IA, puedes reemplazar el secreto o desconectar. Al desconectar se
borra la credencial cifrada; nada más se pierde.

Si lo conectado era tu cuenta de ChatGPT, al desconectar aiuda le avisa a OpenAI
que la sesión terminó y borra el permiso de esta computadora. Si no logra
avisarle (sin internet, por ejemplo), lo borra igual y te lo dice, para que
quites aiuda tú desde la configuración de ChatGPT. La aplicación registrada en tu
cuenta no se borra sola: así, si vuelves a entrar, no se crea otra.
