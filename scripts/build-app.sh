#!/usr/bin/env bash
# Construye la app de escritorio de aiuda de punta a punta.
#
#   scripts/build-app.sh          # todo: consola + binario + app
#   scripts/build-app.sh --solo-binario
#
# Sale en desktop/src-tauri/target/release/bundle/ (.dmg en macOS, .msi/.exe en
# Windows, .deb/.AppImage en Linux). Requisitos: node, uv y Rust (rustup).
set -euo pipefail
cd "$(dirname "$0")/.."

SOLO_BINARIO=false
[ "${1:-}" = "--solo-binario" ] && SOLO_BINARIO=true

echo "==> 1/4 Consola (export estático)"
(cd web && npm ci --silent && npm run export >/dev/null)

echo "==> 2/4 Consola dentro del paquete del server"
rm -rf server/aiuda_server/static
cp -R web/out server/aiuda_server/static

echo "==> 3/4 Binario del server (sin Python en la máquina del usuario)"
uv sync --extra cua --quiet   # el extra no viaja en el binario (excluido en el spec), pero deja el entorno igual que el de desarrollo
uv run pyinstaller packaging/aiuda.spec --noconfirm --distpath dist/bin --workpath build/pyi --log-level WARN

if [ "$SOLO_BINARIO" = true ]; then
  echo "Listo: dist/bin/aiuda"
  exit 0
fi

echo "==> 4/4 App de escritorio"
# rustup instala en ~/.cargo/bin, que no siempre está en el PATH de un script.
export PATH="$HOME/.cargo/bin:$PATH"
command -v rustc >/dev/null || {
  echo "Falta Rust. Instálalo con: curl https://sh.rustup.rs -sSf | sh" >&2
  exit 1
}
TRIPLE=$(rustc -Vv | awk '/host:/ {print $2}')
mkdir -p desktop/src-tauri/binaries
BIN="dist/bin/aiuda"
[ -f "$BIN.exe" ] && BIN="$BIN.exe"
cp "$BIN" "desktop/src-tauri/binaries/aiuda-server-$TRIPLE"
chmod +x "desktop/src-tauri/binaries/aiuda-server-$TRIPLE"
(cd desktop && npm ci --silent && npx tauri build)

echo
echo "Listo. Instaladores en desktop/src-tauri/target/release/bundle/"
