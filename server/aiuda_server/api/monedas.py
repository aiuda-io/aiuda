"""Pesos y dólares nunca se suman.

Un solo criterio para toda cifra de cartera que sale del API (`/v1/cartera`, la
lista y la ficha de clientes, el SAT): los totales van POR MONEDA, y donde hace
falta una sola cifra se dice la de la moneda principal, junto a su código.
"""

from collections.abc import Iterable

MONEDA_BASE = "MXN"


def moneda_de(codigo: str | None) -> str:
    """El código de moneda en limpio. Sin código, pesos."""
    return (codigo or MONEDA_BASE).strip().upper() or MONEDA_BASE


def moneda_principal(conteo: dict[str, int]) -> str:
    """La moneda en la que se dicen las cifras sueltas. Pesos si hay al menos un
    registro en pesos (o ninguno); si solo hay otras monedas, la que más registros
    tenga (empate: orden alfabético)."""
    if not conteo or conteo.get(MONEDA_BASE):
        return MONEDA_BASE
    return max(sorted(conteo), key=lambda m: conteo[m])


def saldos_por_moneda(montos: Iterable[tuple[str | None, float]]) -> tuple[str, list[dict]]:
    """Agrupa (moneda, monto) sin mezclar monedas.

    Devuelve `(principal, [{moneda, open_total, open_count}, ...])`, con la
    principal primero y las demás en orden alfabético. Sin registros la lista
    viene vacía y la principal es pesos."""
    totales: dict[str, float] = {}
    cuenta: dict[str, int] = {}
    for codigo, monto in montos:
        m = moneda_de(codigo)
        totales[m] = totales.get(m, 0.0) + float(monto or 0)
        cuenta[m] = cuenta.get(m, 0) + 1
    principal = moneda_principal(cuenta)
    orden = ([principal] if principal in cuenta else []) + sorted(set(cuenta) - {principal})
    return principal, [
        {"moneda": m, "open_total": totales[m], "open_count": cuenta[m]} for m in orden
    ]


def total_principal(principal: str, por_moneda: list[dict]) -> float:
    """El total de la moneda principal (0 si no hay nada en ella)."""
    return next((p["open_total"] for p in por_moneda if p["moneda"] == principal), 0.0)
