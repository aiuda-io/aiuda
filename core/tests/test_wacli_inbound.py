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

    posts, state = collect_inbound(chats, list_messages, {JID: seen}, {"5587654321"})
    assert [p["message"] for p in posts] == ["nuevo"]
    assert JID in state


def test_collect_inbound_solo_lee_los_chats_de_clientes_y_del_dueno():
    """Visto con un número personal de verdad: 53 chats directos y ninguno de un
    cliente. Cada uno se leía (un proceso de wacli por chat, cada 20 s) y lo que
    escribían la familia y los amigos entraba como si fueran clientes."""
    cliente = "5215587654321@s.whatsapp.net"  # guardado como 52 + 10, sin el 1
    dueno = "5215500000000@s.whatsapp.net"
    amigo = "5215511112222@s.whatsapp.net"
    oculto = "190000000000001@lid"  # sin teléfono que cruzar: desconocido
    chats = [{"jid": j, "kind": "dm"} for j in (cliente, dueno, amigo, oculto)]
    leidos: list[str] = []

    def list_messages(jid):
        leidos.append(jid)
        return [_msg("alto", 200, mid=f"m-{jid}")]

    visto = {"last_ts": 100, "ids": []}
    posts, state = collect_inbound(
        chats, list_messages, {j: dict(visto) for j in (cliente, dueno, amigo, oculto)},
        {"5587654321", "5500000000"},
    )
    assert leidos == [cliente, dueno]
    assert [p["phone"] for p in posts] == ["5215587654321", "5215500000000"]
    # Lo que ya no se atiende sale del marcador: si ese número se vuelve cliente,
    # su chat se siembra de cero en vez de reenviar lo que escribió antes.
    assert set(state) == {cliente, dueno}


def test_collect_inbound_conserva_el_marcador_del_cliente_que_no_salio_en_la_lista():
    otro = "5215533334444@s.whatsapp.net"
    _, state = collect_inbound(
        [{"jid": JID, "kind": "dm"}], lambda _jid: [],
        {JID: {"last_ts": 100, "ids": []}, otro: {"last_ts": 50, "ids": ["z"]}},
        {"5587654321", "5533334444"},
    )
    assert state[otro] == {"last_ts": 50, "ids": ["z"]}


# Formas reales de `messages list --json` (wacli 0.18.2): lo que no es texto trae
# `Text` vacío o un marcador, y `DisplayText` con la descripción en inglés de wacli.
def _real(mid, ts=300, **campos):
    base = {"MsgID": mid, "Timestamp": ts, "FromMe": False, "Text": "", "DisplayText": "",
            "MediaType": "", "MediaCaption": "", "Filename": "", "ReactionToID": ""}
    return {**base, **campos}


def _entran(mensajes):
    posts, _ = select_new(mensajes, JID, {"last_ts": 200, "ids": []})
    return [p["message"] for p in posts]


def test_una_reaccion_o_un_sticker_no_entran_como_mensaje():
    assert _entran([
        _real("r", DisplayText="Reacted x to hola", ReactionToID="abc"),
        _real("s", DisplayText="Sent sticker", MediaType="sticker"),
        _real("m", DisplayText="(message)"),
    ]) == []


def test_un_adjunto_sin_nota_entra_con_su_etiqueta_en_espanol():
    assert _entran([
        _real("i", DisplayText="Sent image", MediaType="image"),
        _real("a", Text="[Audio]", DisplayText="Sent audio", MediaType="audio"),
        _real("d", DisplayText="Sent document", MediaType="document", Filename="pago.pdf"),
    ]) == ["[imagen]", "[audio]", "[documento] pago.pdf"]


def test_un_adjunto_con_nota_entra_con_la_nota():
    assert _entran([
        _real("i", Text="mi comprobante", DisplayText="Sent image", MediaType="image",
              MediaCaption="mi comprobante"),
    ]) == ["mi comprobante"]
