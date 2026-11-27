"""Calling her from your phone on the same Wi-Fi as this Mac (travel stays off). A phone's browser gives a page its
microphone only over https, and reaches LiveKit only over wss, so while calling from the phone is on this Mac opens two
secure doors under its own name on your network, with Viventium's own certificate for that name, which the phone trusts
once (call/ui/app/pair: the certificate, then a code shown on this Mac):

    the page   https://<this Mac>.local:3443  ->  the call page on this computer (127.0.0.1:3400)
    the call   wss://<this Mac>.local:7443    ->  LiveKit's signal on this computer (127.0.0.1:7880); the sound itself goes
                                                   straight to LiveKit on this Mac's address on your network, never here

The doors open on this Mac's address on your network alone, answer only devices on it (private or link-local
addresses), and only on the network calling from the phone was turned on in (its router): anywhere else they stay shut.

The page door reads each request. One for any other address than the phone's (a Host naming this computer, say) is
refused, and every one it carries has this start's door pass (X-Viventium-Door; kept in her state, his alone), by which
the page knows it came from the network: never "this computer" (call/ui/app/api/settings/carry.ts), and the call's
routes only for a phone paired with a code shown on this Mac. The call door carries bytes: LiveKit checks every call's
token itself. With calling from the phone off, LiveKit offers only this computer's own address (call/livekit.yaml).

The certificate: a root of Viventium's own that may sign only for this Mac's exact name, no name under it and never an
address (name constraints), and the doors' certificate it signs (800 days, as Apple accepts). The root's key signs that once and is
gone: it is never kept, so nothing can sign another name with it, nor take it in a backup. The doors' key stays in her
state, his alone. His Mac shows the root's fingerprint, for the phone to check once before it trusts it.

    python -m call.phone address       this Mac's name and address on your network, and its router (JSON)
    python -m call.phone certificate   the certificate for its name, made once and again when the name changes
    python -m call.phone livekit       LiveKit's settings with the phone's sound on your network; prints the file
    python -m call.phone moved         exit 0 when this Mac's address is no longer the one LiveKit's settings name
    python -m call.phone doors         the two doors (./vx runs them while calling from the phone is on)
"""
import asyncio
import calendar
import hashlib
import http.client
import http.server
import ipaddress
import json
import logging
import os
import re
import secrets
import shutil
import socket
import socketserver
import ssl
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

from core.state import STATE_ROOT, private_dir, private_file

log = logging.getLogger("phone")
ROOT = Path(__file__).resolve().parents[1]
HOME = STATE_ROOT / "core" / "phone"
PASS = HOME / "door-pass"  # (this start's door pass: the page reads it, app/api/settings/carry.ts)
DOORS = {"page": (3443, 3400), "call": (7443, 7880)}  # door: (its port, the port on this computer it leads to)
DAYS = 800  # the doors' certificate (Apple accepts a server certificate of at most 825 days)
ROOT_DAYS = 3650
MARK = "X-Viventium-Door"
# Never carried from the phone to the page: how one connection is held (the door holds its own), and anything that would
# say where a request came from (only the door says that, with its pass).
HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "proxy-connection", "te", "trailer",
       "transfer-encoding", "upgrade", "expect"}
UNSAID = HOP | {MARK.lower(), "forwarded", "x-forwarded-for", "x-forwarded-host", "x-forwarded-proto", "x-forwarded-port",
                "x-real-ip"}
LONGEST = 1 << 20  # (a phone sends the page a code or a call's settings: never more than this)
LOOK = 20  # seconds between looks at the network


def _openssl() -> str:
    """macOS's own (LibreSSL, on every Mac), else whichever is on the PATH."""
    return "/usr/bin/openssl" if os.access("/usr/bin/openssl", os.X_OK) else shutil.which("openssl") or "openssl"


