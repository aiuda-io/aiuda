"""Lógica pura del daemon de entrada de wacli: qué mensajes son nuevos y en qué contrato."""

from aiuda_core.connectors.wacli_inbound import collect_inbound, select_new

JID = "5215587654321@s.whatsapp.net"


def _msg(text, ts, from_me=False, mid=None):
    m = {"Text": text, "Timestamp": ts, "FromMe": from_me}
    if mid is not None:
        m["Id"] = mid
    return m


def test_primera_vez_siembra_sin_reenviar_historia():
    # Conversación no vista: no se reenvía el historial (sembraría al agente con lo viejo).
    posts, state = select_new(
        [_msg("hola", 100, mid="a"), _msg("¿me ayudas?", 200, mid="b")], JID, None
    )
    assert posts == []
    assert state["last_ts"] == 200
    assert set(state["ids"]) == {"a", "b"}


def test_reenvia_solo_lo_posterior_al_sembrado():
    state = {"last_ts": 200, "ids": ["a", "b"]}
    posts, new_state = select_new(
        [_msg("hola", 100, mid="a"), _msg("nuevo", 300, mid="c")], JID, state
    )
    assert [p["message"] for p in posts] == ["nuevo"]
    assert posts[0]["phone"] == "5215587654321"  # dígitos del JID
    assert posts[0]["id"] == "c"
    assert new_state["last_ts"] == 300


def test_ignora_los_propios_y_los_vacios():
    posts, _ = select_new(
        [
            _msg("respuesta mía", 300, from_me=True, mid="x"),
            _msg("", 310, mid="y"),
            _msg("real", 320, mid="z"),
        ],
        JID,
        {"last_ts": 200, "ids": []},
    )
    assert [p["message"] for p in posts] == ["real"]


def test_no_reenvia_dos_veces_el_mismo_id():
    state = {"last_ts": 200, "ids": ["a", "b"]}
    _, state = select_new([_msg("nuevo", 300, mid="c")], JID, state)
    # Segundo sondeo con el mismo mensaje: ya está en ids → no se reenvía.
    posts, _ = select_new([_msg("nuevo", 300, mid="c")], JID, state)
    assert posts == []


def test_id_sintetico_estable_si_wacli_no_lo_trae():
    # Sin id nativo, el id se deriva de (jid, ts, texto): determinístico entre sondeos.
    p1, _ = select_new([_msg("hola", 300)], JID, {"last_ts": 200, "ids": []})
    p2, _ = select_new([_msg("hola", 300)], JID, {"last_ts": 200, "ids": []})
    assert p1[0]["id"] == p2[0]["id"]
    assert p1[0]["id"].startswith("wacli-")


def test_timestamp_iso_se_ordena():
    state = {"last_ts": None, "ids": ["seed"]}  # ya sembrado (no primera vez)
    posts, _ = select_new(
        [{"Text": "hola", "Timestamp": "2026-07-02T15:00:00Z", "FromMe": False, "Id": "n"}],
        JID,
        state,
    )
    assert [p["message"] for p in posts] == ["hola"]


def test_collect_inbound_ignora_grupos():
    chats = [
        {"jid": JID, "kind": "dm"},
        {"jid": "12036300@g.us", "kind": "group"},
    ]
    seen = {"last_ts": 100, "ids": []}

    def list_messages(jid):
        assert jid == JID  # el grupo no se consulta
        return [_msg("nuevo", 200, mid="m1")]

    posts, state = collect_inbound(chats, list_messages, {JID: seen})
    assert [p["message"] for p in posts] == ["nuevo"]
    assert JID in state
