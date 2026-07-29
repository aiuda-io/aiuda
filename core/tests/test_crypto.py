"""La clave de cifrado se resuelve de la variable de entorno O del .env (settings).

En local el .env lo carga pydantic en `settings`, NO en os.environ; cripto debe
encontrarlo igual para que guardar un token no truene con 500.
"""

from cryptography.fernet import Fernet

from aiuda_core.config import settings
from aiuda_core.security import crypto


def test_clave_cae_a_settings_cuando_no_hay_env_var(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.delenv("AIUDA_ENCRYPTION_KEYS", raising=False)
    monkeypatch.setattr(settings, "aiuda_encryption_keys", key)
    crypto.reset_cache()
    ct, ver = crypto.encrypt("token-secreto")
    assert crypto.decrypt(ct, ver) == "token-secreto"
    crypto.reset_cache()


def test_env_var_gana_sobre_settings(monkeypatch):
    env_key = Fernet.generate_key().decode()
    monkeypatch.setenv("AIUDA_ENCRYPTION_KEYS", env_key)
    # settings tiene OTRA clave; no debe usarse cuando hay variable de entorno.
    monkeypatch.setattr(settings, "aiuda_encryption_keys", Fernet.generate_key().decode())
    crypto.reset_cache()
    ct, ver = crypto.encrypt("x")
    assert crypto.decrypt(ct, ver) == "x"  # round-trip con la clave del entorno
    crypto.reset_cache()


def test_sin_clave_el_keystore_genera_y_persiste(monkeypatch, tmp_path):
    """Sin env ni settings, el keystore local genera una llave en el primer uso
    y la reusa después (aquí forzado al camino de archivo, sin keychain)."""
    from aiuda_core.security import keystore

    monkeypatch.delenv("AIUDA_ENCRYPTION_KEYS", raising=False)
    monkeypatch.setattr(settings, "aiuda_encryption_keys", "")
    monkeypatch.setattr(keystore, "_keychain_legacy", lambda: None)
    monkeypatch.setattr(keystore, "key_file", lambda: tmp_path / "key")
    crypto.reset_cache()
    ct, ver = crypto.encrypt("x")
    assert crypto.decrypt(ct, ver) == "x"
    key_path = tmp_path / "key"
    assert key_path.exists()
    assert (key_path.stat().st_mode & 0o777) == 0o600
    # Segundo arranque (cache limpio): la MISMA llave descifra lo ya cifrado.
    crypto.reset_cache()
    assert crypto.decrypt(ct, ver) == "x"
    crypto.reset_cache()


def test_keystore_migra_la_llave_del_llavero_al_archivo(monkeypatch, tmp_path):
    """Una instalación previa dejó la llave en el Keychain: se migra al archivo
    (no se genera una nueva, que dejaría ilegibles las credenciales viejas)."""
    from cryptography.fernet import Fernet

    from aiuda_core.security import keystore

    vieja = Fernet.generate_key().decode()
    monkeypatch.delenv("AIUDA_ENCRYPTION_KEYS", raising=False)
    monkeypatch.setattr(settings, "aiuda_encryption_keys", "")
    monkeypatch.setattr(keystore, "_keychain_legacy", lambda: vieja)
    monkeypatch.setattr(keystore, "key_file", lambda: tmp_path / "key")
    crypto.reset_cache()

    assert keystore.get_or_create_keys() == vieja
    assert (tmp_path / "key").read_text().strip() == vieja
    # Ya migrada, el llavero deja de consultarse: la fuente es el archivo.
    monkeypatch.setattr(keystore, "_keychain_legacy", lambda: "otra-cosa")
    assert keystore.get_or_create_keys() == vieja
    crypto.reset_cache()


def test_keystore_nunca_reemplaza_una_llave_existente(monkeypatch, tmp_path):
    from aiuda_core.security import keystore

    monkeypatch.setattr(keystore, "_keychain_legacy", lambda: None)
    monkeypatch.setattr(keystore, "key_file", lambda: tmp_path / "key")
    primera = keystore.get_or_create_keys()
    assert keystore.get_or_create_keys() == primera
