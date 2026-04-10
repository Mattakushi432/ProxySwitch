import base64
import fnmatch
import ipaddress
import platform
import re
import select
import socket
import struct
import subprocess
import sys
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from .config import LOCAL_PROXY_PORT, logger

if platform.system() == "Windows":
    import ctypes  # type: ignore
    import winreg  # type: ignore
else:
    ctypes = None  # type: ignore
    winreg = None  # type: ignore


def match_pattern(target: str, pattern: str) -> bool:
    pattern = pattern.strip()
    if not pattern:
        return False
    if "/" in pattern:
        try:
            net = ipaddress.ip_network(pattern, strict=False)
            addr = ipaddress.ip_address(target)
            return addr in net
        except ValueError:
            pass
    return fnmatch.fnmatch(target.lower(), pattern.lower())


def route_target(host: str, rules: List[Dict[str, str]]) -> str:
    for rule in rules:
        if match_pattern(host, rule.get("pattern", "")):
            return rule.get("action", "proxy")
    return "proxy"


class RoutingProxy:
    def __init__(self, profile: Dict[str, Any]) -> None:
        self.profile: Dict[str, Any] = profile
        self._server: Optional[socket.socket] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._started_evt = threading.Event()
        self._start_error: Optional[str] = None

    def start(self, timeout: float = 2.0) -> None:
        if self._running:
            self.stop()
        self._started_evt.clear()
        self._start_error = None
        self._running = True
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()
        if not self._started_evt.wait(timeout):
            self._running = False
            raise RuntimeError("Локальный routing-прокси не стартовал вовремя")
        if self._start_error:
            self._running = False
            raise RuntimeError(self._start_error)

    def stop(self) -> None:
        self._running = False
        try:
            if self._server:
                self._server.close()
        except Exception:
            pass
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.5)
        self._server = None

    def _serve(self) -> None:
        try:
            self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._server.bind(("127.0.0.1", LOCAL_PROXY_PORT))
            self._server.listen(64)
            self._server.settimeout(1.0)
            self._started_evt.set()
            while self._running:
                try:
                    conn, _ = self._server.accept()
                    threading.Thread(target=self._handle, args=(conn,), daemon=True).start()
                except socket.timeout:
                    continue
                except OSError as e:
                    if self._running:
                        logger.error(f"Routing proxy accept failed: {e}")
                    break
        except Exception:
            self._start_error = f"Не удалось запустить routing-прокси: {sys.exc_info()[1]}"
            logger.exception("Routing proxy start failed")
            self._started_evt.set()
        finally:
            if not self._started_evt.is_set():
                self._started_evt.set()
            if self._server:
                try:
                    self._server.close()
                except Exception:
                    pass
                self._server = None

    def _handle(self, client: socket.socket) -> None:
        upstream: Optional[socket.socket] = None
        try:
            client.settimeout(15)
            data = b""
            while b"\r\n\r\n" not in data:
                chunk = client.recv(4096)
                if not chunk:
                    return
                data += chunk

            hdr_end = data.index(b"\r\n\r\n")
            hdr_raw = data[:hdr_end].decode("utf-8", errors="replace")

            first = hdr_raw.split("\r\n")[0].split()
            if len(first) < 2:
                logger.debug("Invalid client request line (too short)")
                return
            method, target = first[0], first[1]

            if method.upper() == "CONNECT":
                try:
                    host, port = target.rsplit(":", 1)
                    port = int(port)
                except (ValueError, IndexError):
                    logger.debug(f"Invalid CONNECT target from client: {target!r}")
                    client.send(b"HTTP/1.1 400 Bad Request\r\n\r\n")
                    return
            else:
                m = re.match(r"https?://([^/:]+)(?::(\d+))?", target)
                if not m:
                    logger.debug(f"Invalid HTTP target from client: {target!r}")
                    client.send(b"HTTP/1.1 400 Bad Request\r\n\r\n")
                    return
                host = m.group(1)
                port = int(m.group(2)) if m.group(2) else 80

            action = route_target(host, self.profile.get("rules", []))
            upstream = self._connect_direct(host, port) if action == "direct" else self._connect_upstream(host, port)
            if upstream is None:
                logger.warning(
                    f"Failed to open upstream connection for {method.upper()} {host}:{port} "
                    f"(action={action}, profile={self.profile.get('name', 'unknown')})"
                )
                client.send(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
                return

            if method.upper() == "CONNECT":
                client.send(b"HTTP/1.1 200 Connection established\r\n\r\n")
            else:
                upstream.send(data)

            self._tunnel(client, upstream)
        except Exception:
            logger.exception("Unexpected error while handling client connection")
        finally:
            try:
                client.close()
            except Exception:
                pass
            if upstream:
                try:
                    upstream.close()
                except Exception:
                    pass

    def _connect_direct(self, host: str, port: int) -> Optional[socket.socket]:
        try:
            return socket.create_connection((host, port), timeout=10)
        except Exception as e:
            logger.debug(f"Direct connection to {host}:{port} failed: {e}")
            return None

    def _connect_upstream(self, host: str, port: int) -> Optional[socket.socket]:
        p = self.profile
        ptype = p.get("type", "HTTP")
        phost = p.get("host", "")
        pport = int(p.get("port", 8080))
        user = p.get("username", "")
        pwd = p.get("password", "")
        try:
            if ptype == "SOCKS5":
                return self._socks5_connect(phost, pport, host, port, user, pwd)
            s = socket.create_connection((phost, pport), timeout=10)
            req = f"CONNECT {host}:{port} HTTP/1.1\r\nHost: {host}:{port}\r\n"
            if user:
                cred = base64.b64encode(f"{user}:{pwd}".encode()).decode()
                req += f"Proxy-Authorization: Basic {cred}\r\n"
            req += "\r\n"
            s.send(req.encode())
            resp = b""
            while b"\r\n\r\n" not in resp:
                chunk = s.recv(4096)
                if not chunk:
                    logger.debug(f"Upstream {phost}:{pport} closed during CONNECT handshake for {host}:{port}")
                    s.close()
                    return None
                resp += chunk
            status_line = resp.split(b"\r\n")[0]
            if b"200" not in status_line:
                logger.warning(
                    "Upstream proxy rejected CONNECT %s:%s via %s:%s, response=%s",
                    host,
                    port,
                    phost,
                    pport,
                    status_line.decode("utf-8", errors="replace"),
                )
                s.close()
                return None
            return s
        except Exception as e:
            logger.warning(f"Upstream connection to {phost}:{pport} failed for target {host}:{port}: {e}")
            return None

    def _socks5_connect(
        self,
        phost: str,
        pport: int,
        host: str,
        port: int,
        user: str,
        pwd: str,
    ) -> Optional[socket.socket]:
        try:
            s = socket.create_connection((phost, pport), timeout=10)
            s.send(b"\x05\x02\x00\x02" if user else b"\x05\x01\x00")
            resp = s.recv(2)
            if len(resp) < 2 or resp[0] != 5 or resp[1] == 0xFF:
                s.close()
                raise Exception("SOCKS5 handshake failed")
            if resp[1] == 0x02:
                auth = bytes([1, len(user)]) + user.encode() + bytes([len(pwd)]) + pwd.encode()
                s.send(auth)
                ar = s.recv(2)
                if len(ar) < 2 or ar[1] != 0:
                    s.close()
                    raise Exception("SOCKS5 auth failed")
            try:
                addr = socket.inet_aton(host)
                req = b"\x05\x01\x00\x01" + addr + struct.pack(">H", port)
            except OSError:
                enc = host.encode()
                req = b"\x05\x01\x00\x03" + bytes([len(enc)]) + enc + struct.pack(">H", port)
            s.send(req)
            resp = s.recv(10)
            if len(resp) < 2 or resp[1] != 0:
                s.close()
                raise Exception(f"SOCKS5 request failed: {resp[1] if len(resp) >= 2 else 'no response'}")
            return s
        except Exception as e:
            logger.debug(f"SOCKS5 connection to {phost}:{pport} failed: {e}")
            return None

    def _tunnel(self, a: socket.socket, b: socket.socket) -> None:
        a.settimeout(0)
        b.settimeout(0)
        try:
            while True:
                r, _, _ = select.select([a, b], [], [], 30)
                if not r:
                    break
                for src, dst in [(a, b), (b, a)]:
                    if src in r:
                        try:
                            data = src.recv(65536)
                            if not data:
                                return
                            dst.sendall(data)
                        except Exception:
                            return
        finally:
            try:
                b.close()
            except Exception:
                pass


def _is_windows() -> bool:
    return platform.system() == "Windows"


def _is_mac() -> bool:
    return platform.system() == "Darwin"


def set_system_proxy_to_local(direct_patterns: Optional[List[str]] = None) -> Tuple[bool, str]:
    host = "127.0.0.1"
    port = LOCAL_PROXY_PORT
    bypass = direct_patterns or []
    try:
        if _is_windows():
            return _win_set(host, port, bypass)
        if _is_mac():
            return _mac_set(host, port)
        return _env_set(host, port)
    except Exception as e:
        logger.exception("Error setting system proxy")
        return False, str(e)


def clear_system_proxy() -> Tuple[bool, str]:
    try:
        if _is_windows():
            return _win_clear()
        if _is_mac():
            return _mac_clear()
        return _env_clear()
    except Exception as e:
        logger.exception("Error clearing system proxy")
        return False, str(e)


def _win_set(host: str, port: int, bypass: List[str]) -> Tuple[bool, str]:
    try:
        kp = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, kp, 0, winreg.KEY_WRITE)
        default_bp = ["localhost", "127.*", "<local>"]
        all_bp = list(dict.fromkeys(default_bp + bypass))
        winreg.SetValueEx(key, "ProxyServer", 0, winreg.REG_SZ, f"{host}:{port}")
        winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(key, "ProxyOverride", 0, winreg.REG_SZ, ";".join(all_bp))  # type: ignore
        winreg.CloseKey(key)
        _win_refresh()
        logger.info(f"Windows proxy set to {host}:{port}")
        return True, f"Системный прокси -> 127.0.0.1:{port}"
    except Exception as e:
        logger.exception("Error setting Windows proxy")
        return False, str(e)


