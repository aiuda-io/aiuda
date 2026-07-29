from aiuda_core.cartera.aging import Bucket
from aiuda_core.cartera.tone import REMINDER_BUCKETS, TONE_GUIDANCE, TONE_BY_BUCKET, tone_for


def test_todo_bucket_tiene_tono():
    for bucket in Bucket:
        assert bucket in TONE_BY_BUCKET


def test_tono_graduado():
    assert tone_for(Bucket.VENCE_PRONTO) == "amable"
    assert tone_for(Bucket.VENCIDA_RECIENTE) == "amable_directo"
    assert tone_for(Bucket.VENCIDA) == "firme"
    assert tone_for(Bucket.CRITICA) == "urgente_escalado"


def test_por_vencer_no_genera_recordatorio():
    assert Bucket.POR_VENCER not in REMINDER_BUCKETS
    assert tone_for(Bucket.POR_VENCER) == "ninguno"


def test_guidance_existe_para_tonos_accionables():
    for bucket in REMINDER_BUCKETS:
        assert tone_for(bucket) in TONE_GUIDANCE


def test_critica_no_negocia():
    assert "NO negocies" in TONE_GUIDANCE["urgente_escalado"]
