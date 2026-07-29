# Política de seguridad

aiuda está en desarrollo activo, antes de la versión 1.0. Puede haber fallas.
Agradecemos que los reportes con responsabilidad.

## Reportar una vulnerabilidad

**No abras un issue público** para reportar una vulnerabilidad. Un issue es
visible para todos y expondría el problema antes de que exista un arreglo.

En su lugar, escribe en privado a **consulting@hanova.mx** con:

- Qué encontraste y qué impacto tiene.
- Cómo reproducirlo (pasos, y prueba de concepto si la tienes).
- La versión afectada (commit o tag) y tu sistema operativo.

Si prefieres, también puedes usar el reporte privado de GitHub
("Report a vulnerability" en la pestaña Security del repo).

## Qué esperar

- Respuesta **best-effort**: somos un equipo chico, no ofrecemos un SLA. Haremos
  lo posible por confirmar la recepción en pocos días hábiles.
- Trabajaremos contigo para entender y reproducir el problema.
- Te avisaremos cuando haya un arreglo y, si quieres, te damos crédito por el
  reporte.
- Te pedimos no divulgar públicamente la vulnerabilidad hasta que exista un
  arreglo o lo acordemos contigo.

## Cómo está armado el modelo de seguridad

aiuda corre en tu computadora, así que la mayor parte del perímetro es tuyo:

- El server escucha **solo en 127.0.0.1** y exige un token de sesión que cambia
  en cada arranque (estilo Jupyter). Eso lo aísla de la red y de otros procesos
  o pestañas de la misma máquina.
- Hay una **segunda puerta, apagada por default**, que el dueño puede prender
  desde su consola para que su teléfono le llegue por el WiFi de la oficina. Esa
  puerta es más estricta que la de casa: va por HTTPS con un certificado que la
  máquina se firma sola y cuya huella viaja en el QR del emparejamiento, y
  **siempre** exige el token de un aparato emparejado, aunque aiuda se haya
  arrancado con `--no-token`. Un aparato invitado lee y aprueba dentro de su
  tope; no toca el proveedor de IA, las integraciones, el CUA, los ajustes ni la
  exportación. Cada acción queda en la bitácora con el nombre del aparato que la
  hizo, no como si la hubiera hecho el dueño.
- Las credenciales de conectores y el secreto de tu IA se guardan **cifrados**
  (Fernet) dentro de la base. La llave vive fuera de la base, en `~/.aiuda/key`
  con permisos 0600, y se genera sola. Si la pierdes, esas credenciales ya no se
  pueden leer: no hay puerta trasera. Ver [docs/DATOS.md](docs/DATOS.md).
- aiuda nunca guarda ni pide la contraseña de tus portales. Para operarlos, el
  login lo haces tú y solo se guarda la sesión ya autenticada, cifrada. Ver
  [docs/CUA.md](docs/CUA.md).
- Nada sale a tus clientes sin tu aprobación, y cada aprobación queda en la
  bitácora.

Lo que queda de tu lado: quién tiene acceso físico a la computadora, tus
respaldos (incluida la llave), y la seguridad de una instancia operada para
varios usuarios si decides montar una. Nunca subas secretos al repo: usa `.env`
y un gestor de contraseñas.

Los instaladores de macOS llevan firma ad-hoc, pero todavía no tienen identidad
Developer ID ni notarización. Verifica que el archivo venga de este repo o de
nosotros antes de abrirlo.

Gracias por ayudar a mantener aiuda seguro.