def _win_clear() -> Tuple[bool, str]:
    try:
        kp = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, kp, 0, winreg.KEY_WRITE)
        winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 0)
        winreg.CloseKey(key)
        _win_refresh()
        logger.info("Windows proxy cleared")
        return True, "Системный прокси отключён."
    except Exception as e:
        logger.exception("Error clearing Windows proxy")
        return False, str(e)


def _win_refresh() -> None:
    try:
        wi = ctypes.windll.Wininet
        wi.InternetSetOptionW(0, 39, 0, 0)
        wi.InternetSetOptionW(0, 37, 0, 0)
    except Exception:
        pass


def _mac_services() -> List[str]:
    try:
        out = subprocess.check_output(["networksetup", "-listallnetworkservices"], text=True)
        services = []
        for line in out.splitlines():
            line = line.strip()
            if line and not line.startswith("*") and "asterisk" not in line.lower():
                services.append(line)
        if services:
            logger.debug(f"Found network services: {services}")
            return services
    except Exception as e:
        logger.warning(f"Error listing network services: {e}")
    return []


def _run_networksetup(cmd: List[str]) -> Tuple[bool, str]:
    result = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if result.returncode == 0:
        return True, ""
    msg = (result.stderr or result.stdout).strip() or f"exit code {result.returncode}"
    logger.warning(f"networksetup failed ({' '.join(cmd)}): {msg}")
    return False, msg


