#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Small authenticated LAN controller; runs without root/audio permissions."""
import hmac
import json
import os
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from equalizer_state import (STATE_DIR, STATE_FILE, STATUS_FILE, DEFAULT, PRESETS,
                             atomic_json, read_settings, validate)

PAGE = Path(__file__).with_name('equalizer.html')
LOCK = threading.Lock()


def read_profiles():
    p = STATE_DIR / 'profiles.json'
    if not p.exists():
        return {}
    return json.loads(p.read_text())


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        # Do not put auth headers or request bodies in the journal.
        pass

    def reply(self, status, value, html=False):
        body = value if html else json.dumps(value, ensure_ascii=False, allow_nan=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'text/html; charset=utf-8' if html else 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        self.end_headers()
        self.wfile.write(body)

    def authorized(self):
        token = self.headers.get('Authorization', '')
        return hmac.compare_digest(token, 'Bearer ' + self.server.token)

    def do_GET(self):
        if self.path == '/':
            return self.reply(200, PAGE.read_bytes(), html=True)
        if self.path != '/api/state':
            return self.reply(404, {'error': 'Nicht gefunden'})
        if not self.authorized():
            return self.reply(401, {'error': 'Zugangscode erforderlich'})
        try:
            with LOCK:
                settings = read_settings()
                profiles = {**PRESETS, **read_profiles()}
            try:
                runtime = json.loads(STATUS_FILE.read_text())
                runtime['fresh'] = time.time() - runtime.get('updated', 0) < 5
            except (OSError, ValueError):
                runtime = {'fresh': False}
            return self.reply(200, dict(settings=settings, profiles=profiles, runtime=runtime))
        except (OSError, ValueError):
            return self.reply(503, {'error': 'Einstellungen derzeit nicht lesbar'})

    def do_POST(self):
        if not self.authorized():
            return self.reply(401, {'error': 'Zugangscode erforderlich'})
        # No CORS. In addition to the bearer token, reject cross-site writes.
        origin = self.headers.get('Origin')
        if origin and origin not in ('http://' + self.headers.get('Host', ''), 'https://' + self.headers.get('Host', '')):
            return self.reply(403, {'error': 'Fremder Ursprung'})
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 8192 or self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                raise ValueError('JSON-Anfrage erwartet (maximal 8 KiB)')
            data = json.loads(self.rfile.read(length))
            with LOCK:
                if self.path == '/api/settings':
                    atomic_json(STATE_FILE, validate(data))
                elif self.path == '/api/profiles':
                    if not isinstance(data, dict) or set(data) != {'name', 'delete'}:
                        raise ValueError('Ungültiges Profil')
                    name = data['name']
                    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 40 or name in PRESETS or type(data['delete']) is not bool:
                        raise ValueError('Profilname ungültig oder reserviert')
                    profiles = read_profiles()
                    if data['delete']:
                        profiles.pop(name, None)
                    else:
                        if name not in profiles and len(profiles) >= 12:
                            raise ValueError('Maximal 12 eigene Profile')
                        current = read_settings()
                        profiles[name] = {k: current[k] for k in ('bass', 'mid', 'treble')}
                    atomic_json(STATE_DIR / 'profiles.json', profiles)
                else:
                    return self.reply(404, {'error': 'Nicht gefunden'})
            self.reply(200, {'ok': True})
        except (ValueError, TypeError, KeyError, OverflowError):
            self.reply(400, {'error': 'Ungültige Werte oder Profilname'})
        except OSError:
            self.reply(503, {'error': 'Speichern fehlgeschlagen'})

    def setup(self):
        super().setup()
        self.connection.settimeout(5)


def main():
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    if not STATE_FILE.exists():
        atomic_json(STATE_FILE, DEFAULT)
    token_file = STATE_DIR / 'access-token'
    if not token_file.exists():
        fd = os.open(token_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as f:
            f.write(secrets.token_urlsafe(24) + '\n')
    server = ThreadingHTTPServer((os.environ.get('EQ_BIND', '0.0.0.0'), int(os.environ.get('EQ_PORT', '8787'))), Handler)
    server.token = token_file.read_text().strip()
    print('Equalizer listening; access code is in the private state directory.', flush=True)
    server.serve_forever()


if __name__ == '__main__':
    main()
