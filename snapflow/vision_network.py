"""Probe before sending images; optional existing SSH route preserves end-to-end TLS."""
import atexit
import http.client
import os
import shutil
import socket
import ssl
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

BRIDGE_HOST = '100.97.47.4'
GATEWAY_HOST = 'llm-gateway.galbot.com'
SSH_ALIAS = 'ds4090-ts'


class NetworkUnavailable(OSError):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def error_code(exc):
    reason = getattr(exc, 'reason', exc)
    if isinstance(reason, ssl.SSLCertVerificationError): return 'certificate'
    if isinstance(reason, ssl.SSLError): return 'tls'
    if isinstance(reason, (TimeoutError, socket.timeout)): return 'timeout'
    if isinstance(reason, socket.gaierror): return 'dns'
    if isinstance(exc, urllib.error.HTTPError): return 'http_' + str(exc.code)
    return 'connection'


class TunnelHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host, *, tunnel_port, expected_host, **kwargs):
        super().__init__(host, **kwargs)
        if self.host != expected_host or self.port != 443:
            raise NetworkUnavailable('转接目标不匹配。')
        self.tunnel_port = tunnel_port

    def connect(self):
        # The TCP endpoint changes; SNI, Host, CA and hostname validation do not.
        raw = socket.create_connection(('127.0.0.1', self.tunnel_port), self.timeout)
        try:
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
        except Exception:
            raw.close()
            raise


class TunnelHTTPSHandler(urllib.request.HTTPSHandler):
    def __init__(self, port, host):
        super().__init__()
        self.port, self.host = port, host

    def https_open(self, req):
        def connection(host, **kwargs):
            return TunnelHTTPSConnection(host, tunnel_port=self.port, expected_host=self.host, **kwargs)
        return self.do_open(connection, req)


class VisionNetwork:
    def __init__(self, base, allow_bridge=False):
        parsed = urllib.parse.urlsplit(base)
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or
                parsed.password or parsed.query or parsed.fragment):
            raise ValueError('识别服务必须使用 HTTPS 地址。')
        self.base = base.rstrip('/')
        self.origin = (parsed.hostname, parsed.port or 443)
        self.allow_bridge = allow_bridge and self.origin == (GATEWAY_HOST, 443)
        self.lock = threading.RLock()
        self.opener = None
        self.route = ''
        self.attempts = []
        self.process = None
        self.failed_at = None
        atexit.register(self.close)

    def close(self):
        child, self.process = self.process, None
        if child is not None and child.poll() is None:
            child.terminate()
            try: child.wait(timeout=3)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=3)

    def _probe(self, opener, route):
        try:
            with opener.open(self.base + '/models', timeout=4) as response:
                status = response.status
        except urllib.error.HTTPError as exc:
            status = exc.code
            exc.close()
        except (OSError, urllib.error.URLError, http.client.HTTPException) as exc:
            self.attempts.append({'route': route, 'result': error_code(exc)})
            return False
        self.attempts.append({'route': route, 'result': 'http_' + str(status)})
        # Do not route around valid auth / permission responses. Never follow redirects.
        return status in (200, 401, 403, 404, 405, 429)

    def _start_bridge(self):
        ssh = shutil.which('ssh.exe') if os.name == 'nt' else None
        if not ssh:
            raise NetworkUnavailable('未找到已有的 Windows SSH 客户端。')
        flags = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}
        options = ['-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
                   '-o', 'ConnectTimeout=8', '-o', 'ConnectionAttempts=1',
                   '-o', 'ExitOnForwardFailure=yes', '-o', 'ServerAliveInterval=15',
                   '-o', 'ServerAliveCountMax=3', '-o', 'PermitLocalCommand=no',
                   '-o', 'RemoteCommand=none', '-o', 'ForwardAgent=no', '-o', 'ForwardX11=no',
                   '-o', 'ControlMaster=no', '-o', 'ControlPath=none']
        effective = subprocess.run([ssh, '-G', *options, SSH_ALIAS], capture_output=True,
                                   timeout=10, **flags)
        values = dict(line.split(None, 1) for line in effective.stdout.decode('utf-8', 'replace').splitlines() if ' ' in line)
        if effective.returncode or values.get('hostname') != BRIDGE_HOST or values.get('user') != 'lidanshi':
            raise NetworkUnavailable('已有 SSH 连接未指向指定开发机。')
        # Do not overwrite any SSH keys/config, install services or change the firewall.
        with socket.socket() as listener:
            if os.name == 'nt': listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
        self.close()
        self.process = subprocess.Popen([ssh, '-N', '-T', *options, '-L',
            f'127.0.0.1:{port}:{GATEWAY_HOST}:443', SSH_ALIAS],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **flags)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise NetworkUnavailable('已有 SSH 连接未能自动登录，请保留诊断结果。')
            try:
                with socket.create_connection(('127.0.0.1', port), timeout=.2):
                    break
            except OSError:
                time.sleep(.15)
        else:
            self.close()
            raise NetworkUnavailable('开发机转接启动超时。')
        return urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect(),
                                           TunnelHTTPSHandler(port, GATEWAY_HOST))

    def ensure(self, force=False):
        with self.lock:
            if self.opener is not None and not force:
                if self.route != 'bridge' or self.process is not None and self.process.poll() is None:
                    return
            if not force and self.failed_at is not None and time.monotonic() - self.failed_at < 30:
                raise NetworkUnavailable('识别网络暂未连通，请在设置中点击“检测并修复连接”。')
            self.opener = None
            self.route = ''
            self.attempts = []
            for route, handlers in [('default', []), ('direct', [urllib.request.ProxyHandler({})])]:
                opener = urllib.request.build_opener(*handlers, NoRedirect())
                if self._probe(opener, route):
                    self.close()
                    self.opener, self.route, self.failed_at = opener, route, None
                    return
            if self.allow_bridge:
                try:
                    opener = self._start_bridge()
                    if self._probe(opener, 'bridge'):
                        self.opener, self.route, self.failed_at = opener, 'bridge', None
                        return
                except (OSError, subprocess.SubprocessError):
                    self.attempts.append({'route': 'bridge', 'result': 'ssh_unavailable'})
                self.close()
            self.failed_at = time.monotonic()
            raise NetworkUnavailable('识别网络未连通，自动修复未完成。请打开设置查看连接诊断。')

    def open(self, req, timeout=120):
        url = urllib.parse.urlsplit(req.full_url if isinstance(req, urllib.request.Request) else req)
        if url.scheme != 'https' or (url.hostname, url.port or 443) != self.origin:
            raise NetworkUnavailable('识别请求目标与已配置网关不一致。')
        self.ensure()
        try:
            # Exactly one model request. Never retry a potentially billable POST.
            return self.opener.open(req, timeout=timeout)
        except urllib.error.HTTPError:
            raise
        except (OSError, urllib.error.URLError, http.client.HTTPException):
            self.opener = None
            raise

    def summary(self):
        return {'route': self.route, 'attempts': list(self.attempts)}
