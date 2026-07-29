# Tu teléfono y tu equipo

aiuda vive en una computadora: la del negocio. Esta parte es para que tu celular,
y el de quien trabaja contigo, entren a ese mismo aiuda sin salir del WiFi de tu
local. Nada sube a internet y no hay cuenta que crear.

Está en la consola, en **Tus aparatos**.

## Lo honesto, antes de que le dediques tiempo

Del lado de la computadora está armado y probado: prender la red, enseñar el
código, los papeles, sacar un aparato y el candado que deja fuera a quien no
invitaste.

**La app del teléfono todavía no existe.** El código que aparece en pantalla
abre `aiuda://emparejar`, y hoy ningún teléfono tiene instalado nada que
responda a eso. Si le apuntas la cámara, no va a pasar nada.

Entonces: puedes prender la red y ver la pantalla completa, pero **todavía no
vas a aprobar desde tu celular**. Esto se documenta ahora porque la mitad de la
computadora ya viaja en la app, no porque el teléfono ya sirva.

Lo demás que conviene saber de una vez:

- Lo que sí está probado, con pruebas automáticas, es el candado: los papeles, el
  tope, que un invitado no se ascienda solo y que sacar un aparato lo deje fuera
  de inmediato. Probado contra el API, no con un teléfono real.
- Probado en **macOS con chip Apple**. En Windows y Linux el mismo código corre,
  pero nadie lo ha probado. El aviso de permiso que se explica abajo es cosa de
  macOS.

## Qué es, en una frase

Mientras la red está apagada, aiuda solo se habla a sí mismo: nada más responde
en esta computadora. Al prenderla se abre una **segunda puerta**, la que da a tu
red, y por ahí solo pasa un aparato que tú dejaste entrar.

Son dos puertas del mismo aiuda: la misma base, los mismos ayudantes, la misma
bitácora. No es una copia ni una sincronización.

## Prenderla

1. En la consola, entra a **Tus aparatos**.
2. Botón **Prender**.
3. Aparece la dirección de esta computadora en tu red (algo como
   `192.168.1.50`). Esa es la señal de que quedó.

Dos cosas que pasan al prenderla:

- Si esta computadora no está conectada a ninguna red, aiuda no la prende y te
  lo dice. Conéctala al WiFi del negocio y vuelve a intentar.
- La primera vez, macOS pregunta si aiuda puede buscar aparatos en tu red local.
  **Dile que sí.** Si le diste al lado, abajo está cómo arreglarlo.

Queda prendida hasta que tú la apagues, también si cierras aiuda y lo vuelves a
abrir: es una decisión tuya, no de la sesión. Apagarla deja a todos los aparatos
fuera de inmediato, sin borrar a nadie de la lista.

## El permiso de red local de macOS

Es el tropiezo más común y el más difícil de adivinar, porque cuando falta **no
sale ningún error**: simplemente el teléfono nunca encuentra la computadora.

macOS pregunta una sola vez, y si dijiste "No permitir" no vuelve a preguntar.
La pantalla de Tus aparatos lo detecta y te lo dice con todas sus letras: "Tu Mac
no está dejando que aiuda vea la red". Ahí mismo hay un botón **Abrir Ajustes**
que te deja parado en el panel exacto.

A mano, es: **Ajustes del sistema > Privacidad y seguridad > Red local**, y
prender el interruptor de aiuda. Regresa a la consola y dale a **Ya lo permití**.

Un detalle que confunde: si mueves la app de lugar o instalas una versión nueva,
macOS puede volver a tratarla como un programa distinto y pedir el permiso otra
vez.

## El código que aparece en pantalla

**Sumar un aparato** enseña un código cuadrado. Lo que lleva dentro:

| Qué | Para qué |
|---|---|
| La dirección y el puerto de esta computadora | Para que el teléfono sepa a dónde tocar |
| La huella del certificado de esta computadora | Para que acepte a **esta** máquina y a ninguna otra |
| Un código de un solo uso | Es lo que autoriza la entrada |
| El nombre de tu negocio | Para que el teléfono muestre a quién se está uniendo |

El código **dura cinco minutos y sirve una sola vez**. Si cierras la pantalla o
le das a Cancelar, deja de servir en ese momento. Si aiuda se reinicia, también:
un código de entrada no es algo que deba sobrevivir a nada.

