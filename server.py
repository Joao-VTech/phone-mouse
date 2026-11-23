"""Phone Mouse - controla o mouse do PC pelo celular.

Uso normal: atalho "Phone Mouse" na área de trabalho (roda sem janela, com ícone
na bandeja do Windows e notificação no celular via ntfy).
Modo terminal: python server.py --console
"""
import asyncio
import ctypes
import datetime
import ipaddress
import json
import os
import secrets
import shutil
import socket
import ssl
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

from aiohttp import WSMsgType, web

PORT = 8443
BASE = Path(__file__).resolve().parent
CERT, KEY = BASE / "cert.pem", BASE / "key.pem"
CONFIG = BASE / "config.json"
ICON_PNG, ICON_ICO = BASE / "static" / "icon.png", BASE / "icon.ico"
STARTUP_LNK = Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs/Startup/Phone Mouse.lnk"

# sem console (pythonw): manda as mensagens para um arquivo de log
if sys.stdout is None:
    sys.stdout = sys.stderr = open(BASE / "phone-mouse.log", "a", encoding="utf-8", buffering=1)

# ---------------------------------------------------------------- config
def load_config() -> dict:
    cfg = {}
    if CONFIG.exists():
        try:
            cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
        except ValueError:
            pass
    changed = False
    if "notify" not in cfg:
        cfg["notify"] = True
        changed = True
    if not cfg.get("ntfy_topic"):
        cfg["ntfy_topic"] = "phonemouse-" + secrets.token_hex(8)   # tópico secreto, difícil de adivinhar
        changed = True
    if changed:
        CONFIG.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return cfg


def pc_name() -> str:
    """Nome mostrado no celular; pode ser trocado em config.json ("pc_name")."""
    return str(load_config().get("pc_name") or socket.gethostname())


# ---------------------------------------------------------------- mouse (Win32)
user32 = ctypes.windll.user32
MOVE, LDOWN, LUP, RDOWN, RUP, MDOWN, MUP, WHEEL = (
    0x0001, 0x0002, 0x0004, 0x0008, 0x0010, 0x0020, 0x0040, 0x0800)

_rem_x = _rem_y = 0.0  # acumula frações de pixel para movimento suave


def move(dx: float, dy: float) -> None:
    global _rem_x, _rem_y
    _rem_x += dx
    _rem_y += dy
    ix, iy = int(_rem_x), int(_rem_y)
    _rem_x -= ix
    _rem_y -= iy
    if ix or iy:
        user32.mouse_event(MOVE, ix, iy, 0, 0)


def button(btn: str, down: bool) -> None:
    flags = {"left": (LDOWN, LUP), "right": (RDOWN, RUP), "middle": (MDOWN, MUP)}[btn]
    user32.mouse_event(flags[0] if down else flags[1], 0, 0, 0, 0)


def scroll(amount: float) -> None:
    user32.mouse_event(WHEEL, 0, 0, ctypes.c_uint32(int(amount)).value, 0)


# ---------------------------------------------------------------- teclado (Win32 SendInput)
from ctypes import wintypes

ULONG_PTR = ctypes.c_size_t


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


INPUT_KEYBOARD, KEYUP, UNICODE, EXTENDED = 1, 0x0002, 0x0004, 0x0001
VK = {"backspace": 0x08, "tab": 0x09, "enter": 0x0D, "esc": 0x1B, "space": 0x20,
      "pageup": 0x21, "pagedown": 0x22, "end": 0x23, "home": 0x24,
      "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28, "delete": 0x2E,
      "shift": 0x10, "ctrl": 0x11, "alt": 0x12, "win": 0x5B}
EXTENDED_VK = {0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2E, 0x5B}
user32.VkKeyScanW.restype = ctypes.c_short


def _send(inputs: list[INPUT]) -> None:
    arr = (INPUT * len(inputs))(*inputs)
    user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))


