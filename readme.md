# OpenVPN3 GUI Client

A modern graphical client for OpenVPN3 on Ubuntu/Debian, with full **SAML/SSO web authentication** support, saved connection profiles, and a clean dark interface.

**Developed by Agniswar Chakraborty**

---

## Screenshots

> Dark themed interface with profile sidebar, live session stats, SAML banner, and colour-coded log.

---

## Features

- **Saved profiles** — add any number of `.ovpn` configs, name them, rename/remove via right-click. No more browsing for the file every time.
- **Double-click to connect** — select a profile and double-click to connect instantly.
- **SAML / SSO support** — automatically detects web-authentication flows, opens your browser, and polls for connection status.
- **Live session stats** — connection duration, tunnel IP, protocol, and session status updated in real time.
- **Colour-coded log** — errors in red, warnings in orange, SAML events in purple, connection events in green.
- **Clean disconnect** — uses `openvpn3 session-manage` with a `sessions-list` fallback for stale sessions.
- **Dock icon** — proper hicolor icon at 16 → 256 px, wired to the GNOME dock via `StartupWMClass`.

---

## Requirements

| Dependency | Install |
|---|---|
| Python 3.10+ | pre-installed on Ubuntu 22.04+ |
| python3-pyqt5 | `sudo apt install python3-pyqt5` |
| openvpn3 | `sudo apt install openvpn3` |

---

## Installation

### Option A — Install the Debian package (recommended)

Build the package first (see [Building the .deb](#building-the-deb)), then:

```bash
sudo dpkg -i openvpn3-gui_1.0.0_all.deb
sudo apt-get install -f          # installs any missing dependencies
```

Launch from the application menu or run:

```bash
openvpn3-gui
```

Uninstall:

```bash
sudo dpkg -r openvpn3-gui
```

### Option B — Run directly without installing

```bash
pip install PyQt5
python3 main.py
```

---

## Building the .deb

You only need two files in the same folder:

```
your-folder/
├── main.py   
└── build_deb.sh ← the build script
```

Run:

```bash
chmod +x build_deb.sh
./build_deb.sh
```

The script will:
1. Install `cairosvg` (for rendering PNG icons at all sizes)
2. Create the full `debian/` package tree from scratch
3. Write all metadata, icons, launcher, and `.desktop` files
4. Copy your `openvpn3_client.py` as-is into the package
5. Build `openvpn3-gui_1.0.0_all.deb` in the current directory

> **Tip:** Whenever you update `openvpn3_client.py`, just run `./build_deb.sh` again. It always picks up the latest version of your script.

---

## How to Use

### Adding a profile

1. Click the **+** button in the top-left profile panel.
2. Browse to your `.ovpn` configuration file.
3. Give it a name (defaults to the filename stem).
4. The profile is saved and persists across sessions at `~/.config/openvpn3-gui/profiles.json`.

### Connecting

- **Single-click** a profile to select it.
- **Double-click** to select and connect immediately.
- Or select a profile and click **⏵ Connect**.

### SAML / SSO authentication

If your VPN profile requires web-based login (Okta, Azure AD, Google, etc.):

1. Click Connect — the status changes to **AUTHENTICATING** (purple).
2. A banner appears and your browser opens automatically.
3. Complete the login in your browser.
4. The app polls every 3 seconds and switches to **CONNECTED** (green) once the tunnel is up.

> If the browser doesn't open automatically, click **Open Browser** in the purple banner.

### Disconnecting

Click **⏹ Disconnect**. The app runs:

```
openvpn3 session-manage --path <session_path> --disconnect
```

If that fails, it falls back to scanning `openvpn3 sessions-list` and disconnects all sessions matching your config file.

### Profile management

Right-click any profile in the sidebar for options:

- **✏ Rename** — change the display name
- **🗑 Remove** — delete from the list (does not delete the `.ovpn` file)

---

## File locations (after .deb install)

| Path                                               | Contents |
|----------------------------------------------------|---|
| `/usr/share/openvpn3-gui/main.py`                  | Main application |
| `/usr/bin/openvpn3-gui`                            | Shell launcher |
| `/usr/share/applications/openvpn3-gui.desktop`     | Desktop entry |
| `/usr/share/icons/hicolor/*/apps/openvpn3-gui.png` | Icons (16–256 px) |
| `~/.config/openvpn3-gui/profiles.json`             | Your saved profiles |

---

## Troubleshooting

**Dock icon not showing after install**

Run the icon cache refresh manually:

```bash
gtk-update-icon-cache -f -t /usr/share/icons/hicolor
sudo update-desktop-database /usr/share/applications
```

Then log out and log back in.

**openvpn3 not found**

```bash
sudo apt install openvpn3
```

On older Ubuntu you may need to add the OpenVPN repository first:

```bash
sudo apt install apt-transport-https curl
curl -fsSL https://swupdate.openvpn.net/repos/openvpn-repo-pkg-key.pub | sudo gpg --dearmor -o /etc/apt/trusted.gpg.d/openvpn.gpg
echo "deb [arch=amd64] https://packages.openvpn.net/openvpn3/debian $(lsb_release -cs) main" | sudo tee /etc/apt/sources.list.d/openvpn3.list
sudo apt update && sudo apt install openvpn3
```

**PyQt5 not found**

```bash
sudo apt install python3-pyqt5
```

**Profile disappears after reinstall**

Profiles are stored in `~/.config/openvpn3-gui/profiles.json` in your home directory — they are not touched by install or uninstall.

**Session stuck at AUTHENTICATING**

The SAML login may have timed out. Click **⏹ Disconnect**, wait a moment, then connect again.

---

## Notes

- `sudo` is **not** required. `openvpn3` manages tunnels through its own D-Bus daemon.
- Profiles only store the **path** to your `.ovpn` file — not credentials.
- The app works without a `.deb` install: `python3 main.py` is sufficient for testing.

---

## License

MIT © 2026 Agniswar Chakraborty