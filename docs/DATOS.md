# Tus datos: dónde viven, cómo respaldarlos, cómo borrarlos

Todo lo que aiuda sabe de tu negocio cabe en una carpeta: `~/.aiuda/`. No hay
servidor nuestro, no hay cuenta, no hay telemetría. Si borras esa carpeta, no
queda nada en ningún lado.

## Qué hay en `~/.aiuda/`

| Archivo | Qué es |
|---|---|
| `aiuda.db` | La base SQLite: todo tu negocio (ver abajo) |
| `aiuda.db-wal`, `aiuda.db-shm` | Archivos temporales de SQLite mientras aiuda corre |
| `key` | La llave de cifrado, permisos 0600. Se genera sola en el primer arranque |
| `sesion.json` | La llave de la ventana abierta ahorita. Se borra sola al cerrar aiuda |
| `red-local.crt`, `red-local.key` | La identidad de esta computadora frente a tus aparatos. Aparecen si prendes la red del negocio ([APARATOS.md](APARATOS.md)) |
| `wacli_inbound*.json` | Hasta qué mensaje de WhatsApp se leyó (marcador del sondeo) |
| `dev/` | Logs y PIDs si usas `scripts/dev.sh` (desarrollo) |

Dentro de `aiuda.db` está tu cartera (facturas, clientes, productos), las
conversaciones, los recordatorios con su estado, las promesas de pago, la
conciliación, la bitácora de aprobaciones, los aparatos que dejaste entrar y la
configuración del negocio.

Cifrado con la llave de `key`, dentro de la misma base:

- Las credenciales de tus conectores y el secreto de tu proveedor de IA.
- Las sesiones de portales que capturaste con el handoff del CUA (cookies y
  storage ya autenticados; tu contraseña no se guarda nunca). Ver
  [CUA.md](CUA.md).

De los aparatos emparejados **no** se guarda su llave, solo su huella: quien se
lleve la base no se lleva la entrada de ningún teléfono.

Fuera de `~/.aiuda`: si usas WhatsApp con tu número, wacli guarda su propia
sesión en su carpeta, no en la nuestra. Y la app de escritorio deja sus logs en
la bitácora del sistema.

## Tu estado de cuenta bancario (PDF)

No necesitas open banking para conciliar: el PDF que tu banco ya te manda cada
mes alcanza. En **Conciliación** (o en **Importar datos**) arrastras el PDF,
aiuda te enseña qué leyó y si los movimientos cuadran contra el saldo inicial y
final del estado, y solo cuando tú apruebas, los depósitos entran a la bandeja
de conciliación. Ahí tu ayudante propone qué factura liquida cada depósito y tú
confirmas, como con cualquier otro pago.

Lo que hay que saber, sin adornos:

- **BBVA y Banorte se leen directo**, sin IA y sin costo. Estos dos formatos
  están verificados contra estados de cuenta reales.
- **Cualquier otro banco lo lee tu IA** (la que conectaste en Proveedor de IA).
  El texto del estado se le pasa a tu proveedor; si eso te incomoda, usa un
  modelo local con Ollama y nada sale de tu computadora. Cada monto que la IA
  reporte se verifica contra el texto del PDF: un monto que no está en el papel
  se rechaza completo.
- **Si no cuadra, no entra.** La suma de depósitos y retiros tiene que cerrar
  contra los saldos del estado. Si hay diferencia, aiuda te lo dice y no importa
  nada a ciegas.
- **Subir el mismo estado dos veces no duplica**: cada movimiento se reconoce
  por su fecha, monto y referencia.
- **Los PDFs escaneados (pura imagen) todavía no se pueden leer.** Descarga el
  PDF original desde tu banca en línea; ese sí trae texto.
- **El PDF no se guarda**: aiuda toma los depósitos que apruebas y ya. Los
  cargos (lo que salió de tu cuenta) solo se muestran en la previa; la
  conciliación es de dinero que te llega.

## Respaldar

Lo más simple, y lo que recomendamos: **cierra aiuda y copia la carpeta
completa** a donde guardes tus respaldos. Es una carpeta como cualquier otra, no
hace falta ninguna terminal.

En una Mac, la carpeta está oculta y se llega así:

1. Abre **Finder**.
2. Menú **Ir > Ir a la carpeta** (o `Cmd` + `Shift` + `G`).
3. Escribe `~/.aiuda` y dale Enter.
4. Copia esa carpeta a tu disco externo o a donde respaldes.

Es todo. Guárdala como guardarías la carpeta de tu contabilidad, porque eso es.

