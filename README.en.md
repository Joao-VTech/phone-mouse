# Phone Mouse

[🇧🇷 Português](README.md) · **🇺🇸 English**

![MIT License](https://img.shields.io/badge/license-MIT-blue) ![Windows](https://img.shields.io/badge/PC-Windows-0078D6) ![Android and iPhone](https://img.shields.io/badge/phone-Android%20%7C%20iPhone-3DDC84)

Turn your phone into a **mouse and keyboard for your Windows PC** using just the browser — **no app to
install on the phone**. Touchpad with gestures, gyroscope pointer, full keyboard (accents, emoji),
fullscreen, game-friendly admin mode and PIN-protected access.

> The interface is currently in **Brazilian Portuguese**. Contributions with translations are welcome!

## Quick install (Windows)

**Win + R** → type `powershell` → **Enter**, then paste/type:

```powershell
irm https://raw.githubusercontent.com/Joao-VTech/phone-mouse/main/instalar-web.ps1 | iex
```

Answer the questions with **S** (yes) or **N** (no) — it works **with the keyboard only**, no mouse needed.
At the end a **QR code appears on screen**: point your phone camera at it and you're done — the QR code
already carries the access PIN.

<details>
<summary>Other ways to install</summary>

- **ZIP:** download the repository (**Code → Download ZIP**), extract it and double-click **`instalar.bat`**.
- **Manual:** `py -m pip install -r requirements.txt` and `py server.py` (or `py server.py --console` to see the log).

The installer: installs Python if missing (winget or python.org) and the dependencies; optionally `adb`
(USB cable, Android only); creates the **Phone Mouse** shortcut; optionally enables **admin mode**
(one Windows prompt: **Alt + S** on a Portuguese system, **Alt + Y** on English) and start with Windows.
</details>

## Everyday use

1. Open the **Phone Mouse** shortcut (or keep *Start with Windows* on).
2. On the phone, tap the **"Phone Mouse pronto - PC-NAME"** notification (or scan the QR code on the PC).
3. The first time: accept the certificate warning (it is self-signed), tap **Iniciar** (Start) and enter the **PIN** if asked.

## Modes

| Mode | How to use |
|---|---|
| 👆 **Touchpad** (default) | slide your finger on the screen, like a laptop touchpad |
| 🔦 **Pointer** | rotate your wrist and aim, like a laser pointer (gyroscope) |

### Touchpad gestures
- 1-finger drag: move the cursor
- tap: left click · tap + tap-and-drag: select/drag
- 2-finger tap: right click · 2-finger drag: scroll
- 3-finger tap: middle button
- swipe from the edge to the middle: open/close the keyboard
  (portrait: side edges · landscape: top/bottom edges)
- ⛶ fullscreen and ⟳ to rotate the screen (portrait → landscape → other side)

### Keyboard
Types on the PC with accents, autocorrect and emoji. Bar with Esc, Tab, Ctrl, Alt, Shift, Win, arrows
and Del (tap the modifier, then the key, e.g. Ctrl → `c`). When the page itself is rotated, a built-in
keyboard that rotates with it is used.

## 🔒 Access PIN
Each PC has a **6-digit PIN**. Without it nobody can control the PC, even on the same network.
- **Scanning the QR code on the PC screen pairs the phone** (the PIN is inside the QR); the phone remembers it.
- Or type the PIN: it is shown in the **tray icon**, on the QR code page and by `py server.py --pin`.
- **Generate new PIN** (tray menu) disconnects every phone; they will ask for the PIN again.
- After 5 wrong PINs, the device is blocked for 1 minute.

## Phone notification
On first run a page opens with QR codes to **download [ntfy](https://ntfy.sh)** (Google Play and App
Store) and, next to them, to **subscribe to your topic** (Android: QR code; iPhone: copy the topic →
in the app **+** → topic → **Subscribe**). To open it again: tray icon → *Configurar notificação no celular*.

To use the **same topic on several PCs**, copy `config.json` between them. To turn it off, set
`"notify"` to `false`. To change the displayed name, add `"pc_name": "Living room"`.

## Connection
- **Wi-Fi:** phone and PC on the same network.
- **USB cable (Android):** enable *USB debugging*, plug it in and tap **📶 Wi-Fi ⇄** on the page.
- **Network change (cable ↔ Wi-Fi):** the server notices it, resends the notification and, if no phone
  is connected, shows a QR code with the new address on screen.

## Troubleshooting

**The page stays blank/loading on the phone** — almost always the firewall, or the phone is on another
network. On the PC: **Win + R** → `powershell` → **Enter** and type:
```powershell
irm https://raw.githubusercontent.com/Joao-VTech/phone-mouse/main/diagnostico.ps1 | iex
```
It checks the server, network and firewall, offers to fix the firewall and shows the right address.

**Commands:** `py server.py --print-url` (QR code + PIN) · `--pin` · `--new-pin` · `--autostart on|off` ·
`--setup-notification` · `--install-admin` · `--console`.

## Notes
- **Windows limits:** the **sign-in screen**, **Ctrl+Alt+Del** and **UAC prompts** do not accept virtual
  mouse/keyboard input (Windows' own protection). Use the physical keyboard or Windows Hello there.
- **Admin mode:** needed for windows running as administrator and many games. Games with kernel-level
  anti-cheat deliberately block virtual mice.
- **iPhone:** the browser can't lock orientation or go truly fullscreen; the page rotates itself (⟳).
  To open without browser bars: Safari → Share → Add to Home Screen. USB cable doesn't work on iPhone.
- **Network:** use it on trusted networks. Traffic is encrypted (HTTPS) and protected by the PIN.
- Notifications go through the public ntfy.sh server (only the PC name and local address, never the PIN).

## License
[MIT](LICENSE) © 2026 JV Tech — use, modify and share freely, keeping the copyright notice.