def _vk(vk: int, up: bool) -> INPUT:
    flags = (KEYUP if up else 0) | (EXTENDED if vk in EXTENDED_VK else 0)
    return INPUT(type=INPUT_KEYBOARD, u=_INPUTUNION(ki=KEYBDINPUT(wVk=vk, dwFlags=flags)))


def type_text(s: str) -> None:
    """Digita texto qualquer (acentos, emoji...) como caracteres Unicode."""
    inputs = []
    for ch in s:
        if ch == "\n":
            inputs += [_vk(VK["enter"], False), _vk(VK["enter"], True)]
            continue
        data = ch.encode("utf-16-le")
        for i in range(0, len(data), 2):   # emojis viram 2 unidades UTF-16
            code = int.from_bytes(data[i:i + 2], "little")
            for up in (False, True):
                inputs.append(INPUT(type=INPUT_KEYBOARD, u=_INPUTUNION(
                    ki=KEYBDINPUT(wScan=code, dwFlags=UNICODE | (KEYUP if up else 0)))))
    if inputs:
        _send(inputs)


def press_key(key: str | None = None, ch: str | None = None, mods=(), n: int = 1) -> None:
    """Tecla especial (key) ou caractere (ch) com modificadores, ex.: Ctrl+C."""
    if key:
        vk = VK.get(key)
    else:
        scan = user32.VkKeyScanW(ord(ch[0]))
        if scan == -1:
            type_text(ch)
            return
        vk = scan & 0xFF
        if scan & 0x100 and "shift" not in mods:
            mods = [*mods, "shift"]
    if vk is None:
        return
    mvks = [VK[m] for m in mods if m in VK]
    for _ in range(max(1, min(int(n), 500))):
        _send([_vk(m, False) for m in mvks] + [_vk(vk, False), _vk(vk, True)]
              + [_vk(m, True) for m in reversed(mvks)])


# ---------------------------------------------------------------- rede / cert
def primary_ip() -> str | None:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return None


def local_ips() -> list[str]:
    ips = {primary_ip()} - {None}
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    return sorted(ip for ip in ips if not ip.startswith("127."))


def ensure_cert(ips: list[str]) -> None:
    if CERT.exists() and KEY.exists():
        return
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "phone-mouse")])
    san = [x509.DNSName("localhost")] + [x509.IPAddress(ipaddress.ip_address(i)) for i in ips]
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder()
            .subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=3650))
            .add_extension(x509.SubjectAlternativeName(san), critical=False)
            .sign(key, hashes.SHA256()))
    CERT.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    KEY.write_bytes(key.private_bytes(serialization.Encoding.PEM,
                                      serialization.PrivateFormat.TraditionalOpenSSL,
                                      serialization.NoEncryption()))


def already_running() -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", PORT)) == 0


# ---------------------------------------------------------------- ícone
def ensure_icons() -> None:
    if ICON_PNG.exists() and ICON_ICO.exists():
        return
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((16, 16, 496, 496), radius=110, fill=(59, 130, 246))
    d.rounded_rectangle((156, 86, 356, 426), radius=100, fill=(255, 255, 255))   # mouse
    d.line((256, 96, 256, 220), fill=(59, 130, 246), width=14)
    d.line((166, 220, 346, 220), fill=(59, 130, 246), width=14)
    ICON_PNG.parent.mkdir(exist_ok=True)
    img.save(ICON_PNG)
    img.save(ICON_ICO, sizes=[(16, 16), (32, 32), (48, 48), (256, 256)])


# ---------------------------------------------------------------- atalhos do Windows
TASK = "PhoneMouse"
SCHTASKS = str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "schtasks.exe")


def pythonw() -> str:
    p = Path(sys.executable).with_name("pythonw.exe")
    return str(p if p.exists() else sys.executable)


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except OSError:
        return False


def task_exists() -> bool:
    return subprocess.run([SCHTASKS, "/query", "/tn", TASK], capture_output=True,
                          creationflags=subprocess.CREATE_NO_WINDOW).returncode == 0


