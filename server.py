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
from urllib.parse import urlparse

from aiohttp import WSMsgType, web

PORT = int(os.environ.get("PHONE_MOUSE_PORT", "8443"))   # variável só para testes
FROZEN = bool(getattr(sys, "frozen", False))   # rodando como PhoneMouse.exe (instalador)
APP_DIR = Path(sys.executable).resolve().parent if FROZEN else Path(__file__).resolve().parent
RES = Path(getattr(sys, "_MEIPASS", APP_DIR))   # arquivos que vêm com o programa (static/)
# dados do usuário: na pasta do projeto (modo script) ou em %LOCALAPPDATA%\Phone Mouse (instalado)
BASE = (Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "Phone Mouse") if FROZEN else APP_DIR
BASE.mkdir(parents=True, exist_ok=True)
CERT, KEY = BASE / "cert.pem", BASE / "key.pem"
CONFIG = BASE / "config.json"
ICON_PNG = (BASE / "icon.png") if FROZEN else (APP_DIR / "static" / "icon.png")
ICON_ICO = BASE / "icon.ico"
# instalado pela 1ª vez num PC que já usava a versão em script: aproveita PIN, tópico e certificado
if FROZEN and not CONFIG.exists():
    _legacy = Path.home() / "phone-mouse"
    for _name in ("config.json", "cert.pem", "key.pem", "ca.pem", "ca-key.pem"):   # a autoridade também:
        # assim os celulares que já confiam neste PC continuam sem aviso
        try:
            if (_legacy / _name).is_file():
                shutil.copy2(_legacy / _name, BASE / _name)
        except OSError:
            pass
STARTUP_LNK = Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs/Startup/Phone Mouse.lnk"

# sem console (pythonw): manda as mensagens para um arquivo de log
if sys.stdout is None:
    sys.stdout = sys.stderr = open(BASE / "phone-mouse.log", "a", encoding="utf-8", buffering=1)

# ---------------------------------------------------------------- config
def new_pin() -> str:
    return f"{secrets.randbelow(10**6):06d}"


def save_config(cfg: dict) -> None:
    CONFIG.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


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
    if not cfg.get("pin"):
        cfg["pin"] = new_pin()
        changed = True
    if not cfg.get("local_token"):   # só o próprio PC conhece: usado para compartilhar arquivos
        cfg["local_token"] = secrets.token_hex(16)
        changed = True
    if not cfg.get("session_key"):   # cookie dos celulares pareados (trocado em "Gerar novo PIN")
        cfg["session_key"] = secrets.token_urlsafe(32)
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


def physical_addresses() -> list[tuple[str, str]]:
    """(ip, nome da placa) das placas de rede FÍSICAS conectadas (sem WSL, VirtualBox, etc.)."""
    ps = ("Get-NetAdapter -Physical | Where-Object Status -eq 'Up' | ForEach-Object {"
          " $n=$_.Name; Get-NetIPAddress -InterfaceIndex $_.ifIndex -AddressFamily IPv4 -EA SilentlyContinue |"
          " Where-Object { $_.IPAddress -notlike '169.254.*' } | ForEach-Object { \"$($_.IPAddress)|$n\" } }")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True,
                             timeout=15, creationflags=subprocess.CREATE_NO_WINDOW).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return [tuple(line.strip().split("|", 1)) for line in out.splitlines() if "|" in line]


CA_CERT, CA_KEY = BASE / "ca.pem", BASE / "ca-key.pem"
CA_DAYS = 730   # validade da autoridade local (2 anos): limita o estrago se a chave um dia vazar
# a autoridade local só vale para endereços de rede local: mesmo copiada, não serve para sites da internet
_LOCAL_NETS = ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "127.0.0.0/8", "169.254.0.0/16", "100.64.0.0/10"]


def _is_local_ip(ip: str) -> bool:
    try:
        a = ipaddress.ip_address(ip)
        return a.version == 4 and any(a in ipaddress.ip_network(n) for n in _LOCAL_NETS)
    except ValueError:
        return False


def ensure_ca():
    """Autoridade certificadora deste PC (criada uma vez). O celular confia nela uma única vez."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    now = datetime.datetime.now(datetime.timezone.utc)
    if CA_CERT.exists() and CA_KEY.exists():
        try:
            cert = x509.load_pem_x509_certificate(CA_CERT.read_bytes())
            # vale no máximo CA_DAYS e é refeita perto de vencer (antigas de 10 anos também são trocadas)
            if (cert.not_valid_after_utc - now > datetime.timedelta(days=30)
                    and cert.not_valid_after_utc - cert.not_valid_before_utc <= datetime.timedelta(days=CA_DAYS + 1)):
                return cert, serialization.load_pem_private_key(CA_KEY.read_bytes(), password=None)
            print("[cert] autoridade local antiga ou perto de vencer: criando uma nova (confie de novo no celular)")
        except Exception:
            pass
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"Phone Mouse CA ({pc_name()})"[:64]),
                      x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Phone Mouse")])
    permitted = [x509.DNSName("localhost")] + [x509.IPAddress(ipaddress.ip_network(n)) for n in _LOCAL_NETS]
    cert = (x509.CertificateBuilder()
            .subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=CA_DAYS))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=False, content_commitment=False, key_encipherment=False,
                                         data_encipherment=False, key_agreement=False, key_cert_sign=True,
                                         crl_sign=True, encipher_only=False, decipher_only=False), critical=True)
            .add_extension(x509.NameConstraints(permitted_subtrees=permitted, excluded_subtrees=None), critical=True)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
            .sign(key, hashes.SHA256()))
    CA_KEY.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
                                         serialization.NoEncryption()))
    CA_CERT.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    print("[cert] autoridade local criada")
    return cert, key


def ensure_cert(ips: list[str]) -> bool:
    """Certificado do PC assinado pela autoridade local. Refaz se faltar, vencer em breve, não for da
    autoridade ou não cobrir um endereço atual (troca de rede). Retorna True se gerou um novo."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
    ca_cert, ca_key = ensure_ca()
    ips = sorted({i for i in ips if _is_local_ip(i)} | {"127.0.0.1"})
    now = datetime.datetime.now(datetime.timezone.utc)
    if CERT.exists() and KEY.exists():
        try:
            cur = x509.load_pem_x509_certificate(CERT.read_bytes())
            san = cur.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
            have = {str(i) for i in san.get_values_for_type(x509.IPAddress)}
            cur.verify_directly_issued_by(ca_cert)   # assinado pela autoridade atual (não por uma antiga)
            if (set(ips) <= have and cur.not_valid_after_utc - now > datetime.timedelta(days=30)
                    and cur.not_valid_after_utc <= ca_cert.not_valid_after_utc):
                return False
        except Exception:
            pass
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    san = [x509.DNSName("localhost")] + [x509.IPAddress(ipaddress.ip_address(i)) for i in ips]
    cert = (x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, pc_name()[:64] or "phone-mouse")]))
            .issuer_name(ca_cert.subject).public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1))
            # total < 398 dias (limite de iPhone/Chrome) e nunca além da validade da autoridade
            .not_valid_after(min(now + datetime.timedelta(days=395), ca_cert.not_valid_after_utc))
            .add_extension(x509.SubjectAlternativeName(san), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=False, key_encipherment=True,
                                         data_encipherment=False, key_agreement=False, key_cert_sign=False,
                                         crl_sign=False, encipher_only=False, decipher_only=False), critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
            .sign(ca_key, hashes.SHA256()))
    KEY.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
                                      serialization.NoEncryption()))
    # o arquivo leva o certificado do PC + o da autoridade (cadeia completa)
    CERT.write_bytes(cert.public_bytes(serialization.Encoding.PEM) + ca_cert.public_bytes(serialization.Encoding.PEM))
    print(f"[cert] certificado do PC renovado para: {', '.join(ips)}")
    return True


