from aiuda_core.connectors.evolution import parse_webhook

UPSERT_PAYLOAD = {
    "event": "messages.upsert",
    "instance": "labonita",
    "data": {
        "key": {
            "remoteJid": "5215587654321@s.whatsapp.net",
            "fromMe": False,
            "id": "BAE5F4A0C5C7",
        },
        "message": {"conversation": "te pago el viernes"},
    },
}


def test_parse_webhook_mensaje_texto():
    msg = parse_webhook(UPSERT_PAYLOAD)
    assert msg is not None
    assert msg.instance == "labonita"
    assert msg.remote_phone == "5215587654321"
    assert msg.body == "te pago el viernes"
    assert msg.from_me is False


def test_parse_webhook_ignora_otros_eventos():
    assert parse_webhook({"event": "connection.update", "data": {}}) is None


def test_parse_webhook_ignora_grupos():
    payload = {
        "event": "messages.upsert",
        "data": {
            "key": {"remoteJid": "123456@g.us", "id": "X"},
            "message": {"conversation": "hola grupo"},
        },
    }
    assert parse_webhook(payload) is None


def test_parse_webhook_extended_text():
    payload = {
        "event": "messages.upsert",
        "instance": "labonita",
        "data": {
            "key": {"remoteJid": "5215500000000@s.whatsapp.net", "id": "Y"},
            "message": {"extendedTextMessage": {"text": "ya pagué"}},
        },
    }
    msg = parse_webhook(payload)
    assert msg is not None
    assert msg.body == "ya pagué"
