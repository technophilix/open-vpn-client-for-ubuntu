#!/bin/bash
# =============================================================================
# build_deb.sh  –  Debian package builder for openvpn3-gui
# Developed by Agniswar Chakraborty
#
# Place this file alongside openvpn3_client.py, then run:
#   chmod +x build_deb.sh
#   ./build_deb.sh
#
# Install:  sudo dpkg -i openvpn3-gui_1.0.0_all.deb
#           sudo apt-get install -f
# Remove:   sudo dpkg -r openvpn3-gui
# =============================================================================
set -e

PKGNAME="openvpn3-gui"
VERSION="1.1.0"
PKGDIR="debian/${PKGNAME}"
OUTFILE="${PKGNAME}_${VERSION}_all.deb"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PY_SRC="${SCRIPT_DIR}/main.py"

echo "╔══════════════════════════════════════════════╗"
echo "║  OpenVPN3 GUI – Debian Package Builder       ║"
echo "║  by Agniswar Chakraborty                     ║"
echo "╚══════════════════════════════════════════════╝"
echo

# ── sanity checks ─────────────────────────────────────────────────────────────
if ! command -v dpkg-deb &>/dev/null; then
    echo "ERROR: dpkg-deb not found.  sudo apt install dpkg"
    exit 1
fi
if ! command -v python3 &>/dev/null; then
    echo "ERROR: python3 not found."
    exit 1
fi
if [ ! -f "${PY_SRC}" ]; then
    echo "ERROR: openvpn3_client.py not found next to this script."
    echo "       Expected: ${PY_SRC}"
    exit 1
fi

echo "[1/6] Installing cairosvg for icon generation…"
python3 -m pip install --quiet --break-system-packages cairosvg 2>/dev/null \
    || python3 -m pip install --quiet cairosvg 2>/dev/null \
    || echo "  WARN: cairosvg unavailable — PNG icons skipped, SVG only."

# ── directory tree ────────────────────────────────────────────────────────────
echo "[2/6] Creating package structure…"
rm -rf debian
mkdir -p "${PKGDIR}/DEBIAN"
mkdir -p "${PKGDIR}/usr/bin"
mkdir -p "${PKGDIR}/usr/share/${PKGNAME}"
mkdir -p "${PKGDIR}/usr/share/applications"
mkdir -p "${PKGDIR}/usr/share/doc/${PKGNAME}"
mkdir -p "${PKGDIR}/usr/share/pixmaps"
for SZ in 16 24 32 48 64 128 256; do
    mkdir -p "${PKGDIR}/usr/share/icons/hicolor/${SZ}x${SZ}/apps"
done

# ── DEBIAN/control ────────────────────────────────────────────────────────────
cat > "${PKGDIR}/DEBIAN/control" << CONTROL
Package: ${PKGNAME}
Version: ${VERSION}
Section: net
Priority: optional
Architecture: all
Depends: python3 (>= 3.10), python3-pyqt5, openvpn3
Maintainer: Agniswar Chakraborty <agniswar@example.com>
Description: OpenVPN3 GUI Client with SAML/SSO support
 A modern PyQt5-based graphical client for OpenVPN3.
 Supports SAML/SSO web-authentication, saved connection profiles,
 session monitoring and one-click connect/disconnect.
 .
 Developed by Agniswar Chakraborty.
CONTROL

# ── DEBIAN/postinst ───────────────────────────────────────────────────────────
cat > "${PKGDIR}/DEBIAN/postinst" << 'EOF'
#!/bin/bash
set -e
chmod +x /usr/bin/openvpn3-gui
if command -v gtk-update-icon-cache &>/dev/null; then
    gtk-update-icon-cache -f -t /usr/share/icons/hicolor 2>/dev/null || true
fi
if command -v update-desktop-database &>/dev/null; then
    update-desktop-database /usr/share/applications 2>/dev/null || true
fi
echo "OpenVPN3 GUI installed. Run: openvpn3-gui"
EOF
chmod 755 "${PKGDIR}/DEBIAN/postinst"

# ── DEBIAN/prerm ──────────────────────────────────────────────────────────────
cat > "${PKGDIR}/DEBIAN/prerm" << 'EOF'
#!/bin/bash
set -e
echo "Removing OpenVPN3 GUI…"
EOF
chmod 755 "${PKGDIR}/DEBIAN/prerm"

# ── /usr/bin launcher ─────────────────────────────────────────────────────────
cat > "${PKGDIR}/usr/bin/${PKGNAME}" << 'EOF'
#!/bin/bash
exec python3 /usr/share/openvpn3-gui/openvpn3_client.py "$@"
EOF
chmod 755 "${PKGDIR}/usr/bin/${PKGNAME}"

