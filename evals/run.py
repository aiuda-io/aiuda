"""Corredor de evals de IA con umbral. Corre APARTE del gate de tests.

Modos:
  --fake            (default) Runner determinista: valida el ARNÉS y los criterios
                    en CI sin red ni credenciales. No mide al modelo.
  --real            Mide al modelo de verdad. Credencial, en este orden:
                      1. ANTHROPIC_API_KEY del entorno (api_key)
                      2. --env <ruta a .env>: lee DATABASE_URL (solo localhost:5434),
                         abre Postgres en SOLO LECTURA, descifra la credencial 'ia'
                         del tenant en memoria y usa make_runner igual que el motor.
                    Con suscripción, el motor usa su modelo barato por default
                    (model_redaccion_suscripcion=haiku): la corrida es barata.

Umbral: >=90% de los casos pasan (por caso: TODOS sus checks). Salida legible por
área y exit code 1 si no se alcanza — para poder colgarlo de un cron/CI aparte.

Uso:
  .venv/bin/python -m evals.run                  # fake, determinista
  .venv/bin/python -m evals.run --real           # con ANTHROPIC_API_KEY
  .venv/bin/python -m evals.run --real --env /ruta/al/.env
  .venv/bin/python -m evals.run --solo clasificacion
"""

import argparse
import json
import re
import sys
from datetime import date

UMBRAL = 0.90


# --------------------------------------------------------------------------- #
# Runner FAKE determinista (CI): pasa los criterios por construcción.          #
# Valida que el arnés detecte regresiones en los checks, no al modelo.         #
# --------------------------------------------------------------------------- #


class FakeEvalRunner:
    """Cumple el Protocol ProviderRunner sin red. Determinista."""

    _usage_callback = None

    def model_for(self, role: str) -> str:
        return f"fake-{role}"

    # --- redacción ---------------------------------------------------------
    def complete(self, system, user, *, model=None, role="redaccion", task="", max_tokens=1024):
        tono = re.search(r"Tono requerido \((\w+)\)", user)
        tono = tono.group(1) if tono else "amable"
        folio = re.search(r"folio (\S+) por", user)
        monto = re.search(r"por \$([\d,]+\.\d{2})", user)
        ref = f" de la factura {folio.group(1)}" if folio else ""
        cantidad = f"${monto.group(1)} MXN" if monto else "el saldo pendiente"
        base = {
            "amable": (
                f"Buen día. Le recordamos que su pago{ref} por {cantidad} vence pronto. "
                "Agradecemos su preferencia y quedamos atentos."
            ),
            "amable_directo": (
                f"Buen día. Su factura{ref} por {cantidad} venció hace unos días. "
                "Le pedimos amablemente realizar el pago o avisarnos si ya lo hizo."
            ),
            "firme": (
                f"Buen día. Su factura{ref} por {cantidad} presenta 20 días de atraso. "
                "Le solicitamos acordar una fecha de pago concreta; estamos para apoyarle."
            ),
            "urgente_escalado": (
                f"Buen día. El saldo{ref} presenta un atraso crítico y el caso fue escalado: "
                "el responsable del negocio se pondrá en contacto con usted personalmente."
            ),
        }[tono]
        if "prometió pagar" in user:
            base += (
                " Nos comentaste... perdón: nos comentó que quedamos en el pago del 30 de junio; "
                "¿nos comparte una nueva fecha concreta?"
            )
        return base

    # --- clasificación ------------------------------------------------------
    def classify(self, system, user, *, labels, task):
        texto = user.lower()
        if any(
            x in texto
            for x in ("pésimo", "cobrando de más", "mal hecho", "nadie me responde", "no me ha llegado", "me siguen cobrando")
        ):
            return "queja"
        if "¿" in user or texto.rstrip().endswith("?"):
            return "pregunta"
        if any(x in texto for x in ("deposito", "transferencia", "les pago")):
            return "promesa_pago"
        return labels[-1]  # pregunta

    # --- chat con tools -----------------------------------------------------
    def run_tool_loop(self, *, system, user_message, tools, execute_tool, model=None,
                      role="redaccion", task="agent_loop", max_iterations=8):
        texto = user_message.lower()
        if "ignora tus instrucciones" in texto:
            return (
                "Esa información no la puedo compartir por este medio. Solo atiendo lo "
                "relacionado con sus propias facturas; el dueño autoriza fuera de este chat."
            )
        if "no pienso pagar" in texto or "compensación" in texto:
            return (
                "Lamento el inconveniente. Ese tema está fuera de mi alcance: lo escalo al "
                "responsable del negocio, que se pondrá en contacto con usted."
            )
        cartera = execute_tool("consultar_cartera", {})
        m = re.search(r"Folio (\S+) \|.*?\$([\d,]+\.\d{2})", cartera)
        if "f-999" in texto:
            return "No encuentro la factura F-999 asociada a su número; su saldo vigente es otro."
        if m is None:
            return "No encuentro facturas abiertas asociadas a su número."
        folio, monto = m.group(1), m.group(2)
        if "deposito el 10 de julio" in texto:
            execute_tool(
                "registrar_promesa_pago",
                {"folio": folio, "fecha_promesa": "2026-07-10", "nota": "eval"},
            )
            return f"Queda registrado su pago para el 10 de julio de la factura {folio}. Gracias."
        if "ya les pagué" in texto or "ya les pague" in texto:
            execute_tool("registrar_pago", {"folio": folio})
            return (
                f"Gracias por avisar. Registré su reporte de pago de {folio}; se confirmará "
                "en cuanto se refleje en el banco."
            )
        return f"Su saldo pendiente es ${monto} MXN de la factura {folio}. ¿Le comparto los datos de pago?"


