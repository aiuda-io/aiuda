"""Lector de CFDI (factura electrónica del SAT). Extrae los datos fiscales del XML
para mostrarlos y cotejarlos contra la factura en aiuda.

Robusto a la versión (3.3/4.0): empata por nombre local de etiqueta, no por
namespace exacto. El UUID vive en el Timbre Fiscal Digital (complemento), no en
el Comprobante.
"""

import xml.etree.ElementTree as ET


def _local(tag: str) -> str:
    """Nombre de la etiqueta sin namespace: '{...}Comprobante' -> 'Comprobante'."""
    return tag.rsplit("}", 1)[-1]


def _f(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_cfdi(xml: bytes | str) -> dict:
    """Parsea un CFDI y devuelve sus datos fiscales. Lanza ValueError si no lo es."""
    if isinstance(xml, str):
        xml = xml.encode("utf-8")
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise ValueError(f"XML inválido: {exc}") from exc
    if _local(root.tag) != "Comprobante":
        raise ValueError("El XML no es un CFDI (la raíz no es Comprobante).")

    a = root.attrib
    out: dict = {
        "version": a.get("Version") or a.get("version"),
        "serie": a.get("Serie"),
        "folio": a.get("Folio"),
        "fecha": a.get("Fecha"),
        "tipo": a.get("TipoDeComprobante"),
        # PUE (pago en una exhibición: se cobró al emitir) o PPD (a crédito: la
        # cuenta por cobrar de verdad). Decide si un CFDI de ingreso es cartera.
        "metodo_pago": a.get("MetodoPago"),
        "moneda": a.get("Moneda"),
        "subtotal": _f(a.get("SubTotal")),
        "total": _f(a.get("Total")),
        "uuid": None,
        "fecha_timbrado": None,
        "emisor": {},
        "receptor": {},
        "iva": None,
        "conceptos": 0,
        # CFDI relacionados (una nota de crédito apunta a la factura que resta):
        # [{"uuid": ..., "tipo_relacion": "01"}]. Vacío si no relaciona nada.
        "relacionados": [],
        # Complemento de pagos (tipo P): a qué facturas abona y cuánto queda.
        # [{"id_documento": uuid, "imp_pagado": ..., "imp_saldo_insoluto": ...}]
        "pagos": [],
    }
    tipo_relacion = None  # el atributo vive en CfdiRelacionados (el padre)
    for e in root.iter():
        lt = _local(e.tag)
        if lt == "Emisor":
            out["emisor"] = {
                "rfc": e.attrib.get("Rfc"),
                "nombre": e.attrib.get("Nombre"),
                "regimen": e.attrib.get("RegimenFiscal"),
            }
        elif lt == "Receptor":
            out["receptor"] = {
                "rfc": e.attrib.get("Rfc"),
                "nombre": e.attrib.get("Nombre"),
                "uso": e.attrib.get("UsoCFDI"),
            }
        elif lt == "TimbreFiscalDigital":
            out["uuid"] = e.attrib.get("UUID")
            out["fecha_timbrado"] = e.attrib.get("FechaTimbrado")
        elif lt == "Impuestos" and e.attrib.get("TotalImpuestosTrasladados") is not None:
            # Impuestos a nivel comprobante (no el de cada concepto): el IVA trasladado.
            out["iva"] = _f(e.attrib.get("TotalImpuestosTrasladados"))
        elif lt == "Concepto":
            out["conceptos"] += 1
        elif lt == "CfdiRelacionados":
            # root.iter() va en orden de documento: el padre llega antes que sus hijos.
            tipo_relacion = e.attrib.get("TipoRelacion")
        elif lt == "CfdiRelacionado" and e.attrib.get("UUID"):
            out["relacionados"].append(
                {"uuid": e.attrib["UUID"].upper(), "tipo_relacion": tipo_relacion}
            )
        elif lt == "DoctoRelacionado" and e.attrib.get("IdDocumento"):
            # Complemento de pagos 1.0/2.0: mismo nombre local en ambos.
            out["pagos"].append(
                {
                    "id_documento": e.attrib["IdDocumento"].upper(),
                    "imp_pagado": _f(e.attrib.get("ImpPagado")),
                    "imp_saldo_insoluto": _f(e.attrib.get("ImpSaldoInsoluto")),
                }
            )
    if out["uuid"]:
        out["uuid"] = out["uuid"].upper()  # el UUID es la identidad: una sola forma
    return out