# ── .desktop ──────────────────────────────────────────────────────────────────
cat > "${PKGDIR}/usr/share/applications/${PKGNAME}.desktop" << 'EOF'
[Desktop Entry]
Version=1.0
Type=Application
Name=OpenVPN3 GUI
GenericName=VPN Client
Comment=OpenVPN3 graphical client with SAML/SSO support
Exec=openvpn3-gui
Icon=openvpn3-gui
Terminal=false
Categories=Network;Security;
Keywords=vpn;openvpn;openvpn3;saml;sso;
StartupNotify=true
StartupWMClass=openvpn3-gui
EOF

# ── copyright ─────────────────────────────────────────────────────────────────
cat > "${PKGDIR}/usr/share/doc/${PKGNAME}/copyright" << 'EOF'
Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: openvpn3-gui
Copyright: 2026 Agniswar Chakraborty
License: MIT
EOF

# ── icon (SVG embedded, PNGs rendered via cairosvg) ───────────────────────────
echo "[3/6] Writing icons…"
python3 - << 'PYICON'
import base64, os

SVG_B64 = (
    "PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAxMjgg"
    "MTI4IiB3aWR0aD0iMTI4IiBoZWlnaHQ9IjEyOCI+CiAgPHJlY3Qgd2lkdGg9IjEyOCIgaGVpZ2h0"
    "PSIxMjgiIHJ4PSIyNCIgZmlsbD0iIzE2MWIyMiIvPgogIDxwYXRoIGQ9Ik02NCAxNiBMMTA0IDMy"
    "IEwxMDQgNzYgUTEwNCAxMDggNjQgMTIwIFEyNCAxMDggMjQgNzYgTDI0IDMyIFoiCiAgICAgICAg"
    "ZmlsbD0iIzBkMWEwZCIgc3Ryb2tlPSIjMzlkMzUzIiBzdHJva2Utd2lkdGg9IjMiLz4KICA8cGF0"
    "aCBkPSJNNjQgMjQgTDk2IDM4IEw5NiA3NSBROTYgMTAyIDY0IDExMiBRMzIgMTAyIDMyIDc1IEwz"
    "MiAzOCBaIgogICAgICAgIGZpbGw9IiMwODEyMDgiLz4KICA8bGluZSB4MT0iNDAiIHkxPSI4MiIg"
    "eDI9Ijg4IiB5Mj0iODIiIHN0cm9rZT0iIzM5ZDM1MyIgc3Ryb2tlLXdpZHRoPSIyIiBvcGFjaXR5"
    "PSIwLjQ1IiBzdHJva2UtbGluZWNhcD0icm91bmQiLz4KICA8bGluZSB4MT0iNDMiIHkxPSI5MCIg"
    "eDI9Ijg1IiB5Mj0iOTAiIHN0cm9rZT0iIzM5ZDM1MyIgc3Ryb2tlLXdpZHRoPSIyIiBvcGFjaXR5"
    "PSIwLjI4IiBzdHJva2UtbGluZWNhcD0icm91bmQiLz4KICA8bGluZSB4MT0iNDYiIHkxPSI5OCIg"
    "eDI9IjgyIiB5Mj0iOTgiIHN0cm9rZT0iIzM5ZDM1MyIgc3Ryb2tlLXdpZHRoPSIyIiBvcGFjaXR5"
    "PSIwLjEzIiBzdHJva2UtbGluZWNhcD0icm91bmQiLz4KICA8cmVjdCB4PSI0OCIgeT0iNjYiIHdp"
    "ZHRoPSIzMiIgaGVpZ2h0PSIyNiIgcng9IjYiIGZpbGw9IiMzOWQzNTMiLz4KICA8cGF0aCBkPSJN"
    "NTUgNjYgTDU1IDU2IFE2NCA0OCA3MyA1NiBMNzMgNjYiCiAgICAgICAgZmlsbD0ibm9uZSIgc3Ry"
    "b2tlPSIjMzlkMzUzIiBzdHJva2Utd2lkdGg9IjUiIHN0cm9rZS1saW5lY2FwPSJyb3VuZCIgc3Ry"
    "b2tlLWxpbmVqb2luPSJyb3VuZCIvPgogIDxjaXJjbGUgY3g9IjY0IiBjeT0iNzciIHI9IjUuNSIg"
    "ZmlsbD0iIzBkMTExNyIvPgogIDxyZWN0IHg9IjYxLjUiIHk9IjgwIiB3aWR0aD0iNSIgaGVpZ2h0"
    "PSI4IiByeD0iMS41IiBmaWxsPSIjMGQxMTE3Ii8+CiAgPGxpbmUgeDE9IjYiIHkxPSI3MiIgeDI9"
    "IjIyIiB5Mj0iNzIiIHN0cm9rZT0iIzU4YTZmZiIgc3Ryb2tlLXdpZHRoPSIyLjUiIHN0cm9rZS1s"
    "aW5lY2FwPSJyb3VuZCIvPgogIDxwb2x5bGluZSBwb2ludHM9IjE2LDY2IDIzLDcyIDE2LDc4IiBm"
    "aWxsPSJub25lIiBzdHJva2U9IiM1OGE2ZmYiIHN0cm9rZS13aWR0aD0iMi41IgogICAgICAgICAg"
    "ICBzdHJva2UtbGluZWNhcD0icm91bmQiIHN0cm9rZS1saW5lam9pbj0icm91bmQiLz4KICA8bGlu"
    "ZSB4MT0iMTA2IiB5MT0iNzIiIHgyPSIxMjIiIHkyPSI3MiIgc3Ryb2tlPSIjNThhNmZmIiBzdHJv"
    "a2Utd2lkdGg9IjIuNSIgc3Ryb2tlLWxpbmVjYXA9InJvdW5kIi8+CiAgPHBvbHlsaW5lIHBvaW50"
    "cz0iMTE2LDY2IDEyMyw3MiAxMTYsNzgiIGZpbGw9Im5vbmUiIHN0cm9rZT0iIzU4YTZmZiIgc3Ry"
    "b2tlLXdpZHRoPSIyLjUiCiAgICAgICAgICAgIHN0cm9rZS1saW5lY2FwPSJyb3VuZCIgc3Ryb2tl"
    "LWxpbmVqb2luPSJyb3VuZCIvPgogIDxjaXJjbGUgY3g9IjY0IiBjeT0iMTQiIHI9IjYiIGZpbGw9"
    "IiMzOWQzNTMiLz4KICA8Y2lyY2xlIGN4PSI2NCIgY3k9IjE0IiByPSIzIiBmaWxsPSIjMGQxMTE3"
    "Ii8+Cjwvc3ZnPgo="
)

