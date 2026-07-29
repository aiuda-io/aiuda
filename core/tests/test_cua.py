from aiuda_core.cua.mission import Mission, build_mission_prompt
from aiuda_core.cua.runner import PLANTILLAS


def test_prompt_solo_lectura_es_explicito():
    mission = Mission(
        objetivo="Extrae los depósitos de la semana",
        sistema="Banca en línea",
        url_inicio="https://banco.example",
        datos_a_extraer={"depositos": "lista {fecha, monto}"},
    )
    prompt = build_mission_prompt(mission)
    assert "SOLO LECTURA" in prompt
    assert "depositos" in prompt
    assert "JSON" in prompt


def test_prompt_escritura_solo_con_opt_in():
    mission = Mission(
        objetivo="Captura el pago",
        sistema="ERP",
        url_inicio="x",
        datos_a_extraer={"ok": "confirmación"},
        solo_lectura=False,
    )
    assert "SOLO LECTURA" not in build_mission_prompt(mission)


def test_plantillas_mexicanas_definidas():
    assert {"sat_cfdi_recibidos", "tribunal_acuerdos", "banca_movimientos"} <= set(PLANTILLAS)
    sat = PLANTILLAS["sat_cfdi_recibidos"]
    assert sat.solo_lectura is True
    assert "sat" in sat.url_inicio