def desktop_dir() -> Path:
    return Path(subprocess.run(
        ["powershell", "-NoProfile", "-Command", "[Environment]::GetFolderPath('Desktop')"],
        capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW).stdout.strip())


def make_shortcut(lnk: Path) -> None:
    """Com o modo administrador instalado, o atalho dispara a tarefa agendada (sem UAC)."""
    if task_exists():
        tgt, args, style = SCHTASKS, f"/run /tn {TASK}", 7    # 7 = minimizado (sem piscar janela)
    else:
        tgt, args, style = pythonw(), f'"{BASE / "server.py"}"', 1
    ps = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:LNK);"
          "$s.TargetPath=$env:TGT;$s.Arguments=$env:ARGS;$s.WorkingDirectory=$env:WD;"
          "$s.IconLocation=$env:ICO;$s.WindowStyle=[int]$env:STYLE;$s.Description='Phone Mouse';$s.Save()")
    env = dict(os.environ, LNK=str(lnk), TGT=tgt, ARGS=args, WD=str(BASE), ICO=str(ICON_ICO), STYLE=str(style))
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], env=env, check=True,
                   creationflags=subprocess.CREATE_NO_WINDOW)


def install_admin() -> None:
    """Cria a tarefa agendada que roda o servidor como administrador.
    Precisa de UAC uma única vez; depois o atalho abre como admin sem perguntar."""
    if not is_admin():
        ctypes.windll.shell32.ShellExecuteW(None, "runas", pythonw(),
                                            f'"{BASE / "server.py"}" --install-admin', str(BASE), 1)
        return
    ps = ("$a=New-ScheduledTaskAction -Execute $env:TGT -Argument $env:ARGS -WorkingDirectory $env:WD;"
          "$p=New-ScheduledTaskPrincipal -UserId \"$env:USERDOMAIN\\$env:USERNAME\" -LogonType Interactive -RunLevel Highest;"
          "$s=New-ScheduledTaskSettingsSet -MultipleInstances Parallel -ExecutionTimeLimit ([TimeSpan]::Zero)"
          " -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries;"
          "Register-ScheduledTask -TaskName $env:TASK -Action $a -Principal $p -Settings $s -Force | Out-Null;"
          # encerra o servidor antigo (sem admin) que está ocupando a porta
          "Get-NetTCPConnection -LocalPort $env:PORT -State Listen -EA SilentlyContinue |"
          " ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -EA SilentlyContinue }")
    env = dict(os.environ, TGT=pythonw(), ARGS=f'"{BASE / "server.py"}"', WD=str(BASE), TASK=TASK, PORT=str(PORT))
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], env=env, check=True,
                   creationflags=subprocess.CREATE_NO_WINDOW)
    make_shortcut(desktop_dir() / "Phone Mouse.lnk")
    if STARTUP_LNK.exists():
        make_shortcut(STARTUP_LNK)
    time.sleep(1)
    subprocess.run([SCHTASKS, "/run", "/tn", TASK], creationflags=subprocess.CREATE_NO_WINDOW)
    print("[admin] modo administrador instalado e servidor reiniciado como admin")


# ---------------------------------------------------------------- cabo USB (adb)
def find_adb() -> str | None:
    cands = [shutil.which("adb"),
             BASE / "platform-tools" / "adb.exe",
             Path(os.environ.get("LOCALAPPDATA", "")) / "Android" / "Sdk" / "platform-tools" / "adb.exe"]
    winget = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
    if winget.exists():
        cands += list(winget.glob("Google.PlatformTools*/platform-tools/adb.exe"))
    return next((str(c) for c in cands if c and Path(c).exists()), None)


ADB = find_adb()
usb_state = {"adb": bool(ADB), "device": False}