def ca_der() -> bytes:
    from cryptography.hazmat.primitives import serialization
    return ensure_ca()[0].public_bytes(serialization.Encoding.DER)


def ca_fingerprint() -> str:
    import hashlib
    h = hashlib.sha256(ca_der()).hexdigest().upper()
    return ":".join(h[i:i + 2] for i in range(0, 16, 2))   # início do SHA-256, para conferir


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


def launch_cmd(*args: str) -> tuple[str, str]:
    """(programa, argumentos) que abrem este app: o PhoneMouse.exe ou pythonw + server.py."""
    extra = " ".join(args)
    if FROZEN:
        return str(Path(sys.executable).resolve()), extra
    return pythonw(), f'"{APP_DIR / "server.py"}" {extra}'.strip()


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
        (tgt, args), style = launch_cmd(), 1
    write_lnk(lnk, tgt, args, style)


SENDTO_LNK = Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/SendTo/Phone Mouse (celular).lnk"


def ensure_sendto() -> None:
    """Botão direito num arquivo -> Enviar para -> Phone Mouse (celular)."""
    if not SENDTO_LNK.exists():
        try:
            write_lnk(SENDTO_LNK, *launch_cmd("--send"), 1)
        except (OSError, subprocess.SubprocessError) as e:
            print(f"[arquivos] não consegui criar o 'Enviar para': {e}")


def write_lnk(lnk: Path, tgt: str, args: str, style: int) -> None:
    ps = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:LNK);"
          "$s.TargetPath=$env:TGT;$s.Arguments=$env:ARGS;$s.WorkingDirectory=$env:WD;"
          "$s.IconLocation=$env:ICO;$s.WindowStyle=[int]$env:STYLE;$s.Description='Phone Mouse';$s.Save()")
    env = dict(os.environ, LNK=str(lnk), TGT=tgt, ARGS=args, WD=str(APP_DIR), ICO=str(ICON_ICO), STYLE=str(style))
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], env=env, check=True,
                   creationflags=subprocess.CREATE_NO_WINDOW)


def _stop_server() -> None:
    ps = ("Get-NetTCPConnection -LocalPort $env:PORT -State Listen -EA SilentlyContinue |"
          " ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -EA SilentlyContinue }")
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], env=dict(os.environ, PORT=str(PORT)),
                   creationflags=subprocess.CREATE_NO_WINDOW)


def uninstall(admin_part: bool = False) -> None:
    """Chamado pelo desinstalador: encerra o servidor e remove atalhos, tarefa agendada, firewall e a
    autoridade local (chave e certificados). As configurações (PIN, tópico de notificação) ficam em
    %LOCALAPPDATA%\\Phone Mouse. Sem a chave, a autoridade que ficou nos celulares não assina mais nada."""
    if admin_part:   # parte que precisa de administrador (roda elevada)
        subprocess.run([SCHTASKS, "/end", "/tn", TASK], capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
        subprocess.run([SCHTASKS, "/delete", "/tn", TASK, "/f"], capture_output=True,
                       creationflags=subprocess.CREATE_NO_WINDOW)
        subprocess.run(["powershell", "-NoProfile", "-Command",
                        "Remove-NetFirewallRule -DisplayName 'Phone Mouse' -EA SilentlyContinue"],
                       creationflags=subprocess.CREATE_NO_WINDOW)
        _stop_server()
        return
    for lnk in (STARTUP_LNK, SENDTO_LNK, desktop_dir() / "Phone Mouse.lnk"):
        try:
            lnk.unlink(missing_ok=True)
        except OSError:
            pass
    has_rule = subprocess.run(["powershell", "-NoProfile", "-Command",
                               "if (Get-NetFirewallRule -DisplayName 'Phone Mouse' -EA SilentlyContinue) { exit 1 }"],
                              creationflags=subprocess.CREATE_NO_WINDOW).returncode == 1
    if task_exists() or has_rule:
        exe, args = launch_cmd("--uninstall-admin")
        if is_admin():
            uninstall(admin_part=True)
        else:   # pede administrador uma vez e espera terminar
            subprocess.run(["powershell", "-NoProfile", "-Command",
                            "Start-Process -FilePath $env:EXE -ArgumentList $env:ARGS -Verb RunAs -Wait -WindowStyle Hidden"],
                           env=dict(os.environ, EXE=exe, ARGS=args), creationflags=subprocess.CREATE_NO_WINDOW)
    _stop_server()
    for f in (CA_KEY, CA_CERT, KEY, CERT):
        try:
            f.unlink(missing_ok=True)
        except OSError:
            pass


def install_admin() -> None:
    """Cria a tarefa agendada que roda o servidor como administrador.
    Precisa de UAC uma única vez; depois o atalho abre como admin sem perguntar."""
    if not is_admin():
        exe, args = launch_cmd("--install-admin")
        ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, args, str(APP_DIR), 1)
        return
    ps = ("$a=New-ScheduledTaskAction -Execute $env:TGT -Argument $env:ARGS -WorkingDirectory $env:WD;"
          "$p=New-ScheduledTaskPrincipal -UserId \"$env:USERDOMAIN\\$env:USERNAME\" -LogonType Interactive -RunLevel Highest;"
          "$s=New-ScheduledTaskSettingsSet -MultipleInstances Parallel -ExecutionTimeLimit ([TimeSpan]::Zero)"
          " -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries;"
          "Register-ScheduledTask -TaskName $env:TASK -Action $a -Principal $p -Settings $s -Force | Out-Null;"
          # libera a porta no firewall já na instalação: a janela "Permitir acesso" não aparece
          "Remove-NetFirewallRule -DisplayName 'Phone Mouse' -EA SilentlyContinue;"
          "New-NetFirewallRule -DisplayName 'Phone Mouse' -Direction Inbound -Action Allow -Protocol TCP"
          " -LocalPort $env:PORT -Program $env:TGT -Profile Any | Out-Null;"
          # encerra o servidor antigo (sem admin) que está ocupando a porta
          "Get-NetTCPConnection -LocalPort $env:PORT -State Listen -EA SilentlyContinue |"
          " ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -EA SilentlyContinue }")
    exe, args = launch_cmd()
    env = dict(os.environ, TGT=exe, ARGS=args, WD=str(APP_DIR), TASK=TASK, PORT=str(PORT))
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
             APP_DIR / "platform-tools" / "adb.exe",
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