def lan_ip() -> str:
    """This Mac's address on your network now (the one a packet out would leave from; nothing is sent), or "" when it
    has none that a phone on the same Wi-Fi could reach (no network, or only this computer's own)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("10.255.255.255", 9))
            ip = probe.getsockname()[0]
    except OSError:
        return ""
    address = ipaddress.ip_address(ip)
    return ip if address.is_private and not address.is_loopback else ""


def network() -> str:
    """Which network this Mac is on now, by its router: a short hash of the router's hardware address (read from this
    Mac's own tables; nothing is sent), the same at home every day and another in a café. "" when it cannot be told."""
    def said(*command: str) -> str:
        try:
            return subprocess.run(command, capture_output=True, text=True, timeout=5).stdout
        except (OSError, subprocess.TimeoutExpired):
            return ""
    gateway = re.search(r"gateway:\s*(\S+)", said("/sbin/route", "-n", "get", "default"))
    hardware = gateway and re.search(r" at ((?:[0-9a-f]{1,2}:){5}[0-9a-f]{1,2}) ", said("/usr/sbin/arp", "-n", gateway.group(1)))
    return hashlib.sha256(hardware.group(1).encode()).hexdigest()[:16] if hardware else ""


def address() -> dict:
    """This Mac's name on your network (its Bonjour name, as Sharing shows it), its address and network now, with the
    two doors."""
    try:
        name = subprocess.run(["scutil", "--get", "LocalHostName"], capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        name = ""
    name = name or socket.gethostname().split(".")[0]
    host = f"{name}.local".lower()
    return {"name": name, "host": host, "ip": lan_ip(), "network": network(), "page": f"https://{host}:{DOORS['page'][0]}",
            "call": f"wss://{host}:{DOORS['call'][0]}"}


# -- The certificate --

def _run(*args: str, cwd: Path) -> None:
    done = subprocess.run([_openssl(), *args], cwd=cwd, capture_output=True, text=True, timeout=60, umask=0o077)
    if done.returncode:
        raise RuntimeError(f"openssl {args[0]} did not make it: {done.stderr.strip()[-300:]}")


def _expires(cert: Path) -> float:
    """When a certificate stops being valid (seconds since the epoch), 0 when it cannot be read."""
    done = subprocess.run([_openssl(), "x509", "-noout", "-enddate", "-in", str(cert)], capture_output=True, text=True, timeout=20)
    try:  # ("notAfter=<month> <day> 08:00:00 2028 GMT")
        return float(calendar.timegm(time.strptime(done.stdout.strip().split("=", 1)[1], "%b %d %H:%M:%S %Y GMT")))
    except (IndexError, ValueError):
        return 0.0


MADE = 2  # (which rule the root was made under: 2 also excludes every name under this Mac's; an older root is made again)


def root_settings(name: str, host: str) -> str:
    """OpenSSL's settings for Viventium's root: a CA for one level, that may sign only for this exact name (no name under
    it: .<name> excluded) and never for an address of any kind (the phone reaches the doors by name)."""
    allowed = (f"permitted;DNS:{host},excluded;DNS:.{host},"
               "excluded;IP:0.0.0.0/0.0.0.0,excluded;IP:0:0:0:0:0:0:0:0/0:0:0:0:0:0:0:0")
    return ("[req]\ndistinguished_name = dn\nprompt = no\nx509_extensions = ext\n"
            f"[dn]\nCN = Viventium on {name}\nO = Viventium AI\n"
            "[ext]\nbasicConstraints = critical,CA:TRUE,pathlen:0\nkeyUsage = critical,keyCertSign,cRLSign\n"
            f"subjectKeyIdentifier = hash\nnameConstraints = critical,{allowed}\n")


def certificate(where: dict | None = None, force: bool = False) -> Path:
    """The folder with Viventium's root (root.crt, for the phone to trust) and the doors' certificate chain (doors.crt)
    and key, made once; made again, with a new root (the phone trusts it once more), when this Mac's name changed, when
    the root was made under an older rule (MADE), or within 30 days of the doors' certificate's end. The root's key is made in a temporary folder, signs the doors'
    certificate there and is deleted with it."""
    where = where or address()
    folder = private_dir(HOME)
    kept = folder / "for.json"
    try:
        made = json.loads(kept.read_text())
    except (OSError, ValueError):
        made = {}
    (folder / "root.key").unlink(missing_ok=True)  # (an earlier build kept the root's key: never again)
    fresh = (folder / "doors.crt").exists() and _expires(folder / "doors.crt") - time.time() > 30 * 86400
    if not force and made == {"host": where["host"], "made": MADE} and fresh and (folder / "doors.key").exists() \
            and (folder / "root.crt").exists():
        return folder
    host = where["host"]
    with tempfile.TemporaryDirectory(dir=folder, prefix=".making-") as work:
        work = Path(work)
        (work / "root.cnf").write_text(root_settings(where["name"], host))
        _run("req", "-x509", "-new", "-newkey", "rsa:2048", "-nodes", "-sha256", "-days", str(ROOT_DAYS), "-config", "root.cnf",
             "-keyout", "root.key", "-out", "root.crt", cwd=work)
        (work / "doors.cnf").write_text(
            "[req]\ndistinguished_name = dn\nprompt = no\n"
            f"[dn]\nCN = {host}\n"
            "[ext]\nbasicConstraints = critical,CA:FALSE\nkeyUsage = critical,digitalSignature,keyEncipherment\n"
            f"extendedKeyUsage = serverAuth\nsubjectAltName = DNS:{host}\nauthorityKeyIdentifier = keyid\n")
        _run("req", "-new", "-newkey", "rsa:2048", "-nodes", "-sha256", "-config", "doors.cnf", "-keyout", "doors.key",
             "-out", "doors.csr", cwd=work)
        _run("x509", "-req", "-in", "doors.csr", "-CA", "root.crt", "-CAkey", "root.key", "-set_serial",
             str(int.from_bytes(os.urandom(8), "big")), "-sha256", "-days", str(DAYS), "-extfile", "doors.cnf", "-extensions", "ext",
             "-out", "leaf.crt", cwd=work)
        (work / "root.key").unlink()  # (it signed the doors' certificate: nothing else, ever)
        (work / "doors.crt").write_text((work / "leaf.crt").read_text() + (work / "root.crt").read_text())  # (the chain)
        for name in ("root.crt", "doors.crt", "doors.key"):
            os.chmod(work / name, 0o600)
            os.replace(work / name, folder / name)
    with private_file(kept) as out:
        json.dump({"host": host, "made": MADE}, out)
    return folder


def fingerprint(folder: Path | None = None) -> str:
    """The root's SHA-256 fingerprint as a phone shows it before it trusts it (pairs of hex digits), "" with none."""
    try:
        der = ssl.PEM_cert_to_DER_cert(((folder or HOME) / "root.crt").read_text())
    except (OSError, ValueError):
        return ""
    digest = hashlib.sha256(der).hexdigest().upper()
    return " ".join(digest[i:i + 2] for i in range(0, len(digest), 2))


# -- LiveKit, with the phone's sound on your network --

def livekit(where: dict | None = None) -> Path:
    """LiveKit's own settings (call/livekit.yaml) with this Mac's address on your network beside its own: the phone's
    sound goes there, over UDP (TCP when UDP cannot). Its signal still answers this computer only (the call door
    carries the phone's). The file written, in her state."""
    import yaml
    where = where or address()
    config = yaml.safe_load((ROOT / "call" / "livekit.yaml").read_text())
    rtc = config.setdefault("rtc", {})
    rtc["tcp_port"] = 7881
    rtc["ips"] = {"includes": ["127.0.0.1/32", *([f"{where['ip']}/32"] if where.get("ip") else [])]}
    path = private_dir(HOME) / "livekit.yaml"
    with private_file(path) as out:
        out.write("# Made by call/phone.py while calling from the phone is on: call/livekit.yaml, with the phone's sound on\n"
                  "# this Mac's address on your network.\n" + yaml.safe_dump(config, sort_keys=False))
    return path


def moved(ip: str | None = None) -> bool:
    """Whether this Mac's address on your network is no longer the one LiveKit's settings for the phone name (DHCP gave
    it another): LiveKit then offers the phone's sound where nothing answers, until it starts again with the new one."""
    import yaml
    try:
        offered = yaml.safe_load((HOME / "livekit.yaml").read_text())["rtc"]["ips"]["includes"]
    except (OSError, ValueError, KeyError, TypeError, yaml.YAMLError):
        return False
    now = lan_ip() if ip is None else ip
    return [x for x in offered if x != "127.0.0.1/32"] != ([f"{now}/32"] if now else [])


# -- The two doors --

def nearby(ip: str) -> bool:
    """A device on this Mac's own network (a private or link-local address), or this computer itself."""
    try:
        seen = ipaddress.ip_address(ip.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(seen, ipaddress.IPv6Address) and seen.ipv4_mapped:
        seen = seen.ipv4_mapped
    return seen.is_private or seen.is_link_local or seen.is_loopback


def _new_pass() -> str:
    """This start's door pass, kept for the page in her state (his alone): a request with it came through the door."""
    made = secrets.token_urlsafe(32)
    with private_file(PASS) as out:
        out.write(made)
    return made


class _PageDoor(http.server.BaseHTTPRequestHandler):
    """One connection from the phone to the page door: each request read, checked and carried to the page, with the
    door's pass; the page's answer carried back."""
    protocol_version = "HTTP/1.1"
    timeout = 60  # (a connection idle this long is closed)
    server_version, sys_version = "Viventium", ""

    def log_message(self, *args) -> None:  # (nothing of a request is logged: no address, no path)
        pass

    def _refuse(self, status: int, words: str) -> None:
        body = words.encode()
        self.close_connection = True
        self.send_response_only(status)
        for name, value in (("Content-Type", "text/plain; charset=utf-8"), ("Content-Length", str(len(body))),
                            ("Cache-Control", "no-store"), ("Connection", "close")):
            self.send_header(name, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _carry(self) -> None:
        door = self.server
        hosts = self.headers.get_all("Host") or []
        if not self.path.startswith("/") or len(hosts) != 1:
            return self._refuse(400, "Not a request this door carries.")
        if not door.host or hosts[0].strip().lower() != door.host:
            return self._refuse(421, "Not this address.")
        lengths = self.headers.get_all("Content-Length") or []
        if self.headers.get_all("Transfer-Encoding"):
            return self._refuse(411, "Send its length.")
        try:
            length = int(lengths[0]) if lengths else 0
            if len(lengths) > 1 or length < 0:
                raise ValueError
        except ValueError:
            return self._refuse(400, "Not a request this door carries.")
        if length > LONGEST:
            return self._refuse(413, "That is more than the page takes.")
        body = self.rfile.read(length) if length else b""
        if len(body) != length:
            self.close_connection = True
            return
        named = {n.strip().lower() for n in ",".join(self.headers.get_all("Connection") or []).split(",")}
        page = http.client.HTTPConnection("127.0.0.1", door.to, timeout=120)
        try:
            page.putrequest(self.command, self.path, skip_host=True, skip_accept_encoding=True)
            for name, value in self.headers.items():
                if name.lower() not in UNSAID and name.lower() not in named:
                    page.putheader(name, value)
            page.putheader(MARK, door.door_pass)
            page.endheaders(body or None)
            answer = page.getresponse()
        except (OSError, ValueError, http.client.HTTPException):
            page.close()
            return self._refuse(502, "Viventium's page did not answer.")
        try:
            self.send_response_only(answer.status, answer.reason)
            gone = HOP | {n.strip().lower() for n in ",".join(answer.headers.get_all("Connection") or []).split(",")}
            for name, value in answer.headers.items():
                if name.lower() not in gone:
                    self.send_header(name, value)
            if self.command == "HEAD" or answer.status in (204, 304) or answer.status < 200:
                self.end_headers()
            elif answer.length is not None and not answer.chunked:  # (its length said: carried as it is)
                self.end_headers()
                while chunk := answer.read(1 << 16):
                    self.wfile.write(chunk)
            else:  # (streamed: carried in pieces as they come)
                self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()
                while chunk := answer.read1(1 << 16):
                    self.wfile.write(b"%x\r\n%s\r\n" % (len(chunk), chunk))
                self.wfile.write(b"0\r\n\r\n")
        except (OSError, http.client.HTTPException):
            self.close_connection = True
        finally:
            page.close()

    do_GET = do_HEAD = do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = _carry


class _Doorway(socketserver.ThreadingMixIn, http.server.HTTPServer):
    """The page door: https on one address, a thread per connection (at most 64 at once), devices nearby only."""
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, where: tuple, made: ssl.SSLContext, to: int, host: str, door_pass: str):
        self.made, self.to, self.host, self.door_pass = made, to, host.lower(), door_pass
        self.slots = threading.BoundedSemaphore(64)
        super().__init__(where, _PageDoor)

    def server_bind(self) -> None:  # (HTTPServer's own asks the network for this address's name: never needed here)
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]

    def verify_request(self, request, client_address) -> bool:
        return nearby(client_address[0])

    def process_request(self, request, client_address) -> None:
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:  # noqa: BLE001 (no thread for it: it is closed)
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()

    def finish_request(self, request, client_address) -> None:
        request.settimeout(15)  # (the handshake: a phone that stops halfway is let go)
        try:
            tls = self.made.wrap_socket(request, server_side=True)
        except (OSError, ssl.SSLError):
            return
        try:
            self.RequestHandlerClass(tls, client_address, self)
        except (OSError, ssl.SSLError):
            pass
        finally:
            try:
                tls.close()
            except OSError:
                pass


class _Threaded:
    """The page door as the doors' loop holds them: serve_forever() until close()."""
    def __init__(self, server: _Doorway):
        self.server = server

    async def serve_forever(self) -> None:
        await asyncio.to_thread(self.server.serve_forever, 0.25)

    def close(self) -> None:
        threading.Thread(target=lambda: (self.server.shutdown(), self.server.server_close()), daemon=True).start()


async def _carry(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, to: int) -> None:
    """One connection, through: its bytes to this computer's port and back, as they are, until either side ends."""
    peer = writer.get_extra_info("peername") or ("",)
    if not nearby(str(peer[0])):
        writer.close()
        return
    try:
        far_reader, far_writer = await asyncio.open_connection("127.0.0.1", to)
    except OSError:
        writer.close()
        return

    async def one_way(source: asyncio.StreamReader, sink: asyncio.StreamWriter) -> None:
        try:
            while chunk := await source.read(1 << 16):
                sink.write(chunk)
                await sink.drain()
        except (ConnectionError, OSError, ssl.SSLError, asyncio.IncompleteReadError):
            pass
        finally:
            try:
                sink.close()
            except Exception:  # noqa: BLE001 (already gone)
                pass

    await asyncio.gather(one_way(reader, far_writer), one_way(far_reader, writer))


def context(folder: Path) -> ssl.SSLContext:
    made = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    made.minimum_version = ssl.TLSVersion.TLSv1_2
    made.load_cert_chain(folder / "doors.crt", folder / "doors.key")
    return made


def _page_host() -> str:
    """The one address the page door carries requests for (VX_LAN_ORIGIN's host and port), "" when none is set."""
    try:
        origin = urlparse(os.environ.get("VX_LAN_ORIGIN", ""))
        return f"{origin.hostname}:{origin.port}" if origin.hostname and origin.port not in (None, 443) else origin.hostname or ""
    except ValueError:
        return ""


async def serve(folder: Path, doors: dict | None = None, host: str = "", page_host: str | None = None) -> list:
    """Open the doors on one address of this Mac (host: its address on your network; a test's own 127.0.0.1), the page
    door carrying only requests for page_host (VX_LAN_ORIGIN's when not given: none, so nothing, when that is unset),
    with a new door pass; returns the servers, each with serve_forever() and close()."""
    if not host:
        raise ValueError("the doors open on one address of this Mac, never on every one")
    made = context(folder)
    loop = asyncio.get_running_loop()
    loop.set_exception_handler(lambda _loop, said: log.info("a connection ended: %s", type(said.get("exception")).__name__))
    servers = []
    for door, (port, to) in (doors or DOORS).items():
        if door == "page":
            servers.append(_Threaded(_Doorway((host, port), made, to, _page_host() if page_host is None else page_host, _new_pass())))
        else:
            servers.append(await asyncio.start_server(lambda r, w, to=to: _carry(r, w, to), host=host, port=port, ssl=made,
                                                      ssl_handshake_timeout=15))
        log.info("%s door open on %s, to this computer's %s", door, port, to)
    return servers


def doors_from(env: dict) -> dict:
    """The two doors as this run is set: each opens on the port of the address the phone is given (VX_LAN_ORIGIN,
    VX_LAN_LIVEKIT_URL) and leads to this computer's page (UI_PORT) and LiveKit (LIVEKIT_URL), so a second Light (the
    bench) has doors of its own. Unset, the ones above."""
    def port(url: str, default: int) -> int:
        try:
            return urlparse(url).port or default
        except ValueError:
            return default
    return {"page": (port(env.get("VX_LAN_ORIGIN", ""), DOORS["page"][0]), int(env.get("UI_PORT") or DOORS["page"][1])),
            "call": (port(env.get("VX_LAN_LIVEKIT_URL", ""), DOORS["call"][0]), port(env.get("LIVEKIT_URL", ""), DOORS["call"][1]))}


def at_home(ip: str, seen: str, home: str) -> bool:
    """Whether the doors may open: this Mac has an address on a network, and that network is the one calling from the
    phone was turned on in (home, VX_LAN_NETWORK). One that cannot be told, or none remembered: shut."""
    return bool(ip) and bool(home) and seen == home


async def _doors() -> None:
    """The doors while ./vx runs them: open on this Mac's address on the network calling from the phone was turned on in
    (VX_LAN_NETWORK), shut on any other or with none, and opened again on the new address when the address changes."""
    env = dict(os.environ)
    doors, home = doors_from(env), env.get("VX_LAN_NETWORK", "")
    folder = certificate()
    servers, tasks, at = [], [], ""
    while True:
        ip = lan_ip()
        here = at_home(ip, network() if ip else "", home)
        if servers and (not here or ip != at):
            for server in servers:
                server.close()
            for task in tasks:
                task.cancel()
            servers, tasks, at = [], [], ""
            log.info("doors shut: %s", "a new address" if here else "not the network calling from the phone was turned on in")
        if here and not servers:
            try:
                servers = await serve(folder, doors, ip)
            except OSError as e:
                log.info("the doors did not open: %s", e)
            else:
                tasks, at = [asyncio.ensure_future(server.serve_forever()) for server in servers], ip
        await asyncio.sleep(LOOK)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    action = sys.argv[1] if len(sys.argv) > 1 else ""
    if action == "address":
        print(json.dumps(address()))
    elif action == "certificate":
        print(certificate())
    elif action == "livekit":
        print(livekit())
    elif action == "moved":
        sys.exit(0 if moved() else 1)
    elif action == "doors":
        asyncio.run(_doors())
    else:
        sys.exit("python -m call.phone address | certificate | livekit | moved | doors")