async def adb_reverse_loop():
    """Mantém 'adb reverse' ativo: o celular no cabo acessa https://localhost:PORT."""
    if not ADB:
        return
    while True:
        proc = await asyncio.create_subprocess_exec(
            ADB, "reverse", f"tcp:{PORT}", f"tcp:{PORT}",
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW)
        ok = await proc.wait() == 0
        if ok != usb_state["device"]:
            print("[usb] celular conectado no cabo -> https://localhost:%d" % PORT if ok
                  else "[usb] nenhum celular no cabo")
        usb_state["device"] = ok
        await asyncio.sleep(3)


# ---------------------------------------------------------------- notificação (ntfy)
def send_notification(wait_network: bool = False) -> bool:
    """Manda uma notificação para o celular com o link atual. Retorna True se enviou."""
    cfg = load_config()
    if not cfg.get("notify"):
        return False
    ip = primary_ip()
    for _ in range(30 if wait_network else 0):   # logo após ligar o PC a rede pode demorar
        if ip:
            break
        time.sleep(2)
        ip = primary_ip()
    if not ip:
        print("[ntfy] sem rede, notificação não enviada")
        return False
    url = f"https://{ip}:{PORT}"
    actions = [f"view, Abrir (Wi-Fi), {url}"]
    if usb_state["device"]:
        actions.append(f"view, Abrir (cabo), https://localhost:{PORT}")
    req = urllib.request.Request(
        f"https://ntfy.sh/{cfg['ntfy_topic']}", method="POST",
        data="Toque para abrir o controle.".encode("utf-8"),
        headers={"Title": f"Phone Mouse pronto - {pc_name()}".encode("ascii", "replace").decode(),
                 "Click": url, "Tags": "computer_mouse",
                 "Actions": "; ".join(actions)})
    try:
        urllib.request.urlopen(req, timeout=10).close()
        print(f"[ntfy] notificação enviada ({url})")
        return True
    except OSError as e:
        print(f"[ntfy] falhou: {e}")
        return False


# ---------------------------------------------------------------- handlers
async def index(_req):
    return web.FileResponse(BASE / "static" / "index.html", headers={"Cache-Control": "no-cache"})


async def info(_req):
    return web.json_response({"port": PORT, "name": pc_name(), "primary": primary_ip(),
                              "wifi": local_ips(), **usb_state})


async def manifest(_req):
    return web.json_response({
        "name": "Phone Mouse", "short_name": "Phone Mouse", "start_url": "/",
        "display": "fullscreen", "orientation": "any",
        "background_color": "#111111", "theme_color": "#111111",
        "icons": [{"src": "/icon.png", "sizes": "512x512", "type": "image/png", "purpose": "any"}],
    }, content_type="application/manifest+json")


async def icon(_req):
    return web.FileResponse(ICON_PNG)


async def ws_handler(req):
    ws = web.WebSocketResponse(heartbeat=10)
    await ws.prepare(req)
    print(f"[+] conectado: {req.remote} | {req.headers.get('User-Agent', '?')}")
    try:
        async for msg in ws:
            if msg.type != WSMsgType.TEXT:
                continue
            m = json.loads(msg.data)
            t = m.get("t")
            if t == "m":
                move(m["x"], m["y"])
            elif t == "b":
                button(m["b"], m["d"])
            elif t == "s":
                scroll(m["y"])
            elif t == "txt":
                type_text(str(m.get("s", ""))[:2000])
            elif t == "key":
                press_key(m.get("k"), m.get("ch"), m.get("mods") or (), m.get("n", 1))
            elif t == "log":
                print(f"[celular] {str(m.get('msg', ''))[:300]}")
    finally:
        # solta botões presos se a conexão cair
        for b in ("left", "right", "middle"):
            button(b, False)
        print(f"[-] desconectado: {req.remote}")
    return ws


def build_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/", index)
    app.router.add_get("/ws", ws_handler)
    app.router.add_get("/info", info)
    app.router.add_get("/manifest.json", manifest)
    app.router.add_get("/icon.png", icon)

    async def start_bg(app):
        app["adb"] = asyncio.create_task(adb_reverse_loop())

    app.on_startup.append(start_bg)
    return app


