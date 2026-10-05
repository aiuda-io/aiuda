# SAT y bóveda fiscal

aiuda guarda tus CFDI en esta computadora y puede convertir en cartera los
ingresos a crédito. Admite hasta tres RFCs del mismo negocio.

## Empezar sin e.firma

1. Abre **Integraciones > SAT · Bóveda fiscal**.
2. Registra cada RFC y el plazo de pago que normalmente usas.
3. Sube un XML o el ZIP que descargaste del SAT.

Volver a subir el mismo CFDI no lo duplica: el UUID es su identidad.

## Conectar la e.firma

En la misma pantalla elige el `.cer`, el `.key`, escribe la contraseña y pulsa
**Validar y conectar**. No mandes esos archivos ni la contraseña por chat.

Antes de guardar, aiuda comprueba que:

- el certificado y la llave pertenecen juntos;
- la contraseña abre la llave;
- es una e.firma y no un CSD;
- el certificado sigue vigente.

La e.firma se cifra en el disco. La API y la consola solo vuelven a mostrar RFC,
titular y vigencia. Puedes borrarla por RFC sin borrar los CFDI ya importados.

**Probar con SAT** autentica contra el servicio real sin pedir ni descargar
comprobantes.

## Qué hace con cada CFDI

| CFDI | Resultado |
|---|---|
| Ingreso PPD emitido | Crea una cuenta por cobrar con vencimiento estimado |
| Ingreso PUE | Se guarda en la bóveda; no crea cartera |
| Complemento de pago | Abona o cierra la factura relacionada; nunca crea otra |
| Egreso | Resta a la factura relacionada y la cancela si llega a cero |
| Entre dos RFCs tuyos | Se marca intercompañía y queda fuera de cartera |

El CFDI PPD no incluye plazo. aiuda usa el plazo que elegiste para ese RFC, 30
días por defecto, y siempre lo marca como estimado. Cambiar el plazo solo aplica
a CFDI que entren después.

## Descarga automática

Con e.firma conectada, aiuda le pide al SAT tus emitidos y tus recibidos de cada
RFC **una vez al día**. La Descarga Masiva es asíncrona: aiuda envía la
solicitud y en una vuelta posterior (corre cada hora) recoge los paquetes cuando
el SAT termina de prepararlos. El SAT limita cuántas veces acepta la misma
solicitud, por eso aiuda nunca repite una igual: cada día pide con fechas
nuevas.

La pantalla muestra, por dirección, hasta qué fecha vas al día y lo último que
contestó el SAT, en español:

| Lo que ves | Qué significa |
|---|---|
| El SAT está preparando tus comprobantes | La solicitud se envió; aiuda la recoge en la siguiente vuelta |
| El SAT no tiene comprobantes nuevos en ese periodo | No emitiste o no recibiste nada en esas fechas |
| El SAT ya no acepta otra solicitud para ese mismo periodo | Límite del SAT; aiuda pide mañana con fechas nuevas |
| El SAT ya tiene en curso una solicitud igual | aiuda espera y vuelve a pedir mañana |
| El SAT no pudo preparar la solicitud | Falla del lado del SAT; aiuda vuelve a pedir mañana |
| El SAT no contestó | La solicitud pudo haber llegado, así que hoy no se repite; aiuda vuelve a pedir mañana |
| Esta vuelta no se pudo completar | Un tropiezo al recoger o guardar; se reintenta en la siguiente vuelta |
| No se pudieron leer los comprobantes que entregó el SAT | Tras varios intentos aiuda suelta ese paquete y lo pide de nuevo mañana |

Cada paquete que baja se guarda cifrado antes de importarlo. Si algo falla al
importar, aiuda reintenta desde esa copia en vez de volver a descargarlo, y la
borra cuando termina bien. Si después de tres intentos no se puede leer, la
borra y pide el periodo otra vez al día siguiente. Un comprobante suelto que no
se pueda guardar se omite con un aviso y los demás del paquete entran.

Si borras la e.firma de una empresa, también se borra lo que estuviera a medias
con el SAT: la solicitud pendiente y los paquetes bajados sin importar.

## Facturas canceladas

Una vez al día aiuda también le pide al SAT la lista de comprobantes cancelados
de cada RFC. Cuando una factura a crédito que ya estaba en tu cartera aparece
cancelada:

- sale de la cartera y queda como **Cancelada en el SAT**, con la fecha;
- los recordatorios que estaban por aprobar o por enviar se retiran, y aiuda
  dice por qué;
- no se le vuelve a redactar ni a mandar nada.

El CFDI se queda en la bóveda, marcado como cancelado.

Si cancelaste una factura y la **volviste a timbrar con el mismo folio**, aiuda
se queda con el comprobante vigente y la sigue cobrando: no sale de la cartera,
o regresa a ella si ya había salido.

Lo que conviene saber:

- **Puede tardar hasta un día** en reflejarse, porque la lista se pide una vez
  al día.
- **Cancelación en proceso.** Si cancelaste una factura que necesita que tu
  cliente acepte, el SAT la sigue reportando vigente hasta que acepte o venza el
  plazo. Mientras tanto aiuda la ve abierta. Si no quieres que se cobre, rechaza
  sus recordatorios.
- **Pagos y notas de crédito cancelados.** Si cancelas un complemento de pago o
  una nota de crédito que aiuda ya había aplicado, queda marcado como cancelado
  en la bóveda pero la factura no se reabre sola.
- **Facturas que vienen de otro sistema.** Si la factura llegó de Odoo o de un
  Excel y su comprobante no trae el folio fiscal, aiuda no puede probar que sea
  la cancelada: no la cierra sola, te avisa para que la revises.
- **Recibidos.** El SAT ya no entrega el XML de un CFDI recibido que está
  cancelado, así que aiuda pide únicamente los vigentes. Si un proveedor cancela
  después un CFDI que ya tenías, queda marcado como cancelado en la bóveda.

## Qué se ha probado contra el SAT real

Con una e.firma vigente, el 4 y 5 de octubre de 2026:

- autenticación, solicitud, verificación, descarga e importación;
- emitidos: facturas a crédito (PPD), de contado (PUE) y recibos de nómina;
- recibidos: facturas y un complemento de pago;
- un periodo sin comprobantes;
- la lista de cancelados de emitidos y de recibidos, leída del SAT real. Con
  ella se cerró una factura cancelada que se había cargado a mano para la
  prueba: su XML nunca se descargó, porque ya estaba cancelada antes de la
  primera descarga.

En esas pruebas cada paquete estuvo listo en menos de dos minutos; el SAT puede
tardar más.

Todavía **sin probar en vivo** (están programados y probados con datos de
prueba):

- complementos de pago y notas de crédito **emitidos** por ti;
- la cadena completa de una cancelación: una factura que aiuda descargó, que
  después se cancela y cuyos recordatorios se retiran;
- una factura cancelada y vuelta a timbrar con el mismo folio;
- un CFDI **recibido** que después se cancela;
- el SAT sin contestar, o entregando un paquete que no se puede leer;
- un periodo tan grande que el SAT lo parta en varios paquetes;
- los límites del SAT por solicitud repetida;
- más de un RFC conectado al mismo tiempo.

aiuda solo usa la e.firma. No hay descarga con contraseña CIEC.

## Prueba técnica en vivo

Quien opere desde terminal puede probar solo la autenticación, sin guardar nada:

```sh
uv run python scripts/prueba-sat.py /ruta/firma.cer /ruta/firma.key
```

El script pide la contraseña de forma oculta. La descarga completa se observa
desde la pantalla y puede tardar varias corridas por el ciclo asíncrono del SAT.
