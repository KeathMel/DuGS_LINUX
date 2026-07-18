#!/bin/bash
# DuGS installer — one command, working app.
#
#   curl -fsSL https://raw.githubusercontent.com/emprkeathi-cmd/DUGS/main/install.sh | bash
#
# Clones (or updates) the repo, installs dependencies, registers the desktop
# entry and icon. When it finishes, DuGS is in your application menu.

set -e

REPO="https://github.com/emprkeathi-cmd/DUGS.git"
DEST="${DUGS_DIR:-$HOME/DUGS}"

say() { printf "\033[36m::\033[0m %s\n" "$1"; }
die() { printf "\033[31m!!\033[0m %s\n" "$1" >&2; exit 1; }

# ---- prerequisites -------------------------------------------------------
command -v git >/dev/null 2>&1 || die "git is not installed."
command -v python3 >/dev/null 2>&1 || die "python3 is not installed."

# ---- get the code --------------------------------------------------------
if [ -d "$DEST/.git" ]; then
    say "updating existing install at $DEST"
    git -C "$DEST" pull --ff-only
else
    say "cloning into $DEST"
    git clone --depth 1 "$REPO" "$DEST"
fi

# the app lives in the DUGS/ subfolder of the repo
APP="$DEST"
[ -f "$APP/ui.py" ] || APP="$DEST/DUGS"
[ -f "$APP/ui.py" ] || die "could not find ui.py — unexpected repo layout."

# ---- dependencies --------------------------------------------------------
say "installing python dependencies"
PIPFLAGS=""
python3 -c "import sys; sys.exit(0)" 2>/dev/null
if pip install --help 2>/dev/null | grep -q -- "--break-system-packages"; then
    PIPFLAGS="--break-system-packages"
fi
if [ -f "$APP/requirements.txt" ]; then
    pip install $PIPFLAGS -r "$APP/requirements.txt" || \
        pip install $PIPFLAGS --user -r "$APP/requirements.txt"
else
    pip install $PIPFLAGS PyQt6 || pip install $PIPFLAGS --user PyQt6
fi

# ---- launcher ------------------------------------------------------------
say "installing launcher"
chmod +x "$APP/DuGS.sh" 2>/dev/null || true

# ---- icon ----------------------------------------------------------------
ICONDIR="$HOME/.local/share/icons/hicolor"
for sz in 16 24 32 48 64 128 256; do
    src="$APP/icons/dugs-${sz}.png"
    [ -f "$src" ] || continue
    mkdir -p "$ICONDIR/${sz}x${sz}/apps"
    cp "$src" "$ICONDIR/${sz}x${sz}/apps/dugs.png"
done
if [ -f "$APP/icons/dugs.png" ]; then
    mkdir -p "$ICONDIR/512x512/apps"
    cp "$APP/icons/dugs.png" "$ICONDIR/512x512/apps/dugs.png"
fi
command -v gtk-update-icon-cache >/dev/null 2>&1 && \
    gtk-update-icon-cache -f -t "$ICONDIR" 2>/dev/null || true

# ---- desktop entry -------------------------------------------------------
say "registering application"
APPDIR="$HOME/.local/share/applications"
mkdir -p "$APPDIR"
cat > "$APPDIR/DuGS.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=DuGS
Comment=Node-based workflow builder and Arduino code generator
Exec=$APP/DuGS.sh
Path=$APP
Icon=dugs
Terminal=false
Categories=Development;Utility;
StartupWMClass=dugs
EOF
chmod +x "$APPDIR/DuGS.desktop"
command -v update-desktop-database >/dev/null 2>&1 && \
    update-desktop-database "$APPDIR" 2>/dev/null || true

say "done."
echo
echo "  DuGS installed to: $APP"
echo "  Launch it from your application menu, or run: $APP/DuGS.sh"
echo
