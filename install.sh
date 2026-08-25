#!/usr/bin/env bash
# Install helper dependencies on a fresh Parrot / Kali / Debian HTB VM.
# Does not install the whole pentest toolset — those come with the VM image.
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

THEN_RUN=0
if [[ "${1:-}" == "--then-run" ]]; then
  THEN_RUN=1
  shift
fi

os_id=""
os_like=""
pretty=""
if [[ -f /etc/os-release ]]; then
  # shellcheck disable=SC1091
  . /etc/os-release
  os_id="${ID:-}"
  os_like="${ID_LIKE:-}"
  pretty="${PRETTY_NAME:-$os_id}"
fi
echo "[*] Distro: ${pretty:-unknown}"

need=()
command -v python3 >/dev/null || need+=(python3)
command -v nmap >/dev/null || need+=(nmap)
command -v script >/dev/null || need+=(bsdutils)
command -v xdg-open >/dev/null || need+=(xdg-utils)
# Parrot MATE screenshot; scrot is a small fallback on both Parrot and Kali.
if ! command -v mate-screenshot >/dev/null && ! command -v gnome-screenshot >/dev/null && ! command -v scrot >/dev/null; then
  need+=(scrot)
fi

if ((${#need[@]})); then
  if ! command -v apt-get >/dev/null && ! command -v apt >/dev/null; then
    echo "[-] Need packages: ${need[*]}"
    echo "[-] No apt on this box. Install them by hand, then re-run."
    exit 1
  fi
  APT="$(command -v apt-get || command -v apt)"
  SUDO=()
  if [[ "$(id -u)" -ne 0 ]]; then
    if command -v sudo >/dev/null; then
      SUDO=(sudo)
    else
      echo "[-] Not root and no sudo. Install: ${need[*]}"
      exit 1
    fi
  fi
  echo "[*] Installing: ${need[*]}"
  export DEBIAN_FRONTEND=noninteractive
  "${SUDO[@]}" "$APT" update -qq
  "${SUDO[@]}" "$APT" install -y "${need[@]}"
else
  echo "[+] Helper packages already present."
fi

chmod +x "$DIR/htb" "$DIR/install.sh" 2>/dev/null || true

EXAMPLE="$DIR/htb_app_lib/config.example.json"
CONFIG="$DIR/htb_app_lib/config.json"
if [[ ! -f "$CONFIG" && -f "$EXAMPLE" ]]; then
  cp "$EXAMPLE" "$CONFIG"
  echo "[*] Wrote htb_app_lib/config.json from the example. Fill it in on first GUI launch."
fi

BIN_DIR="${HOME}/.local/bin"
mkdir -p "$BIN_DIR"
ln -sfn "$DIR/htb" "$BIN_DIR/htb"
echo "[+] Launcher: $BIN_DIR/htb   (add ~/.local/bin to PATH if needed)"

APP_DIR="${HOME}/.local/share/applications"
mkdir -p "$APP_DIR"
cat > "$APP_DIR/htb-helper.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=HTB Helper
Comment=HTB lab notes, logs, and recon capture
Exec=$DIR/htb --gui-only
Terminal=false
Categories=Utility;
EOF
echo "[+] Desktop entry: $APP_DIR/htb-helper.desktop"
echo "[*] Optional hotkey: Parrot/Kali Keyboard settings → Custom shortcut → command: $DIR/htb   keys: Ctrl+Alt+H"

echo
echo "Run:"
echo "  cd $DIR"
echo "  ./htb"
echo
echo "GUI only (browser, no logged shell):"
echo "  ./htb --gui-only"
echo
echo "Original numbered CLI:"
echo "  ./htb --cli"

if [[ "$THEN_RUN" -eq 1 ]]; then
  exec python3 "$DIR/htb_app_lib/htb_app.py" "$@"
fi
