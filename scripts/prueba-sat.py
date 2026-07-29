#!/usr/bin/env python3
"""Prueba una e.firma contra el SAT sin guardarla ni solicitar CFDI."""

from __future__ import annotations

import argparse
import getpass
from pathlib import Path

from aiuda_core.connectors.sat_descarga import SatDescargaClient, validar_efirma


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Valida una e.firma y autentica contra Descarga Masiva."
    )
    parser.add_argument("cer", type=Path, help="Certificado .cer")
    parser.add_argument("key", type=Path, help="Llave privada .key")
    parser.add_argument("--rfc", help="RFC esperado, para evitar probar la empresa equivocada")
    args = parser.parse_args()

    cer = args.cer.read_bytes()
    key = args.key.read_bytes()
    password = getpass.getpass("Contraseña de la e.firma: ")
    info = validar_efirma(cer, key, password)
    esperado = (args.rfc or "").strip().upper()
    if esperado and info["rfc"] != esperado:
        raise SystemExit(
            f"El certificado es de {info['rfc']}, no del RFC esperado {esperado}."
        )

    resultado = SatDescargaClient(cer, key, password).probar()
    password = ""
    print(f"{resultado['mensaje']} RFC {info['rfc']}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
