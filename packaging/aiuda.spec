# Binario único de aiuda: el server + la consola, sin Python instalado.
#
#   cd web && npm run export && cd ..
#   rm -rf server/aiuda_server/static && cp -R web/out server/aiuda_server/static
#   uv run pyinstaller packaging/aiuda.spec --noconfirm
#
# Sale en dist/aiuda (un ejecutable). Es también el sidecar de la app de
# escritorio. Playwright/Chromium NO viaja aquí (pesa cientos de MB y es
# opcional): `aiuda doctor` dice cómo instalarlo si quieres el CUA.

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).parent

datos = [(str(ROOT / "server" / "aiuda_server" / "static"), "aiuda_server/static")]
datos += collect_data_files("aiuda_core")

ocultos = [
    # uvicorn/fastapi cargan por nombre, PyInstaller no los ve en el import graph.
    *collect_submodules("uvicorn"),
    *collect_submodules("aiuda_core"),
    *collect_submodules("aiuda_server"),
    "anthropic",
    "httpx",
    # Bonjour: zeroconf carga sus piezas por nombre y sin esto el paquete sale
    # sin ellas, o sea que la app anunciaría en la red... nada.
    *collect_submodules("zeroconf"),
    # El certificado de la red local: cryptography también carga por nombre.
    "cryptography.hazmat.primitives.asymmetric.ec",
    "cryptography.hazmat.backends.openssl",
    "cryptography.x509",
    "sqlalchemy.dialects.sqlite",
    "email.mime.text",
    "email.mime.multipart",
]

a = Analysis(
    [str(ROOT / "packaging" / "entry.py")],
    pathex=[str(ROOT / "core"), str(ROOT / "server")],
    binaries=[],
    datas=datos,
    hiddenimports=ocultos,
    excludes=["tkinter", "matplotlib", "pytest", "playwright"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="aiuda",
    console=True,
    strip=False,
    upx=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
