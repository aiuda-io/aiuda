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

Esta ruta está implementada y probada con dobles del protocolo. La autenticación
y la descarga completas todavía deben verificarse con una e.firma real.

## Prueba técnica en vivo

Quien opere desde terminal puede probar solo la autenticación, sin guardar nada:

```sh
uv run python scripts/prueba-sat.py /ruta/firma.cer /ruta/firma.key
```

El script pide la contraseña de forma oculta. La descarga completa se observa
desde la pantalla y puede tardar varias corridas por el ciclo asíncrono del SAT.