Lo de la huella vale la pena entenderlo, porque es lo que hace segura una red de
oficina donde no controlas quién más está conectado. El teléfono no confía en
una lista de autoridades de internet como hace un navegador: confía en **una
sola huella**, la que vio con su cámara en tu pantalla. Si alguien se pone en
medio y responde por la computadora, la huella no le cuadra y el teléfono no
habla con él.

Prender la red no le abre nada a nadie: quien toque el puerto sin ser un aparato
emparejado recibe un "este aparato no está emparejado" y hasta ahí. Lo único que
se contesta sin llave es el propio emparejamiento, porque el teléfono todavía no
tiene ninguna, y ahí hay freno: se aceptan pocos intentos por minuto para que
nadie pueda tumbar tu aiuda a fuerza de tocar la puerta.

## Los papeles

Al enseñar el código eliges con qué papel entra quien lo escanee.

**Como dueño.** Aprueba lo que sea, prende y apaga la red, invita a otros
aparatos y los saca. Es tu propio teléfono. No se lo des a nadie más.

**Como invitado.** Entra al mismo aiuda con menos manos. Puede ver todo y hacer
el trabajo del día: aprobar dentro de su tope, rechazar, responder, conciliar.

Lo que un invitado **no** toca nunca, aunque su teléfono esté emparejado:

| No puede | Por qué |
|---|---|
| Cambiar el proveedor de IA | Apuntar la IA a otro lado manda tu cartera a donde diga quien lo cambió |
| Tocar integraciones y conectores | Ahí viven las llaves de tus sistemas |
| Encargar misiones del navegador (CUA) | Usarían las sesiones de portales que tú ya dejaste abiertas |
| Cambiar la configuración del negocio | Ahí se apaga el modo sombra, o sea, ahí se sueltan mensajes a clientes reales |
| Exportar o importar | Es llevarse el negocio completo en un archivo |
| Invitar o sacar aparatos, prender la red | Sería darse a sí mismo la llave |

Al invitado puedes ponerle un **hasta cuánto puede aprobar solo**. Ese número sí
corta: al aprobar, aiuda compara con el monto de la factura y si se pasa, no
deja y lo dice. **Vacío significa que no aprueba nada**, ni lo chico: ve,
propone y tú apruebas.

Cada aprobación queda en la bitácora con el nombre del aparato que la hizo. Lo
que aprobó el teléfono de alguien de tu equipo no queda firmado como tuyo.

## Sacar un aparato

En la lista, botón **Sacar**. Queda fuera de inmediato: su llave deja de servir
en la siguiente petición que haga, sin esperar a nada.

El renglón no se borra. Sigue ahí, marcado como fuera y con la fecha. Es a
propósito: mereces poder ver que ese teléfono estuvo dentro y cuándo salió.

Desde el aparato del dueño no puedes sacarte a ti mismo, para que nadie se quede
sin manera de entrar por un dedazo.

## Qué se guarda de cada aparato

El nombre que puso, su papel, su tope, cuándo se le vio la última vez y, si
salió, cuándo. De su llave **solo se guarda la huella**, nunca la llave. Si
alguien se lleva tu base de datos, no se lleva las llaves de los teléfonos.

Al prender la red, aiuda crea el certificado de esta computadora en
`~/.aiuda/red-local.crt` y `~/.aiuda/red-local.key`. Se lo firma ella a sí misma
y dura diez años a propósito: no es un certificado de internet, es la identidad
de tu máquina para los teléfonos que ya la conocen. Ver [DATOS.md](DATOS.md).

## Si el teléfono no encuentra la computadora

Cuando exista la app, esta es la lista corta:

- **El permiso de red local**, arriba. Es la causa número uno en macOS.
- **El mismo WiFi.** Muchos módems tienen una red de invitados que aísla a los
  aparatos entre sí: ahí no se ven aunque estén a un metro.
- **La red apagada.** Revisa que en Tus aparatos diga la dirección.
- **La computadora dormida.** aiuda no contesta si la Mac está suspendida.

Si aiuda no logra anunciarse en tu red, la pantalla lo dice y sigue sirviendo: el
teléfono usa la dirección que venía en el código. Lo que se pierde es
reencontrarla sola cuando el módem le cambie la dirección a la computadora.

## Lo que no es

- **No es acceso desde la calle.** Solo funciona dentro de tu red. aiuda no abre
  ningún puerto hacia internet ni pasa por servidor de nadie.
- **No son cuentas.** No hay correo ni contraseña: es el aparato el que queda
  emparejado, y se saca igual de fácil.
- **No es multiusuario.** Sigue siendo un negocio por instalación. Varios
  aparatos, la misma bitácora.
