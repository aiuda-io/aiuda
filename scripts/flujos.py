#!/usr/bin/env python
"""Todos los flujos adyacentes al journey, contra un servidor vivo, con assertions.

El journey (scripts/journey.py) prueba el camino principal: Odoo, corrida, aprobación,
modo sombra. Aquí van los DEMÁS, que es donde se esconden los no-ops:

  - Importar Excel: clientes, facturas, productos, citas, prospectos.
  - Importar estado de cuenta del banco (PDF).
  - Conciliación: pago detectado, propuesta, confirmar.
  - Cotización.
  - Promesas de pago.
  - Write-back hacia la fuente (outbox).
  - Alta de un conector a la medida y su receta exportable.
  - Exportar a Excel.
  - Bitácora y consumo, los dos endpoints que existen sin pantalla.
  - Opt-out del cliente.

Uso (con la consola ya corriendo con datos):

    uv run aiuda start --no-token --no-browser &
    uv run python scripts/flujos.py

Nada sale a un cliente: el script exige que el modo sombra esté encendido y aborta si
no lo está.
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:4747"
_ok = 0
_fallos: list[str] = []
_avisos: list[str] = []


def pedir(metodo: str, ruta: str, cuerpo=None, archivo=None, campos=None):
    """HTTP mínimo sin dependencias. Devuelve (status, json|texto)."""
    url = BASE + ruta
    datos, headers = None, {}
    if archivo is not None:
        nombre, contenido, tipo = archivo
        limite = "----aiudaflujos"
        partes = []
        for k, v in (campos or {}).items():
            partes.append(
                f"--{limite}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode()
            )
        partes.append(
            f'--{limite}\r\nContent-Disposition: form-data; name="file"; '
            f'filename="{nombre}"\r\nContent-Type: {tipo}\r\n\r\n'.encode()
            + contenido
            + b"\r\n"
        )
        partes.append(f"--{limite}--\r\n".encode())
        datos = b"".join(partes)
        headers["Content-Type"] = f"multipart/form-data; boundary={limite}"
    elif cuerpo is not None:
        datos = json.dumps(cuerpo).encode()
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=datos, headers=headers, method=metodo)
    try:
        with urllib.request.urlopen(req, timeout=120) as res:
            crudo = res.read()
            try:
                return res.status, json.loads(crudo)
            except (json.JSONDecodeError, UnicodeDecodeError):
                return res.status, crudo  # binario (un .xlsx, por ejemplo)
    except urllib.error.HTTPError as e:
        crudo = e.read()
        try:
            return e.code, json.loads(crudo)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return e.code, crudo.decode("utf-8", "replace")[:300]
    except Exception as e:  # servidor caído, timeout
        return 0, str(e)


def seccion(t: str) -> None:
    print(f"\n\033[1m{t}\033[0m")


def revisar(cond: bool, msg: str) -> None:
    global _ok
    if cond:
        _ok += 1
        print(f"   \033[32mok\033[0m  {msg}")
    else:
        print(f"   \033[31mFALLA\033[0m  {msg}")
        _fallos.append(msg)


def aviso(msg: str) -> None:
    _avisos.append(msg)
    print(f"   \033[33m--\033[0m  {msg}")


def _xlsx(filas: list[list], hoja: str = "Hoja1") -> bytes:
    """Un .xlsx mínimo, sin depender de openpyxl para escribir."""
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = hoja
    for f in filas:
        ws.append(f)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def main() -> int:
    global BASE
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=BASE)
    args = ap.parse_args()
    BASE = args.base

    code, salud = pedir("GET", "/health")
    if code != 200:
        print(f"La consola no responde en {BASE}. Arráncala con: uv run aiuda start --no-token")
        return 2

    code, sombra = pedir("GET", "/v1/settings/modo-sombra")
    if code != 200 or not sombra.get("modo_sombra"):
        print("\033[31mEl modo sombra está APAGADO. No corro: podría salir algo a un cliente.\033[0m")
        print('Enciéndelo con: PUT /v1/settings/modo-sombra {"activo": true}')
        return 2
    print(f"modo sombra encendido, nada sale a clientes  ·  {BASE}")

    # ---------------------------------------------------------------- Excel
    seccion("Importar un Excel: la IA reconoce qué trae")
    hoja = _xlsx(
        [
            ["Cliente", "Telefono", "Correo"],
            ["Refaccionaria del Golfo", "2291234567", "pagos@refagolfo.mx"],
            ["Tortillería La Espiga", "2299876543", "contacto@laespiga.mx"],
        ]
    )
    code, r = pedir(
        "POST", "/v1/import/analyze", archivo=("clientes.xlsx", hoja, "application/vnd.ms-excel")
    )
    revisar(code == 200, f"analiza el archivo sin importarlo ({code})")
    if code == 200:
        revisar(bool(r.get("entity")), f"propone qué es: {r.get('entity')} (confianza {r.get('confidence')})")
        revisar(bool(r.get("mapping")), f"y mapea las columnas solo: {r.get('mapping')}")
        entidad = r.get("entity") or "clientes"
        code2, r2 = pedir(
            "POST",
            "/v1/import/commit",
            archivo=("clientes.xlsx", hoja, "application/vnd.ms-excel"),
            campos={"entity": entidad, "mapping": json.dumps(r.get("mapping") or {})},
        )
        revisar(code2 == 200, f"y lo importa al confirmar ({code2})")
        if code2 == 200:
            revisar(
                (r2.get("created") or 0) > 0 or (r2.get("skipped") or 0) > 0,
                f"procesa los renglones: {r2.get('created')} nuevos, {r2.get('skipped')} ya estaban",
            )
            revisar(
                not (r2.get("created") == 0 and r2.get("skipped", 0) > 0 and not r2.get("errors")),
                "y si no entra nada, DICE por qué (nada de no-ops mudos)",
            )

        # Y el modo de fallo que importa: sin mapeo, no puede quedarse callado.
        code3, r3 = pedir(
            "POST", "/v1/import/commit",
            archivo=("clientes.xlsx", hoja, "application/vnd.ms-excel"),
            campos={"entity": entidad},
        )
        revisar(
            code3 == 200 and bool(r3.get("errors")),
            f"sin mapeo explica el problema en vez de callarse: {(r3.get('errors') or [''])[0][:90]}",
        )

    # ---------------------------------------------------------------- banco
    seccion("Importar el estado de cuenta del banco")
    code, r = pedir(
        "POST",
        "/v1/banco/analizar",
        archivo=("estado.pdf", b"%PDF-1.4\n(no es un PDF real)\n%%EOF", "application/pdf"),
    )
    if code == 200:
        revisar(True, "el endpoint acepta el PDF y contesta")
        aviso(f"con un PDF falso devuelve: {str(r)[:120]}")
    elif code in (400, 422):
        revisar(True, f"rechaza un PDF inválido con {code}, honesto")
        aviso(f"detalle: {str(r)[:140]}")
    else:
        revisar(False, f"respuesta inesperada del análisis bancario: {code} {str(r)[:140]}")

    # ---------------------------------------------------------------- conciliación
    seccion("Conciliación: el pago que el cliente dice que hizo")
    code, facturas = pedir("GET", "/v1/invoices?status=open")
    revisar(code == 200 and len(facturas) > 0, f"hay cartera abierta ({len(facturas) if code==200 else 0})")
    if code == 200 and facturas:
        f = facturas[0]
        code, pago = pedir(
            "POST",
            "/v1/payments",
            {"amount": f["amount"], "reference": "SPEI prueba flujos", "invoice_id": f["id"]},
        )
        revisar(code == 201, f"se registra un pago a mano ({code})")
        if code == 201:
            code, bandeja = pedir("GET", "/v1/reconciliation")
            revisar(code == 200 and bandeja.get("count", 0) > 0, "y cae en la bandeja de conciliación")
            pend = (bandeja.get("pending") or [{}])[0]
            prop = pend.get("proposal") or {}
            revisar(
                prop.get("folio") == f["folio"],
                f"con la factura propuesta por monto: {prop.get('folio')}",
            )
            revisar(
                pago.get("status") == "pendiente",
                "el pago NO cierra la factura solo: espera al humano",
            )
            code, _ = pedir("POST", f"/v1/reconciliation/{pago['id']}/confirm", {"invoice_ids": [f["id"]]})
            revisar(code == 200, f"y el humano lo confirma ({code})")

    # ---------------------------------------------------------------- promesas
    seccion("Promesas de pago")
    code, promesas = pedir("GET", "/v1/promises")
    revisar(code == 200, f"la lista responde ({code})")

    # ---------------------------------------------------------------- cotización
    seccion("Cotización")
    code, productos = pedir("GET", "/v1/products")
    code_c, clientes = pedir("GET", "/v1/customers")
    if code == 200 and productos and code_c == 200 and clientes:
        code, q = pedir(
            "POST",
            "/v1/quotes",
            {"customer_id": clientes[0]["id"], "items": [{"product_id": productos[0]["id"], "cantidad": 2}]},
        )
        revisar(code in (200, 201), f"se genera y cae en aprobaciones ({code})")
        if code in (200, 201):
            revisar("id" in q, f"con id de propuesta: {str(q)[:120]}")
    else:
        aviso(f"sin catálogo ({len(productos) if code==200 else 0} productos) o sin clientes: no se probó")

    # ---------------------------------------------------------------- write-back
    seccion("Write-back: lo confirmado regresa a tu sistema")
    code, wb = pedir("GET", "/v1/writeback")
    revisar(code == 200, f"la cola de inyecciones responde ({code})")
    if code == 200:
        entradas = wb if isinstance(wb, list) else wb.get("entries") or wb.get("entradas") or []
        print(f"       {len(entradas)} en la cola")
    code, destinos = pedir("GET", "/v1/inyectar/destinos")
    revisar(code == 200, f"los destinos se derivan de credenciales reales ({code})")
    if code == 200:
        revisar(
            any(destinos.get(k) for k in destinos) if isinstance(destinos, dict) else False,
            f"y con Odoo conectado hay a dónde inyectar: {destinos}",
        )

    # ---------------------------------------------------------------- conector a la medida
    seccion("Conector a la medida y su receta")
    code, campos = pedir("GET", "/v1/custom-connectors/fields")
    revisar(code == 200, f"dice qué campos hay que mapear ({code})")
    code, creado = pedir(
        "POST",
        "/v1/custom-connectors",
        {
            "name": "ERP de prueba",
            "cap": "cuentas_por_cobrar",
            "base_url": "https://api.ejemplo.mx",
            "list_path": "/facturas",
        },
    )
    revisar(code in (200, 201), f"se crea sin tocar el repo ({code})")
    if code in (200, 201):
        cid = creado.get("id")
        code, receta = pedir("GET", f"/v1/custom-connectors/{cid}/receta")
        revisar(code == 200, "y se puede exportar como receta")
        if code == 200:
            revisar(
                "secret" not in json.dumps(receta).lower()
                and "api_key" not in json.dumps(receta).lower(),
                "la receta NO lleva secretos: es compartible",
            )
        pedir("DELETE", f"/v1/custom-connectors/{cid}")

    # ---------------------------------------------------------------- export
    seccion("Exportar a Excel")
    for entidad in ("facturas", "clientes"):
        code, crudo = pedir("GET", f"/v1/export/{entidad}.xlsx")
        revisar(
            code == 200 and isinstance(crudo, bytes) and crudo[:2] == b"PK",
            f"{entidad}.xlsx sale como Excel de verdad ({code})",
        )

    # ---------------------------------------------------------------- lo que existe sin pantalla
    seccion("Los dos endpoints que existen y ninguna pantalla lee")
    code, aud = pedir("GET", "/v1/audit")
    revisar(code == 200, f"bitácora: {code}")
    if code == 200:
        filas = aud if isinstance(aud, list) else aud.get("entries") or aud.get("items") or []
        revisar(len(filas) > 0, f"y ya tiene {len(filas)} movimientos registrados")
        aviso("pero NINGUNA pantalla de la consola la muestra todavía")
    code, uso = pedir("GET", "/v1/usage")
    revisar(code == 200, f"consumo de IA: {code}")
    if code == 200:
        aviso(f"tampoco tiene pantalla. Hoy: {json.dumps(uso, ensure_ascii=False)[:160]}")

    # ---------------------------------------------------------------- opt-out
    seccion("Baja del cliente (BAJA/STOP)")
    code, clientes = pedir("GET", "/v1/customers")
    con_tel = [c for c in clientes if c.get("phone")] if code == 200 else []
    if con_tel:
        cid = con_tel[0]["id"]
        code, r = pedir("POST", f"/v1/customers/{cid}/optout", {"activo": True})
        revisar(code == 200 and r.get("opt_out"), "se registra la baja")
        code, ficha = pedir("GET", f"/v1/customers/{cid}")
        revisar(bool(ficha.get("opt_out")), "y la ficha del cliente la muestra")
        code, lista = pedir("GET", "/v1/customers")
        marcado = next((c for c in lista if c["id"] == cid), {})
        revisar(marcado.get("opt_out") is True, "y la LISTA también, para no ofrecer escribirle")
        pedir("POST", f"/v1/customers/{cid}/optout", {"activo": False})
    else:
        aviso("ningún cliente con teléfono: no se probó la baja")

    # ---------------------------------------------------------------- cierre
    print()
    if _avisos:
        print(f"\033[33m{len(_avisos)} avisos (no son fallas):\033[0m")
        for a in _avisos:
            print(f"  - {a}")
        print()
    if _fallos:
        print(f"\033[31m{len(_fallos)} fallas de {_ok + len(_fallos)} revisiones:\033[0m")
        for f in _fallos:
            print(f"  - {f}")
        return 1
    print(f"\033[32mLos {_ok} chequeos de flujos adyacentes pasan.\033[0m")
    return 0


if __name__ == "__main__":
    sys.exit(main())