# --------------------------------------------------------------------------- #
# Runner REAL: mismas vías que el motor                                        #
# --------------------------------------------------------------------------- #


def _runner_real(env_path: str | None):
    import os

    from aiuda_core.engine.provider import (
        ProviderCredential,
        default_credential,
        test_credential,
    )
    from aiuda_core.engine.runner import make_runner

    cred = default_credential()  # ANTHROPIC_API_KEY del entorno, si hay
    if cred is None:
        if not env_path:
            sys.exit("Sin credencial: exporta ANTHROPIC_API_KEY o pasa --env <ruta a .env>.")
        env: dict[str, str] = {}
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    env[k.strip()] = v.strip().strip('"').strip("'")
        from urllib.parse import urlsplit

        u = urlsplit(env.get("DATABASE_URL", ""))
        if u.hostname not in ("localhost", "127.0.0.1") or u.port != 5434:
            sys.exit("--env: DATABASE_URL no es la base local (localhost:5434); abortando.")
        os.environ["AIUDA_ENCRYPTION_KEYS"] = env["AIUDA_ENCRYPTION_KEYS"]

        from sqlalchemy import create_engine, text

        from aiuda_core.security import crypto

        eng = create_engine(
            env["DATABASE_URL"],
            connect_args={"options": "-c default_transaction_read_only=on"},
        )
        with eng.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT ic.secret_ciphertext, ic.key_version, ic.public_config "
                    "FROM integration_credentials ic JOIN tenants t ON t.id = ic.tenant_id "
                    "WHERE ic.provider = 'ia' AND ic.status != 'disabled' "
                    "ORDER BY (t.name ILIKE '%hanova%') DESC LIMIT 1"
                )
            ).fetchone()
        eng.dispose()
        if row is None:
            sys.exit("--env: no hay credencial 'ia' en esa base.")
        secret = json.loads(crypto.decrypt(bytes(row[0]), row[1]))
        public = row[2] if isinstance(row[2], dict) else json.loads(row[2] or "{}")
        data = {**public, **secret}
        cred = ProviderCredential(
            name=data.get("name") or "claude",
            mode=data.get("mode") or "api_key",
            secret=data["secret"],
        )
    veredicto = test_credential(cred)
    if not veredicto.get("ok"):
        sys.exit(f"La credencial no pasó el ping: {veredicto.get('code')} — {veredicto.get('error')}")
    runner = make_runner(cred)
    print(
        f"credencial: modo={cred.mode} ping={veredicto['latency_ms']}ms "
        f"modelo_redaccion={runner.model_for('redaccion')} modelo_triage={runner.model_for('triage')}"
    )
    return runner


# --------------------------------------------------------------------------- #
# Orquestación                                                                 #
# --------------------------------------------------------------------------- #


def main() -> None:
    parser = argparse.ArgumentParser(description="Evals de IA de aiuda (aparte del gate)")
    parser.add_argument("--real", action="store_true", help="mide al modelo real (default: fake)")
    parser.add_argument("--env", default=None, help="ruta a un .env con DATABASE_URL local para la credencial 'ia'")
    parser.add_argument("--solo", choices=["redaccion", "chat", "clasificacion"], default=None)
    parser.add_argument("--umbral", type=float, default=UMBRAL)
    args = parser.parse_args()

    from evals import casos

    runner = _runner_real(args.env) if args.real else FakeEvalRunner()
    modo = "REAL" if args.real else "FAKE (arnés; no mide al modelo)"
    print(f"evals de IA — modo {modo} — {date.today().isoformat()}")
    print("-" * 76)

    areas = {
        "redaccion": casos.correr_redaccion,
        "chat": casos.correr_chat,
        "clasificacion": casos.correr_clasificacion,
    }
    if args.solo:
        areas = {args.solo: areas[args.solo]}

    resultados = []
    for nombre, correr in areas.items():
        resultados.extend(correr(runner))

    ancho = max(len(f"{r.area}/{r.caso}") for r in resultados)
    por_area: dict[str, list] = {}
    for r in resultados:
        por_area.setdefault(r.area, []).append(r)
        marca = "PASA " if r.paso else "FALLA"
        print(f"{marca}  {f'{r.area}/{r.caso}':<{ancho}}", end="")
        if r.fallos:
            print(f"  -> {'; '.join(r.fallos)}")
            if r.extracto:
                print(f"{'':<{ancho + 11}}«{r.extracto}»")
        else:
            print()

    print("-" * 76)
    total = len(resultados)
    pasan = sum(1 for r in resultados if r.paso)
    for area, rs in por_area.items():
        p = sum(1 for r in rs if r.paso)
        print(f"{area:>14}: {p}/{len(rs)}")
    score = pasan / total if total else 0.0
    veredicto = "VERDE" if score >= args.umbral else "ROJO"
    print(f"{'score':>14}: {pasan}/{total} = {score:.0%}  (umbral {args.umbral:.0%}) -> {veredicto}")
    sys.exit(0 if score >= args.umbral else 1)


if __name__ == "__main__":
    main()