Lo mismo desde la terminal, para quien la prefiera:

```sh
mkdir -p ~/respaldos
cp -R ~/.aiuda ~/respaldos/aiuda-2026-07-27
```

Si prefieres no cerrar nada, SQLite sabe copiarse en caliente:

```sh
mkdir -p ~/respaldos
sqlite3 ~/.aiuda/aiuda.db ".backup '$HOME/respaldos/aiuda.db'"
cp ~/.aiuda/key ~/respaldos/aiuda.key
```

**La llave va con la base.** Un respaldo con `aiuda.db` pero sin `key` te deja
los datos legibles y las credenciales inservibles. Guarda `key` como guardas una
contraseña: quien la tenga junto con la base puede leer tus credenciales.

Restaurar es copiar de vuelta los dos archivos con aiuda cerrado.

Aparte del respaldo técnico, cada lista de la consola baja como `.xlsx` con lo
que estás viendo: sirve para llevarte los datos a otro lado o revisarlos sin
aiuda.

## Borrar todo

Cierra aiuda, llega a `~/.aiuda` con los mismos pasos de arriba y manda esa
carpeta a la basura. Desde la terminal es una línea:

```sh
rm -rf ~/.aiuda
```

Eso borra tu negocio de esta computadora, sin vuelta atrás. Si además quieres
quitar el programa, borra la app (macOS: `/Applications/aiuda.app`) o el clon
del repo. No queda ningún servicio instalado.

Para borrar solo los datos de demostración:

```sh
uv run python scripts/seed.py --wipe
```

## La llave de cifrado

Vive en `~/.aiuda/key`, se genera sola la primera vez y no cambia. Es un archivo
y no el Keychain a propósito: una app sin firmar, una terminal y un doble clic
tienen identidades distintas frente al llavero de macOS, y una llave que a veces
aparece y a veces no significa credenciales que un día ya no abren. El archivo se
comporta igual siempre. Si vienes de una instalación que dejó la llave en el
Keychain, se migra sola al archivo.

Si pierdes la llave, las credenciales cifradas no se recuperan: no hay puerta
trasera. Vuelves a capturarlas en la consola y sigues.

### Administrarla tú (opcional)

Si prefieres manejar la llave por tu cuenta (por ejemplo, una instancia operada
para un tercero), define `AIUDA_ENCRYPTION_KEYS` y esa manda sobre el archivo:

```
AIUDA_ENCRYPTION_KEYS="<llave_fernet>"            # una sola llave
AIUDA_ENCRYPTION_KEYS="2:<llave_v2>,1:<llave_v1>" # rotación
```

Generar una llave nueva:

```sh
uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Se cifra siempre con la versión más alta y se descifra con la versión que se usó
al guardar, que queda anotada en cada fila. Por eso conviven varias.

### Rotar la llave

Regla de oro: **nunca quites una versión del llavero mientras exista una fila
cifrada con ella.**

1. Agrega la nueva sin quitar la vieja: `AIUDA_ENCRYPTION_KEYS="2:<v2>,1:<v1>"`.
2. Re-cifra lo existente (no hay comando todavía, es este bucle corto):

   ```sh
   uv run python - <<'EOF'
   from sqlalchemy import select
   from aiuda_core.db import session_scope
   from aiuda_core.connectors.credentials import read_stored, set_credential
   from aiuda_core.security.crypto import active_key_version
   from aiuda_core.models import IntegrationCredential

   with session_scope() as s:
       n = 0
       for row in s.scalars(select(IntegrationCredential)).all():
           if row.key_version == active_key_version():
               continue
           datos = read_stored(s, row.tenant_id, row.provider)
           estado = row.status
           set_credential(s, row.tenant_id, row.provider, datos)
           row.status = estado
           n += 1
       print(f"re-cifradas: {n}")
   EOF
   ```

3. Verifica que no quede nada con la versión vieja:

   ```sh
   sqlite3 ~/.aiuda/aiuda.db \
     "SELECT key_version, count(*) FROM integration_credentials GROUP BY key_version;"
   ```

4. Quita la vieja del llavero. Guárdala un tiempo por si un respaldo la necesita.

Si al leer aparece "No hay clave para la versión N", regresaste demasiado pronto:
vuelve a poner esa versión y repite. Si la llave se perdió de verdad, hay que
capturar los secretos otra vez.

## Guardar los datos en otro lado

El default es SQLite en tu computadora. Si corres una instancia para varias
personas, `DATABASE_URL` apunta a Postgres (necesita el extra
`aiuda-server[postgres]`). El resto del comportamiento no cambia.