def ssl_ctx() -> ssl.SSLContext:
    ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    ctx.load_cert_chain(CERT, KEY)
    return ctx


def print_banner(ips):
    print("\nPhone Mouse rodando.")
    print(" Wi-Fi (mesma rede):")
    for ip in ips:
        print(f"   https://{ip}:{PORT}")
    if ADB:
        print(f" Cabo USB (Android, depuração USB ligada):\n   https://localhost:{PORT}")
    else:
        print(" Cabo USB: adb não encontrado (instale com: winget install Google.PlatformTools)")
    print("Aceite o aviso de certificado (é autoassinado).\n")


# ---------------------------------------------------------------- modos de execução
def run_console():
    ips = local_ips()
    print_banner(ips)
    threading.Thread(target=send_notification, daemon=True).start()
    web.run_app(build_app(), host="0.0.0.0", port=PORT, ssl_context=ssl_ctx(), print=None)


def run_tray():
    import pystray
    from PIL import Image

    loop = asyncio.new_event_loop()
    runner = web.AppRunner(build_app())

    def serve():
        asyncio.set_event_loop(loop)
        loop.run_until_complete(runner.setup())
        loop.run_until_complete(web.TCPSite(runner, "0.0.0.0", PORT, ssl_context=ssl_ctx()).start())
        loop.run_forever()

    threading.Thread(target=serve, daemon=True).start()
    print_banner(local_ips())

    def notify_bg(wait=False):
        def job():
            time.sleep(4 if wait else 0)   # dá tempo do adb detectar o cabo
            sent = send_notification(wait_network=wait)
            if not wait:
                tray.notify("Link enviado para o celular." if sent else
                            "Não consegui enviar (notificação desligada ou sem internet).", "Phone Mouse")
        threading.Thread(target=job, daemon=True).start()

    def toggle_startup(_icon, _item):
        if STARTUP_LNK.exists():
            STARTUP_LNK.unlink()
        else:
            make_shortcut(STARTUP_LNK)

    def quit_app(icon, _item):
        for b in ("left", "right", "middle"):
            button(b, False)
        loop.call_soon_threadsafe(loop.stop)
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem(lambda _: f"Wi-Fi: https://{primary_ip() or '?'}:{PORT}", None, enabled=False),
        pystray.MenuItem(lambda _: "Cabo: conectado" if usb_state["device"] else
                         ("Cabo: sem celular" if ADB else "Cabo: adb não instalado"), None, enabled=False),
        pystray.MenuItem("Modo administrador: ativo" if is_admin() else
                         "Modo administrador: desligado", None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Enviar link para o celular", lambda: notify_bg(), default=True),
        pystray.MenuItem("Ativar modo administrador (jogos e apps admin)", lambda: install_admin(),
                         visible=not is_admin()),
        pystray.MenuItem("Iniciar com o Windows", toggle_startup, checked=lambda _: STARTUP_LNK.exists()),
        pystray.MenuItem("Sair", quit_app),
    )
    tray = pystray.Icon("phone-mouse", Image.open(ICON_PNG), "Phone Mouse", menu)
    notify_bg(wait=True)
    tray.run()


def main():
    load_config()
    ensure_icons()
    if "--make-desktop-shortcut" in sys.argv:
        make_shortcut(desktop_dir() / "Phone Mouse.lnk")
        print(f"Atalho criado em {desktop_dir()}")
        return
    if "--install-admin" in sys.argv:
        install_admin()
        return
    if already_running():
        # clicou de novo no atalho: só reenvia o link para o celular
        print("Já está rodando; reenviando notificação.")
        send_notification()
        return
    ensure_cert(local_ips())
    if "--console" in sys.argv:
        run_console()
    else:
        run_tray()


if __name__ == "__main__":
    main()
