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

Con e.firma conectada, la corrida horaria atiende emitidos y recibidos por RFC.
La Descarga Masiva es asíncrona: una corrida puede enviar la solicitud y otra
posterior recoger los paquetes cuando el SAT termine de prepararlos.

La pantalla muestra, por dirección, la última fecha cubierta o si hay una
solicitud pendiente. Un rechazo definitivo del SAT se conserva para no repetir
la misma solicitud y agotar el servicio.

Esta ruta se probó contra el SAT real el 4 de octubre de 2026 con una e.firma
vigente: autenticación, solicitud, verificación, descarga e importación, en
emitidos y recibidos. En esa prueba el paquete de emitidos estuvo listo en menos
de un minuto; el SAT puede tardar más.

Dos límites que conviene conocer:

- **Recibidos: solo vigentes.** El SAT ya no entrega el XML de un CFDI recibido
  que está cancelado, así que aiuda pide únicamente los vigentes.
- **Cancelaciones posteriores.** Un CFDI que emitiste y cancelas después de que
  aiuda lo descargó no se actualiza solo: la descarga trae los vigentes del
  periodo, no avisa de lo que se canceló más tarde. Una factura a crédito que
  cancelas después sigue apareciendo abierta en aiuda.

## Opinión de cumplimiento y constancia de situación fiscal

Con la e.firma conectada, aiuda también puede bajarte del portal del SAT estos
dos documentos en PDF:

1. Abre **Rutinas**. Hay un bloque por cada RFC con e.firma.
2. La primera vez te pide permiso, una sola vez por RFC: para bajarlos, aiuda
   entra al portal con la e.firma que guardaste y escribe su contraseña por ti.
   La firma se hace en esta computadora; la llave y la contraseña no se mandan a
   nadie.
3. Pulsa **Bajar ahora** en el documento que quieras. Tarda cerca de un minuto.

El PDF queda guardado en esta computadora. Lo ves en Rutinas y en esta misma
pantalla del SAT, en el bloque **Documentos**, con la fecha y, en la opinión, su
sentido (Positivo o Negativo).

Lo que conviene saber:

- No usa tu IA: sigue un guion fijo y funciona aunque no tengas ninguna conectada.
- Solo consulta y descarga. No presenta, no firma ni acepta nada. Si el portal
  pide aceptar algo o muestra un captcha, se detiene y te lo dice.
- Cada vez que bajas la opinión, el SAT le pone un folio nuevo.
- La app de escritorio todavía no trae el navegador que hace falta; ahí la
  pantalla lo avisa.
- Todavía lleva el sello «Sin estrenar»: dentro de aiuda solo se ha corrido contra
  un portal de prueba. Los detalles están en [CUA.md](CUA.md).

## Prueba técnica en vivo

Quien opere desde terminal puede probar solo la autenticación, sin guardar nada:

```sh
uv run python scripts/prueba-sat.py /ruta/firma.cer /ruta/firma.key
```

El script pide la contraseña de forma oculta. La descarga completa se observa
desde la pantalla y puede tardar varias corridas por el ciclo asíncrono del SAT.