def _mac_set(host: str, port: int) -> Tuple[bool, str]:
    try:
        services = _mac_services()
        if not services:
            return False, "Не найдено ни одного network service для настройки прокси."
        ok_count = 0
        errors: List[str] = []
        for svc in services:
            svc_ok = True
            for cmd in [
                ["networksetup", "-setwebproxy", svc, host, str(port)],
                ["networksetup", "-setwebproxystate", svc, "on"],
                ["networksetup", "-setsecurewebproxy", svc, host, str(port)],
                ["networksetup", "-setsecurewebproxystate", svc, "on"],
            ]:
                ok, err = _run_networksetup(cmd)
                if not ok:
                    svc_ok = False
                    errors.append(f"{svc}: {err}")
            if svc_ok:
                ok_count += 1
        if ok_count == 0:
            return False, "Не удалось применить прокси ни к одному network service."
        if errors:
            logger.warning(f"macOS proxy partially applied: {errors}")
        logger.info(f"macOS proxy set to {host}:{port} on {ok_count}/{len(services)} services")
        return True, f"macOS прокси -> {host}:{port} ({ok_count}/{len(services)} сервисов)"
    except Exception as e:
        logger.exception("Error setting macOS proxy")
        return False, str(e)


def _mac_clear() -> Tuple[bool, str]:
    try:
        services = _mac_services()
        if not services:
            return False, "Не найдено ни одного network service для отключения прокси."
        ok_count = 0
        for svc in services:
            svc_ok = True
            for cmd in [
                ["networksetup", "-setwebproxystate", svc, "off"],
                ["networksetup", "-setsecurewebproxystate", svc, "off"],
                ["networksetup", "-setsocksfirewallproxystate", svc, "off"],
            ]:
                ok, _ = _run_networksetup(cmd)
                if not ok:
                    svc_ok = False
            if svc_ok:
                ok_count += 1
        if ok_count == 0:
            return False, "Не удалось отключить прокси ни в одном network service."
        logger.info("macOS proxy cleared")
        return True, "Системный прокси отключён."
    except Exception as e:
        logger.exception("Error clearing macOS proxy")
        return False, str(e)