# ---------------------------------------------------------------- página de configuração da notificação
SETUP_HTML = BASE / "notificacao.html"


NTFY_PLAY = "https://play.google.com/store/apps/details?id=io.heckel.ntfy"
NTFY_APPSTORE = "https://apps.apple.com/us/app/ntfy/id1625396347"


def _qr_png_b64(data: str) -> str:
    import base64
    import io
    import qrcode
    buf = io.BytesIO()
    qrcode.make(data, box_size=8, border=2).save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def open_notification_setup() -> None:
    """Página local: QR para baixar o ntfy (Play Store / App Store) ao lado do QR/tópico para assinar."""
    import html

    cfg = load_config()
    topic = cfg["ntfy_topic"]
    qr_sub = _qr_png_b64(f"ntfy://ntfy.sh/{topic}?display=Phone%20Mouse")
    qr_play = _qr_png_b64(NTFY_PLAY)
    qr_ios = _qr_png_b64(NTFY_APPSTORE)
    t = html.escape(topic)
    off = "" if cfg.get("notify") else (
        '<p class="warn">⚠️ A notificação está <b>desligada</b> neste PC '
        '(<code>"notify": false</code> no config.json).</p>')
    page = f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Phone Mouse - notificação</title>
<style>
 :root {{ --bg:#f6f7f9; --fg:#1b1d21; --card:#fff; --mut:#5b6270; --acc:#2563eb; --line:#e3e6ea; }}
 @media (prefers-color-scheme: dark) {{ :root {{ --bg:#111317; --fg:#e8eaee; --card:#1a1d23; --mut:#9aa1ad; --acc:#60a5fa; --line:#2a2f37; }} }}
 body {{ margin:0; background:var(--bg); color:var(--fg); font:16px/1.5 system-ui,sans-serif; }}
 main {{ max-width:860px; margin:0 auto; padding:32px 16px; }}
 h1 {{ font-size:26px; margin:0 0 4px; }} .sub {{ color:var(--mut); margin:0 0 24px; }}
 .card {{ background:var(--card); border:1px solid var(--line); border-radius:14px; padding:20px; margin-bottom:16px; }}
 h2 {{ font-size:18px; margin:0 0 14px; }}
 .pair {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(230px,1fr)); gap:16px; }}
 .step {{ text-align:center; border:1px solid var(--line); border-radius:12px; padding:14px; }}
 .step b.n {{ display:inline-block; width:26px; height:26px; line-height:26px; border-radius:13px; background:var(--acc); color:#fff; margin-right:6px; }}
 .step p {{ margin:4px 0 0; color:var(--mut); font-size:14px; }}
 .qr {{ display:block; width:190px; max-width:100%; margin:10px auto 6px; background:#fff; padding:8px; border-radius:10px; }}
 .topic {{ display:flex; gap:8px; align-items:center; margin:14px 0 8px; text-align:left; }}
 .topic code {{ flex:1; font-size:16px; padding:10px 12px; border-radius:8px; background:var(--bg); border:1px solid var(--line); word-break:break-all; }}
 button {{ font:inherit; padding:10px 14px; border:0; border-radius:8px; background:var(--acc); color:#fff; cursor:pointer; }}
 .steps {{ text-align:left; margin:8px 0 0; padding-left:20px; font-size:14px; }}
 .warn {{ background:#fef3c7; color:#78350f; padding:10px 12px; border-radius:8px; }}
 .foot {{ color:var(--mut); font-size:14px; margin-top:8px; }}
</style></head><body><main>
<h1>Notificação no celular</h1>
<p class="sub">Receba "Phone Mouse pronto - {html.escape(pc_name())}" com o link de acesso sempre que o PC ligar.
Aponte a câmera do celular para os QR codes, na ordem.</p>
{off}
<section class="card"><h2>🤖 Android</h2><div class="pair">
 <div class="step"><b class="n">1</b><b>Baixe o ntfy</b>
  <img class="qr" alt="QR code do ntfy na Google Play" src="data:image/png;base64,{qr_play}">
  <p>Abre a Google Play</p></div>
 <div class="step"><b class="n">2</b><b>Assine o tópico</b>
  <img class="qr" alt="QR code para assinar o tópico no ntfy" src="data:image/png;base64,{qr_sub}">
  <p>Abre o ntfy e assina sozinho</p></div>
</div></section>
<section class="card"><h2>🍎 iPhone</h2><div class="pair">
 <div class="step"><b class="n">1</b><b>Baixe o ntfy</b>
  <img class="qr" alt="QR code do ntfy na App Store" src="data:image/png;base64,{qr_ios}">
  <p>Abre a App Store · permita notificações</p></div>
 <div class="step"><b class="n">2</b><b>Assine o tópico</b>
  <div class="topic"><code>{t}</code><button onclick="navigator.clipboard.writeText('{t}').then(()=>this.textContent='Copiado!')">Copiar</button></div>
  <ol class="steps"><li>No ntfy, toque em <b>+</b></li><li>Digite o tópico acima</li><li>Toque em <b>Subscribe</b></li></ol>
  <p>O iPhone não aceita assinar por QR code.</p></div>
</div></section>
<p class="foot">Para testar: ícone do Phone Mouse perto do relógio → <b>Enviar link para o celular</b>.<br>
O tópico funciona como uma senha: não o publique. Para usar o mesmo tópico em outro PC, copie o <code>config.json</code>.</p>
</main></body></html>"""
    SETUP_HTML.write_text(page, encoding="utf-8")
    # via explorer: abre o navegador sem privilégio de administrador mesmo se o servidor for admin
    subprocess.Popen(["explorer.exe", str(SETUP_HTML)])


# ---------------------------------------------------------------- QR do endereço + mudança de rede
ADDR_HTML = BASE / "endereco.html"


def open_address_page(reason: str = "") -> None:
    """Abre no PC uma página com QR code do endereço atual (o celular abre pela câmera)."""
    import base64
    import html
    import io
    import qrcode

    ip = primary_ip()
    if not ip:
        return
    url = f"https://{ip}:{PORT}"
    buf = io.BytesIO()
    qrcode.make(pin_url(url), box_size=10, border=2).save(buf, format="PNG")   # QR com PIN embutido
    qr = base64.b64encode(buf.getvalue()).decode()
    others = [(a, n) for a, n in physical_addresses() if a != ip]
    alt = ""
    if others:
        items = "".join(f"<li><code>https://{html.escape(a)}:{PORT}</code> <span>({html.escape(n)})</span></li>"
                        for a, n in others)
        alt = (f"<div class='alt'><b>Não abriu?</b> O PC está em mais de uma rede. Se o celular estiver na outra, "
               f"use:<ul>{items}</ul></div>")
    note = f"<p class='why'>{html.escape(reason)}</p>" if reason else ""
    page = f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Phone Mouse - endereço</title>
<style>
 :root {{ --bg:#f6f7f9; --fg:#1b1d21; --card:#fff; --mut:#5b6270; --line:#e3e6ea; }}
 @media (prefers-color-scheme: dark) {{ :root {{ --bg:#111317; --fg:#e8eaee; --card:#1a1d23; --mut:#9aa1ad; --line:#2a2f37; }} }}
 body {{ margin:0; background:var(--bg); color:var(--fg); font:16px/1.5 system-ui,sans-serif; }}
 main {{ max-width:560px; margin:0 auto; padding:32px 16px; text-align:center; }}
 h1 {{ font-size:26px; margin:0 0 6px; }} .why {{ color:var(--mut); margin:0 0 16px; }}
 .qr {{ width:300px; max-width:90vw; background:#fff; padding:10px; border-radius:14px; }}
 .url {{ font-size:22px; font-weight:600; margin:14px 0 4px; word-break:break-all; }}
 .pin {{ font-size:20px; margin:6px 0 0; color:var(--mut); }} .pin b {{ color:var(--fg); letter-spacing:4px; font-size:26px; }}
 .alt {{ text-align:left; background:var(--card); border:1px solid var(--line); border-radius:12px; padding:14px 16px; margin-top:20px; }}
 .alt ul {{ margin:8px 0 0; padding-left:20px; }} .alt span {{ color:var(--mut); }}
 .foot {{ color:var(--mut); font-size:14px; margin-top:20px; }}
</style></head><body><main>
<h1>Abra no celular</h1>{note}
<img class="qr" alt="QR code com o endereço do Phone Mouse" src="data:image/png;base64,{qr}">
<div class="url">{html.escape(url)}</div>
<div class="pin">PIN: <b>{html.escape(current_pin())}</b></div>
<p class="foot">Aponte a câmera do celular para o QR code (ele já leva o PIN). O celular precisa estar na mesma rede do PC.<br>
Esta página pode ser fechada (Alt+F4).<br>
Aviso de "site perigoso" no celular? Abra <b>{html.escape(url)}/ca</b> para resolver de vez.</p>
{alt}
</main></body></html>"""
    ADDR_HTML.write_text(page, encoding="utf-8")
    subprocess.Popen(["explorer.exe", str(ADDR_HTML)])


def open_trust_page() -> None:
    """QR code que abre no celular a página "Confiar neste PC" (remove o aviso de site perigoso)."""
    import html
    ip = primary_ip()
    if not ip:
        return
    url = f"https://{ip}:{PORT}/ca"
    qr = _qr_png_b64(url)
    page = f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Phone Mouse - confiar neste PC</title>
<style>
 :root {{ --bg:#f6f7f9; --fg:#1b1d21; --mut:#5b6270; }}
 @media (prefers-color-scheme: dark) {{ :root {{ --bg:#111317; --fg:#e8eaee; --mut:#9aa1ad; }} }}
 body {{ margin:0; background:var(--bg); color:var(--fg); font:16px/1.5 system-ui,sans-serif; }}
 main {{ max-width:520px; margin:0 auto; padding:32px 16px; text-align:center; }}
 h1 {{ font-size:24px; margin:0 0 6px; }} p {{ color:var(--mut); }}
 .qr {{ width:260px; max-width:90vw; background:#fff; padding:10px; border-radius:14px; }}
 code {{ font-size:15px; word-break:break-all; }}
</style></head><body><main>
<h1>Tirar o aviso de "site perigoso"</h1>
<p>Aponte a câmera do celular para o QR code e siga os passos da página que abrir.
Faça isso uma vez por celular.</p>
<img class="qr" alt="QR code da página Confiar neste PC" src="data:image/png;base64,{qr}">
<p><code>{html.escape(url)}</code></p>
<p>No iPhone, abra o link no <b>Safari</b>: só ele instala o perfil.</p>
</main></body></html>"""
    path = BASE / "confiar.html"
    path.write_text(page, encoding="utf-8")
    subprocess.Popen(["explorer.exe", str(path)])


def check_network_change(state: dict, on_change) -> None:
    """Compara o endereço atual com o último; se mudou (ex.: cabo -> Wi-Fi), chama on_change."""
    ip = primary_ip()
    if ip and ip != state.get("ip"):
        old, state["ip"] = state.get("ip"), ip
        if old:
            on_change(old, ip)


def watch_network(on_change, interval: float = 5) -> None:
    state = {"ip": primary_ip()}
    while True:
        time.sleep(interval)
        try:
            check_network_change(state, on_change)
        except Exception as e:   # o vigia nunca pode derrubar o servidor
            print(f"[rede] erro ao verificar: {e}")


def handle_network_change(old: str, new: str, tray_notify=None) -> None:
    print(f"[rede] endereço mudou: {old} -> {new}")
    try:
        reload_cert()
    except Exception as e:
        print(f"[cert] não consegui renovar: {e}")
    url = f"https://{new}:{PORT}"
    send_notification()
    if tray_notify:
        tray_notify(f"A rede mudou. Novo endereço: {url}")
    if clients["n"] == 0:   # nenhum celular conectado: mostra o QR novo na tela
        open_address_page(f"A rede do PC mudou ({old} → {new}). Use o endereço novo:")


# ---------------------------------------------------------------- handlers
async def index(_req):
    return web.FileResponse(RES / "static" / "index.html", headers={"Cache-Control": "no-cache"})


# ---------------------------------------------------------------- PIN de acesso
# O PIN só serve para parear: o celular manda o PIN no corpo de um POST /pair (nunca na URL, para não
# ficar em histórico nem em logs) e recebe um cookie de sessão HttpOnly. Todo o resto usa o cookie.
MAX_FAILS = 5                        # PINs errados seguidos por aparelho antes de bloquear
BLOCK_BASE, BLOCK_MAX = 60, 3600     # bloqueio progressivo por aparelho: 1 min, 2, 4, 8... até 1 h
GLOBAL_WINDOW, GLOBAL_MAX = 60, 10   # no máximo 10 PINs errados por minuto somando todos os aparelhos
ROTATE_AFTER = 30                    # 30 PINs errados (somando todos) sem nenhum acerto: troca o PIN sozinho
SESSION_COOKIE = "pm_session"
_fails: dict[str, list] = {}         # ip -> [erros seguidos, bloqueios já aplicados, bloqueado até]
_recent_fails: list[float] = []      # horários dos últimos erros (todos os aparelhos)
_total_fails = {"n": 0}              # erros desde o último acerto ou troca de PIN


def current_pin() -> str:
    return str(load_config()["pin"])


def session_key() -> str:
    return str(load_config()["session_key"])


def is_paired(req) -> bool:
    """O celular já pareou com o PIN atual (tem o cookie de sessão válido)?"""
    tok = req.cookies.get(SESSION_COOKIE, "")
    return bool(tok) and secrets.compare_digest(tok.encode(), session_key().encode())


def _reset_pin_counters() -> None:
    _fails.clear()
    _recent_fails.clear()
    _total_fails["n"] = 0


def pin_url(base: str) -> str:
    """Endereço com o PIN embutido: escanear o QR da tela do PC já pareia o celular."""
    return f"{base}/#pin={current_pin()}"


def check_pin(ip: str, pin: str) -> int:
    """200 = ok, 401 = PIN errado/ausente, 429 = muitas tentativas (aguarde).
    Limites: por aparelho (bloqueio progressivo) e no total (trocar de IP não ajuda quem tenta adivinhar)."""
    now = time.time()
    fails, blocks, until = _fails.get(ip, [0, 0, 0.0])
    if until > now:
        return 429
    _recent_fails[:] = [t for t in _recent_fails if now - t < GLOBAL_WINDOW]
    if len(_recent_fails) >= GLOBAL_MAX:
        return 429
    pin = "".join(c for c in str(pin) if c in "0123456789")[:6]
    if len(pin) == 6 and secrets.compare_digest(pin, current_pin()):
        _fails.pop(ip, None)
        _total_fails["n"] = 0
        return 200
    _recent_fails.append(now)
    _total_fails["n"] += 1
    fails += 1
    if fails >= MAX_FAILS:
        secs = min(BLOCK_BASE * 2 ** blocks, BLOCK_MAX)
        _fails[ip] = [0, blocks + 1, now + secs]
        print(f"[pin] {ip} bloqueado por {secs}s após {MAX_FAILS} PINs errados")
    else:
        _fails[ip] = [fails, blocks, 0.0]
    if _total_fails["n"] >= ROTATE_AFTER:
        # alguém está tentando adivinhar: troca o PIN (celulares já pareados continuam conectados)
        cfg = load_config()
        cfg["pin"] = new_pin()
        save_config(cfg)
        _reset_pin_counters()
        print(f"[pin] {ROTATE_AFTER} PINs errados: PIN trocado automaticamente")
        toast_pc("Muitos PINs errados no celular. Por segurança o PIN foi trocado (veja no ícone da bandeja).")
    return 401


active_ws: set = set()
loop_ref: dict = {}


def regenerate_pin() -> str:
    """Novo PIN: desconecta todos os celulares e invalida os pareamentos (eles pedem o PIN de novo)."""
    cfg = load_config()
    cfg["pin"] = new_pin()
    cfg["session_key"] = secrets.token_urlsafe(32)
    save_config(cfg)
    _reset_pin_counters()
    loop = loop_ref.get("loop")
    if loop:
        for ws in list(active_ws):
            asyncio.run_coroutine_threadsafe(ws.close(code=4001, message=b"pin"), loop)
    print("[pin] novo PIN gerado")
    return cfg["pin"]


# ---------------------------------------------------------------- arquivos
def downloads_dir() -> Path:
    """Pasta Downloads do Windows (respeita se o usuário a moveu)."""
    try:
        import uuid
        class GUID(ctypes.Structure):
            _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
                        ("Data4", ctypes.c_ubyte * 8)]
        u = uuid.UUID("374DE290-123F-4565-9164-39C4925E467B")   # FOLDERID_Downloads
        g = GUID(u.fields[0], u.fields[1], u.fields[2], (ctypes.c_ubyte * 8)(*u.bytes[8:]))
        out = ctypes.c_wchar_p()
        if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(g), 0, None, ctypes.byref(out)) == 0:
            path = Path(out.value)
            ctypes.windll.ole32.CoTaskMemFree(out)
            return path
    except Exception:
        pass
    return Path.home() / "Downloads"


RECEIVED_DIR = downloads_dir() / "Phone Mouse"
events: dict = {"toast": None}   # a bandeja registra aqui como mostrar avisos no PC
_last_folder_open = {"t": 0.0}


def toast_pc(msg: str) -> None:
    if events["toast"]:
        try:
            events["toast"](msg)
        except Exception:
            pass


def safe_filename(name: str) -> str:
    name = Path(str(name).replace("\\", "/")).name           # tira qualquer caminho
    name = "".join("_" if c in '<>:"/\\|?*' or ord(c) < 32 else c for c in name).strip(" .")
    return (name or "arquivo")[:180]


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    for i in range(1, 10000):
        cand = path.with_name(f"{path.stem} ({i}){path.suffix}")
        if not cand.exists():
            return cand
    return path.with_name(f"{path.stem} ({secrets.token_hex(3)}){path.suffix}")


async def upload(req):
    """Celular -> PC: o corpo da requisição é o arquivo; salva em Downloads\\Phone Mouse."""
    if not is_paired(req):
        return web.json_response({"error": "pin"}, status=401)
    RECEIVED_DIR.mkdir(parents=True, exist_ok=True)
    dest = unique_path(RECEIVED_DIR / safe_filename(req.query.get("name", "arquivo")))
    part = dest.with_name(dest.name + ".part")
    size = 0
    try:
        with open(part, "wb") as f:
            async for chunk in req.content.iter_chunked(1 << 16):
                f.write(chunk)
                size += len(chunk)
        part.replace(dest)
    except Exception:
        part.unlink(missing_ok=True)
        raise
    print(f"[arquivos] recebido do celular: {dest.name} ({size} bytes)")
    toast_pc(f"Recebido do celular: {dest.name}")
    if time.time() - _last_folder_open["t"] > 15:   # abre a pasta (uma vez por leva de arquivos)
        _last_folder_open["t"] = time.time()
        subprocess.Popen(["explorer.exe", f"/select,{dest}"])
    return web.json_response({"ok": True, "name": dest.name, "size": size})


shared_files: list[dict] = []   # PC -> celular: só o que o usuário escolheu compartilhar


def broadcast(msg: dict) -> None:
    loop = loop_ref.get("loop")
    if loop:
        for ws in list(active_ws):
            asyncio.run_coroutine_threadsafe(ws.send_json(msg), loop)


def share_paths(paths) -> list[str]:
    added = []
    for p in paths:
        path = Path(p)
        if not path.is_file():
            continue
        item = {"id": secrets.token_urlsafe(9), "name": path.name, "path": str(path),
                "size": path.stat().st_size, "t": time.time()}
        shared_files.insert(0, item)
        added.append(path.name)
        broadcast({"t": "file", "id": item["id"], "name": item["name"], "size": item["size"]})
    del shared_files[30:]
    if added:
        print(f"[arquivos] disponível no celular: {', '.join(added)}")
        toast_pc("Disponível no celular: " + ", ".join(added) +
                 ("" if clients["n"] else " (abra o Phone Mouse no celular para baixar)"))
    return added


async def share(req):
    """Só o próprio PC (com o token local) pode adicionar arquivos à lista."""
    if (req.remote not in ("127.0.0.1", "::1")
            or not secrets.compare_digest(req.headers.get("X-Token", "").encode(),
                                          str(load_config()["local_token"]).encode())):
        return web.json_response({"error": "token"}, status=403)
    data = await req.json()
    added = share_paths(data.get("paths", []))
    return web.json_response({"ok": True, "added": added})


async def files_list(req):
    if not is_paired(req):
        return web.json_response({"error": "pin"}, status=401)
    return web.json_response([{k: f[k] for k in ("id", "name", "size", "t")} for f in shared_files])


async def file_get(req):
    if not is_paired(req):
        return web.json_response({"error": "pin"}, status=401)
    item = next((f for f in shared_files if f["id"] == req.match_info["fid"]), None)
    if not item or not Path(item["path"]).is_file():
        return web.json_response({"error": "não encontrado"}, status=404)
    from urllib.parse import quote
    return web.FileResponse(item["path"], headers={
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(item['name'])}"})


def send_cli(paths: list[str]) -> None:
    """--send (usado pelo 'Enviar para' do Explorer): entrega os arquivos ao servidor que está rodando."""
    files = [str(Path(p).resolve()) for p in paths if Path(p).is_file()]
    msg = None
    if not files:
        msg = "Escolha um ou mais arquivos (pastas não são enviadas)."
    else:
        body = json.dumps({"paths": files}).encode("utf-8")
        req = urllib.request.Request(
            f"https://127.0.0.1:{PORT}/share", data=body, method="POST",
            headers={"Content-Type": "application/json", "X-Token": str(load_config()["local_token"])})
        try:
            urllib.request.urlopen(req, context=ssl._create_unverified_context(), timeout=10).close()
        except OSError:
            msg = "O Phone Mouse não está rodando. Abra o atalho Phone Mouse e tente de novo."
    if msg:
        if sys.stdout and sys.stdout.isatty():
            print(msg)
        else:
            ctypes.windll.user32.MessageBoxW(None, msg, "Phone Mouse", 0x30)


async def info(req):
    if not is_paired(req):
        return web.json_response({"error": "pin"}, status=401)
    return web.json_response({"port": PORT, "name": pc_name(), "primary": primary_ip(),
                              "wifi": local_ips(), **usb_state})


# ---------------------------------------------------------------- confiar no PC (remove o aviso no celular)
async def ca_crt(_req):
    """Certificado da autoridade local (Android). É público: não tem nada secreto."""
    return web.Response(body=ca_der(), content_type="application/x-x509-ca-cert",
                        headers={"Content-Disposition": 'attachment; filename="PhoneMouse-CA.crt"'})


async def ca_mobileconfig(_req):
    """Perfil do iPhone que instala a autoridade local."""
    import plistlib
    import uuid
    der = ca_der()
    base = uuid.uuid5(uuid.NAMESPACE_URL, "phone-mouse-ca:" + ca_fingerprint())
    profile = {
        "PayloadType": "Configuration", "PayloadVersion": 1,
        "PayloadIdentifier": f"com.jvtech.phonemouse.{base}", "PayloadUUID": str(base).upper(),
        "PayloadDisplayName": f"Phone Mouse - {pc_name()}",
        "PayloadDescription": "Faz este celular confiar no Phone Mouse deste PC e remove o aviso de site perigoso. "
                              "Vale só para endereços de rede local.",
        "PayloadOrganization": "Phone Mouse",
        "PayloadContent": [{
            "PayloadType": "com.apple.security.root", "PayloadVersion": 1,
            "PayloadIdentifier": f"com.jvtech.phonemouse.ca.{base}",
            "PayloadUUID": str(uuid.uuid5(base, "ca")).upper(),
            "PayloadDisplayName": "Phone Mouse CA", "PayloadCertificateFileName": "PhoneMouse-CA.cer",
            "PayloadContent": der,
        }],
    }
    return web.Response(body=plistlib.dumps(profile), content_type="application/x-apple-aspen-config",
                        headers={"Content-Disposition": 'attachment; filename="PhoneMouse.mobileconfig"'})


CA_PAGE = """<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Confiar neste PC · Phone Mouse</title>
<style>
 :root{--bg:#0e1014;--s:#171a20;--s2:#20242c;--line:#2a2f38;--fg:#e8eaef;--mut:#8b93a1;--acc:#3b82f6;--ok:#4ade80}
 body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
 main{max-width:560px;margin:0 auto;padding:24px 16px 40px;display:grid;gap:14px}
 h1{font-size:24px;margin:0} .lead{color:var(--mut);margin:0}
 section{background:var(--s);border:1px solid var(--line);border-radius:16px;padding:16px}
 h2{font-size:18px;margin:0 0 10px;display:flex;gap:8px;align-items:center}
 .tag{font-size:11px;font-weight:700;color:#93c5fd;background:rgba(59,130,246,.16);padding:2px 8px;border-radius:99px}
 ol{margin:0;padding-left:20px} li{margin:8px 0} b{font-weight:600}
 .btn{display:inline-block;margin:6px 0;padding:12px 18px;border-radius:12px;background:var(--acc);color:#fff;text-decoration:none;font-weight:600;border:0;font-size:15px}
 .btn.alt{background:var(--s2);color:var(--fg)} code{background:var(--s2);padding:2px 6px;border-radius:6px;font-size:13px;word-break:break-all}
 .note{color:var(--mut);font-size:13px} .ok{color:var(--ok)}
</style></head><body><main>
<h1>Confiar neste PC</h1>
<p class="lead">Faça isto <b>uma vez</b> e o aviso de "site perigoso" some, mesmo quando o endereço do PC mudar.
Vale só para o Phone Mouse na sua rede local.</p>
<section id="ios"><h2>iPhone / iPad <span class="tag" id="ios-tag" hidden>seu aparelho</span></h2><ol>
 <li><b>Abra esta página no Safari</b> (o Chrome do iPhone não instala perfis).
  <br><button class="btn alt" id="copy">Copiar endereço desta página</button></li>
 <li><a class="btn" href="/ca.mobileconfig">Baixar perfil</a> e toque em <b>Permitir</b>.</li>
 <li>Abra <b>Ajustes</b> → <b>Perfil Transferido</b> → <b>Instalar</b> (pede o código do iPhone).</li>
 <li>Abra <b>Ajustes → Geral → Sobre → Ajustes de Confiança de Certificados</b> e
  <b>ative "Phone Mouse CA"</b>.</li>
 <li>Feche e abra de novo a página do Phone Mouse. <span class="ok">Pronto, sem aviso.</span></li></ol></section>
<section id="android"><h2>Android <span class="tag" id="and-tag" hidden>seu aparelho</span></h2><ol>
 <li><a class="btn" href="/ca.crt">Baixar certificado</a></li>
 <li>Abra <b>Configurações → Segurança</b> (ou "Segurança e privacidade") → <b>Mais configurações</b> →
  <b>Criptografia e credenciais</b> → <b>Instalar um certificado</b> → <b>Certificado de CA</b>.</li>
 <li>Toque em <b>Instalar mesmo assim</b> e escolha o arquivo <b>PhoneMouse-CA.crt</b> em Downloads.</li>
 <li>Feche e abra de novo a página do Phone Mouse no Chrome. <span class="ok">Pronto, sem aviso.</span></li></ol>
 <p class="note">Os nomes dos menus variam um pouco entre marcas (Samsung, Motorola, Xiaomi...).</p></section>
<p class="note">Para conferir: o certificado se chama <b>Phone Mouse CA (__PC__)</b> e a impressão digital começa com
<code>__FP__</code>. Para desfazer, remova o perfil (iPhone) ou o certificado (Android) nas configurações.</p>
</main><script>
const ua = navigator.userAgent, ios = /iPhone|iPad|iPod/.test(ua), and = /Android/.test(ua);
if (ios) document.getElementById("ios-tag").hidden = false;
if (and) { document.getElementById("and-tag").hidden = false; document.querySelector("main").insertBefore(document.getElementById("android"), document.getElementById("ios")); }
document.getElementById("copy").onclick = async e => {
  try { await navigator.clipboard.writeText(location.href); e.target.textContent = "Copiado! Cole no Safari"; }
  catch { e.target.textContent = location.href; }
};
</script></body></html>"""


async def ca_page(_req):
    html = CA_PAGE.replace("__PC__", pc_name()).replace("__FP__", ca_fingerprint())
    return web.Response(text=html, content_type="text/html", headers={"Cache-Control": "no-cache"})


async def manifest(_req):
    return web.json_response({
        "name": "Phone Mouse", "short_name": "Phone Mouse", "start_url": "/",
        "display": "fullscreen", "orientation": "any",
        "background_color": "#111111", "theme_color": "#111111",
        "icons": [{"src": "/icon.png", "sizes": "512x512", "type": "image/png", "purpose": "any"}],
    }, content_type="application/manifest+json")


async def icon(_req):
    return web.FileResponse(ICON_PNG)


clients = {"n": 0}   # celulares conectados agora


async def ws_handler(req):
    ws = web.WebSocketResponse(heartbeat=10)
    await ws.prepare(req)
    origin = req.headers.get("Origin")
    if origin and urlparse(origin).netloc != req.host:   # outra página tentando usar o cookie do celular
        await ws.close(code=4003, message=b"origin")
        return ws
    if not is_paired(req):   # 4001 = precisa parear (PIN)
        await ws.close(code=4001, message=b"pin")
        return ws
    active_ws.add(ws)
    clients["n"] += 1
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
        clients["n"] -= 1
        active_ws.discard(ws)
        print(f"[-] desconectado: {req.remote}")
    return ws


async def pair(req):
    """Pareia o celular: recebe o PIN no corpo (JSON) e devolve o cookie de sessão."""
    try:
        data = await req.json()
    except Exception:
        data = {}
    st = check_pin(req.remote or "?", str(data.get("pin", "")) if isinstance(data, dict) else "")
    if st != 200:
        return web.json_response({"error": "pin"}, status=st)
    resp = web.json_response({"ok": True})
    resp.set_cookie(SESSION_COOKIE, session_key(), max_age=400 * 86400, path="/",
                    secure=True, httponly=True, samesite="Strict")
    return resp


@web.middleware
async def local_only(req, handler):
    """Só atende a rede local (e o cabo USB, que chega como 127.0.0.1): nunca a internet."""
    if not _is_local_ip(req.remote or ""):
        print(f"[rede] recusado: {req.remote} não é da rede local")
        return web.Response(status=403, text="Phone Mouse: só aceita conexões da rede local.")
    return await handler(req)


def build_app() -> web.Application:
    app = web.Application(middlewares=[local_only])
    app.router.add_get("/", index)
    app.router.add_post("/pair", pair)
    app.router.add_get("/ws", ws_handler)
    app.router.add_get("/info", info)
    app.router.add_get("/manifest.json", manifest)
    app.router.add_get("/icon.png", icon)
    app.router.add_get("/ca", ca_page)
    app.router.add_get("/ca.crt", ca_crt)
    app.router.add_get("/ca.mobileconfig", ca_mobileconfig)
    app.router.add_post("/upload", upload)
    app.router.add_post("/share", share)
    app.router.add_get("/files", files_list)
    app.router.add_get("/files/{fid}", file_get)

    async def start_bg(app):
        loop_ref["loop"] = asyncio.get_running_loop()
        app["adb"] = asyncio.create_task(adb_reverse_loop())

    app.on_startup.append(start_bg)
    return app


_ssl = {}


def ssl_ctx() -> ssl.SSLContext:
    if "ctx" not in _ssl:
        ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        ctx.load_cert_chain(CERT, KEY)
        _ssl["ctx"] = ctx
    return _ssl["ctx"]


def reload_cert() -> None:
    """Após troca de rede: renova o certificado se preciso; novas conexões já usam o novo."""
    if ensure_cert(local_ips()) and "ctx" in _ssl:
        _ssl["ctx"].load_cert_chain(CERT, KEY)


def print_banner(ips):
    print("\nPhone Mouse rodando.")
    print(" Wi-Fi (mesma rede):")
    for ip in ips:
        print(f"   https://{ip}:{PORT}")
    if ADB:
        print(f" Cabo USB (Android, depuração USB ligada):\n   https://localhost:{PORT}")
    else:
        print(" Cabo USB: adb não encontrado (instale com: winget install Google.PlatformTools)")
    print(f" PIN de acesso: {current_pin()}")
    print("Aceite o aviso de certificado (é autoassinado).\n")


# ---------------------------------------------------------------- modos de execução
def run_console():
    ips = local_ips()
    print_banner(ips)
    threading.Thread(target=send_notification, daemon=True).start()
    threading.Thread(target=watch_network, args=(handle_network_change,), daemon=True).start()
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

    def pick_and_share():
        def job():
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            paths = filedialog.askopenfilenames(title="Enviar para o celular")
            root.destroy()
            share_paths(paths)
        threading.Thread(target=job, daemon=True).start()

    def new_pin_from_tray():
        pin = regenerate_pin()
        tray.update_menu()
        tray.notify(f"Novo PIN: {pin}. Os celulares vão pedir o PIN de novo.", "Phone Mouse")

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
        pystray.MenuItem(lambda _: f"Endereço: https://{primary_ip() or '?'}:{PORT}", None, enabled=False),
        pystray.MenuItem(lambda _: f"PIN: {current_pin()}", None, enabled=False),
        pystray.MenuItem(lambda _: "Cabo: conectado" if usb_state["device"] else
                         ("Cabo: sem celular" if ADB else "Cabo: adb não instalado"), None, enabled=False),
        pystray.MenuItem("Modo administrador: ativo" if is_admin() else
                         "Modo administrador: desligado", None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Enviar link para o celular", lambda: notify_bg(), default=True),
        pystray.MenuItem("Enviar arquivo para o celular…", lambda: pick_and_share()),
        pystray.MenuItem("Abrir arquivos recebidos", lambda: (RECEIVED_DIR.mkdir(parents=True, exist_ok=True),
                                                             subprocess.Popen(["explorer.exe", str(RECEIVED_DIR)]))),
        pystray.MenuItem("Mostrar QR do endereço", lambda: open_address_page()),
        pystray.MenuItem("Tirar aviso de \"site perigoso\" no celular…", lambda: open_trust_page()),
        pystray.MenuItem("Gerar novo PIN (desconecta os celulares)", lambda: new_pin_from_tray()),
        pystray.MenuItem("Configurar notificação no celular", lambda: open_notification_setup()),
        pystray.MenuItem("Ativar modo administrador (jogos e apps admin)", lambda: install_admin(),
                         visible=not is_admin()),
        pystray.MenuItem("Iniciar com o Windows", toggle_startup, checked=lambda _: STARTUP_LNK.exists()),
        pystray.MenuItem("Sair", quit_app),
    )
    tray = pystray.Icon("phone-mouse", Image.open(ICON_PNG), "Phone Mouse", menu)
    events["toast"] = lambda m: tray.notify(m, "Phone Mouse")
    threading.Thread(target=ensure_sendto, daemon=True).start()
    notify_bg(wait=True)
    threading.Thread(target=watch_network, daemon=True,
                     args=(lambda o, n: handle_network_change(o, n, lambda m: tray.notify(m, "Phone Mouse")),)).start()
    cfg = load_config()
    if not cfg.get("setup_shown"):   # primeira vez neste PC: mostra como assinar a notificação
        cfg["setup_shown"] = True
        CONFIG.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        def first_run():
            time.sleep(2)   # deixa o servidor subir antes de abrir as páginas
            open_address_page("Primeira vez: aponte a câmera do celular para o QR code (ele já leva o PIN).")
            time.sleep(1)
            open_notification_setup()
        threading.Thread(target=first_run, daemon=True).start()
    tray.run()


def print_url_qr() -> None:
    """Mostra no terminal um QR code com o endereço: o celular abre o controle pela câmera."""
    import qrcode
    ip = primary_ip()
    if not ip:
        print("Sem rede: conecte o PC ao Wi-Fi/cabo e tente de novo.")
        return
    url = f"https://{ip}:{PORT}"
    qr = qrcode.QRCode(border=2)
    qr.add_data(pin_url(url))   # o QR já leva o PIN: escaneou, pareou
    try:
        qr.print_ascii(invert=True)
    except UnicodeEncodeError:
        pass   # console sem UTF-8: fica só o endereço escrito
    print(f"\n  Aponte a câmera do celular para o QR code ou digite no navegador:\n\n      {url}"
          f"\n\n  PIN de acesso: {current_pin()}\n")


def set_autostart(on: bool) -> None:
    if on:
        make_shortcut(STARTUP_LNK)
    elif STARTUP_LNK.exists():
        STARTUP_LNK.unlink()
    print("Iniciar com o Windows:", "ligado" if on else "desligado")


def main():
    load_config()
    ensure_icons()
    if "--make-desktop-shortcut" in sys.argv:
        make_shortcut(desktop_dir() / "Phone Mouse.lnk")
        print(f"Atalho criado em {desktop_dir()}")
        return
    if "--stop" in sys.argv:   # usado pelo instalador antes de atualizar os arquivos
        subprocess.run([SCHTASKS, "/end", "/tn", TASK], capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
        _stop_server()
        return
    if "--uninstall" in sys.argv or "--uninstall-admin" in sys.argv:
        uninstall(admin_part="--uninstall-admin" in sys.argv)
        return
    if "--send" in sys.argv:
        send_cli(sys.argv[sys.argv.index("--send") + 1:])
        return
    if "--pin" in sys.argv:
        print("PIN de acesso:", load_config()["pin"])
        return
    if "--new-pin" in sys.argv:
        cfg = load_config(); cfg["pin"] = new_pin(); save_config(cfg)
        print("Novo PIN:", cfg["pin"], "(reinicie o Phone Mouse se estiver rodando)")
        return
    if "--print-url" in sys.argv:
        print_url_qr()
        return
    if "--autostart" in sys.argv:
        i = sys.argv.index("--autostart")
        set_autostart(len(sys.argv) > i + 1 and sys.argv[i + 1].lower() in ("on", "sim", "1"))
        return
    if "--setup-notification" in sys.argv:
        open_notification_setup()
        return
    if "--install-admin" in sys.argv:
        install_admin()
        return
    if already_running():
        # clicou de novo no atalho: só reenvia o link para o celular
        print("Já está rodando; reenviando notificação.")
        send_notification()
        return
    if "--console" not in sys.argv and task_exists() and not is_admin():
        # modo administrador instalado: qualquer atalho (Menu Iniciar, etc.) abre pela tarefa, já como admin
        subprocess.run([SCHTASKS, "/run", "/tn", TASK], capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
        return
    ensure_cert(local_ips())
    if "--console" in sys.argv:
        run_console()
    else:
        run_tray()


if __name__ == "__main__":
    main()
