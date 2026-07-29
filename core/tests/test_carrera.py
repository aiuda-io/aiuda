"""Plan de carrera: el nivel se deriva de acciones reales y sube DE VERDAD."""

from aiuda_core.carrera import NIVELES, nivel_por_acciones


def test_niveles_suben_por_umbral():
    assert nivel_por_acciones(0)["nivel"] == "Aprendiz"
    assert nivel_por_acciones(9)["nivel"] == "Aprendiz"
    assert nivel_por_acciones(10)["nivel"] == "Junior"
    assert nivel_por_acciones(49)["nivel"] == "Junior"
    assert nivel_por_acciones(50)["nivel"] == "Senior"
    assert nivel_por_acciones(199)["nivel"] == "Senior"
    assert nivel_por_acciones(200)["nivel"] == "Experto"
    assert nivel_por_acciones(5000)["nivel"] == "Experto"


def test_progreso_avanza_hacia_el_siguiente():
    n = nivel_por_acciones(5)  # a medio camino de Junior (0 → 10)
    assert n["siguiente"] == 10
    assert n["progreso"] == 0.5
    n = nivel_por_acciones(30)  # Junior (10) rumbo a Senior (50): 20/40
    assert n["siguiente"] == 50
    assert n["progreso"] == 0.5


def test_nivel_maximo_sin_siguiente():
    n = nivel_por_acciones(200)
    assert n["siguiente"] is None
    assert n["progreso"] == 1.0


def test_basura_no_rompe():
    assert nivel_por_acciones(-3)["nivel"] == "Aprendiz"


def test_la_escala_es_monotona():
    """La señal es real: más trabajo nunca baja el nivel."""
    umbrales = [u for u, _ in NIVELES]
    assert umbrales == sorted(umbrales)
    orden = {"Aprendiz": 0, "Junior": 1, "Senior": 2, "Experto": 3}
    previo = 0
    for acciones in range(0, 260, 7):
        actual = orden[nivel_por_acciones(acciones)["nivel"]]
        assert actual >= previo
        previo = actual