svg_bytes = base64.b64decode(SVG_B64)
pkgdir = "debian/openvpn3-gui"

for dest in [
    f"{pkgdir}/usr/share/pixmaps/openvpn3-gui.svg",
    f"{pkgdir}/usr/share/openvpn3-gui/openvpn3-gui.svg",
]:
    with open(dest, "wb") as f:
        f.write(svg_bytes)
print("  ✓ SVG written")

try:
    import cairosvg
    hicolor = f"{pkgdir}/usr/share/icons/hicolor"
    for sz in [16, 24, 32, 48, 64, 128, 256]:
        cairosvg.svg2png(bytestring=svg_bytes,
                         write_to=f"{hicolor}/{sz}x{sz}/apps/openvpn3-gui.png",
                         output_width=sz, output_height=sz)
        print(f"  ✓ PNG {sz}x{sz}")
    cairosvg.svg2png(bytestring=svg_bytes,
                     write_to=f"{pkgdir}/usr/share/pixmaps/openvpn3-gui.png",
                     output_width=48, output_height=48)
    print("  ✓ pixmaps PNG (48x48)")
except ImportError:
    print("  ! cairosvg not available — SVG only, no PNGs")
PYICON

# ── copy the Python app (edit openvpn3_client.py freely, rebuild anytime) ────
echo "[4/6] Copying openvpn3_client.py…"
cp "${PY_SRC}" "${PKGDIR}/usr/share/${PKGNAME}/openvpn3_client.py"
chmod 644 "${PKGDIR}/usr/share/${PKGNAME}/openvpn3_client.py"

# ── permissions ───────────────────────────────────────────────────────────────
echo "[5/6] Setting permissions…"
chmod 644 "${PKGDIR}/usr/share/applications/${PKGNAME}.desktop"
chmod 644 "${PKGDIR}/usr/share/doc/${PKGNAME}/copyright"
find "${PKGDIR}/usr/share/icons" -name "*.png" -exec chmod 644 {} \; 2>/dev/null || true
find "${PKGDIR}/usr/share/pixmaps" -type f -exec chmod 644 {} \;

# ── build .deb ────────────────────────────────────────────────────────────────
echo "[6/6] Building ${OUTFILE}…"
INSTALLED_SIZE=$(du -sk "${PKGDIR}" | cut -f1)
sed -i "/^Installed-Size:/d" "${PKGDIR}/DEBIAN/control"
echo "Installed-Size: ${INSTALLED_SIZE}" >> "${PKGDIR}/DEBIAN/control"

dpkg-deb --build --root-owner-group "${PKGDIR}" "${OUTFILE}"

echo
echo "────────────────────────────────────────────────"
echo "✓  Built: ${OUTFILE}"
echo "  Install:  sudo dpkg -i ${OUTFILE}"
echo "            sudo apt-get install -f"
echo "  Run:      openvpn3-gui"
echo "  Remove:   sudo dpkg -r ${PKGNAME}"
echo "────────────────────────────────────────────────"