def _env_set(host: str, port: int) -> Tuple[bool, str]:
    try:
        import os

        val = f"http://{host}:{port}"
        for v in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"):
            os.environ[v] = val
        logger.info(f"Environment proxy set to {val}")
        return True, f"ENV прокси -> {val}"
    except Exception as e:
        logger.exception("Error setting environment proxy")
        return False, str(e)


def _env_clear() -> Tuple[bool, str]:
    try:
        import os

        for v in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"):
            os.environ.pop(v, None)
        logger.info("Environment proxy cleared")
        return True, "ENV прокси очищен."
    except Exception as e:
        logger.exception("Error clearing environment proxy")
        return False, str(e)


def test_proxy(profile: Dict[str, Any], timeout: int = 6) -> Tuple[bool, float, str]:
    ptype = profile.get("type", "HTTP")
    host = profile.get("host", "")
    port = int(profile.get("port", 8080))
    user = profile.get("username", "")
    pwd = profile.get("password", "")
    start = time.time()
    s = None
    try:
        if ptype == "SOCKS5":
            try:
                import socks as pysocks
            except ImportError:
                logger.error("PySocks not installed for SOCKS5 testing")
                return False, 0.0, "PySocks не установлен"
            s = pysocks.socksocket()
            if user:
                s.set_proxy(pysocks.SOCKS5, host, port, True, user, pwd)
            else:
                s.set_proxy(pysocks.SOCKS5, host, port)
            s.settimeout(timeout)
            s.connect(("1.1.1.1", 80))
        else:
            s = socket.create_connection((host, port), timeout=timeout)
            req = "CONNECT 1.1.1.1:80 HTTP/1.1\r\nHost: 1.1.1.1\r\n"
            if user:
                cred = base64.b64encode(f"{user}:{pwd}".encode()).decode()
                req += f"Proxy-Authorization: Basic {cred}\r\n"
            req += "\r\n"
            s.send(req.encode())
            s.settimeout(timeout)
            resp = s.recv(256)
            if b"200" not in resp:
                status_line = resp.split(b"\r\n", 1)[0].decode("utf-8", errors="replace")
                reason = f"прокси вернул неуспешный ответ: {status_line}"
                logger.warning(f"Proxy test failed for {host}:{port}: {reason}")
                return False, 0.0, reason
        logger.info(f"Proxy test successful for {host}:{port}")
        return True, round((time.time() - start) * 1000, 1), ""
    except Exception as e:
        logger.warning(f"Proxy test failed for {host}:{port}: {type(e).__name__}: {e}")
        return False, 0.0, f"{type(e).__name__}: {e}"
    finally:
        if s:
            try:
                s.close()
            except Exception:
                pass


def test_local_proxy(timeout: int = 6) -> Tuple[bool, float, str]:
    start = time.time()
    s: Optional[socket.socket] = None
    try:
        s = socket.create_connection(("127.0.0.1", LOCAL_PROXY_PORT), timeout=timeout)
        req = "CONNECT 1.1.1.1:80 HTTP/1.1\r\nHost: 1.1.1.1\r\n\r\n"
        s.sendall(req.encode())
        s.settimeout(timeout)
        resp = s.recv(512)
        if b"200" not in resp.split(b"\r\n", 1)[0]:
            first = resp.split(b"\r\n", 1)[0].decode("utf-8", errors="replace")
            return False, 0.0, f"локальный прокси вернул: {first}"
        return True, round((time.time() - start) * 1000, 1), ""
    except Exception as e:
        return False, 0.0, str(e)
    finally:
        if s:
            try:
                s.close()
            except Exception:
                pass
