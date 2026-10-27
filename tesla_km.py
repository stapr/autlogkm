"""Tesla kilometerstand-logger.

Een Apple Shortcut roept dit script aan (webhook) op het moment dat de Tesla
geopend (/open) en gesloten (/close) wordt. Het script leest dan via de Tesla
Fleet API de odometer uit en legt per rit begin- en eindstand vast in een CSV.

Gebruik:
    python tesla_km.py serve            # webhook voor de Shortcut
    python tesla_km.py open|close       # handmatig een meting doen
    python tesla_km.py report [YYYY-MM] # samenvatting per maand
    python tesla_km.py auth-url         # eenmalig: inloglink voor Tesla
    python tesla_km.py auth-code CODE   # eenmalig: code inwisselen voor tokens
"""
import csv
import json
import os
import sys
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import requests

MILES_TO_KM = 1.609344
AUTH_URL = "https://auth.tesla.com/oauth2/v3"
FIELDS = ["id", "start_tijd", "start_km", "eind_tijd", "eind_km", "afstand_km"]


def cfg(name, default=None, required=False):
    value = os.environ.get(name, default)
    if required and not value:
        sys.exit(f"Omgevingsvariabele {name} ontbreekt (zie .env.example)")
    return value


def load_env(path=".env"):
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"'))


class TeslaClient:
    """Dunne wrapper om de Fleet API: tokens verversen, wakker maken, odometer lezen."""

    def __init__(self):
        self.client_id = cfg("TESLA_CLIENT_ID", required=True)
        self.client_secret = cfg("TESLA_CLIENT_SECRET", "")
        self.api = cfg("TESLA_API_BASE", "https://fleet-api.prd.eu.vn.cloud.tesla.com")
        self.vin = cfg("TESLA_VIN", required=True)
        self.token_file = Path(cfg("TESLA_TOKEN_FILE", "tokens.json"))
        self._lock = threading.Lock()

    # -- tokens ---------------------------------------------------------
    def _load_tokens(self):
        if not self.token_file.exists():
            sys.exit("Geen tokens.json: doorloop eerst 'auth-url' en 'auth-code'.")
        return json.loads(self.token_file.read_text())

    def _save_tokens(self, tokens):
        tokens["obtained_at"] = time.time()
        self.token_file.write_text(json.dumps(tokens))
        os.chmod(self.token_file, 0o600)

    def exchange_code(self, code):
        r = requests.post(f"{AUTH_URL}/token", timeout=30, data={
            "grant_type": "authorization_code",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "code": code,
            "audience": self.api,
            "redirect_uri": cfg("TESLA_REDIRECT_URI", required=True),
        })
        r.raise_for_status()
        self._save_tokens(r.json())

    def _access_token(self):
        t = self._load_tokens()
        if time.time() < t["obtained_at"] + t.get("expires_in", 0) - 120:
            return t["access_token"]
        # Refresh tokens zijn eenmalig bruikbaar: direct het nieuwe paar opslaan.
        r = requests.post(f"{AUTH_URL}/token", timeout=30, data={
            "grant_type": "refresh_token",
            "client_id": self.client_id,
            "refresh_token": t["refresh_token"],
        })
        r.raise_for_status()
        new = r.json()
        new.setdefault("refresh_token", t["refresh_token"])
        self._save_tokens(new)
        return new["access_token"]

    # -- voertuig -------------------------------------------------------
    def _request(self, method, path, **kw):
        headers = {"Authorization": f"Bearer {self._access_token()}"}
        return requests.request(method, f"{self.api}/api/1/vehicles/{self.vin}{path}",
                                headers=headers, timeout=30, **kw)

    def odometer_km(self, wake_timeout=60):
        """Odometer in km; maakt de auto indien nodig wakker (HTTP 408 = slaapt)."""
        with self._lock:
            deadline = time.time() + wake_timeout
            while True:
                r = self._request("GET", "/vehicle_data",
                                  params={"endpoints": "vehicle_state"})
                if r.status_code == 200:
                    miles = r.json()["response"]["vehicle_state"]["odometer"]
                    return round(miles * MILES_TO_KM, 1)
                if r.status_code != 408 or time.time() > deadline:
                    raise RuntimeError(f"Tesla API {r.status_code}: {r.text[:200]}")
                self._request("POST", "/wake_up")
                time.sleep(5)


class TripLog:
    """CSV met één rij per rit. Een rit zonder eindstand is nog 'open'."""

    def __init__(self, path):
        self.path = Path(path)
        self._lock = threading.Lock()

    def _read(self):
        if not self.path.exists():
            return []
        with self.path.open(newline="") as f:
            return list(csv.DictReader(f))

    def _write(self, rows):
        with self.path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            w.writeheader()
            w.writerows(rows)

    def open_trip(self, km, now=None):
        with self._lock:
            rows = self._read()
            row = dict.fromkeys(FIELDS, "")
            row.update(id=len(rows) + 1, start_tijd=_ts(now), start_km=km)
            rows.append(row)
            self._write(rows)
            return row

    def close_trip(self, km, now=None):
        """Sluit de laatste open rit. Zonder open rit: aparte rij met alleen eindstand."""
        with self._lock:
            rows = self._read()
            row = next((r for r in reversed(rows) if not r["eind_tijd"]), None)
            if row is None:
                row = dict.fromkeys(FIELDS, "")
                row["id"] = len(rows) + 1
                rows.append(row)
            row.update(eind_tijd=_ts(now), eind_km=km)
            if row["start_km"]:
                row["afstand_km"] = round(float(km) - float(row["start_km"]), 1)
            self._write(rows)
            return row

    def report(self, month=None):
        rows = [r for r in self._read() if r["afstand_km"]
                and (not month or r["start_tijd"].startswith(month))]
        per_month = {}
        for r in rows:
            per_month[r["start_tijd"][:7]] = per_month.get(r["start_tijd"][:7], 0) + float(r["afstand_km"])
        return {"ritten": len(rows),
                "totaal_km": round(sum(per_month.values()), 1),
                "per_maand": {m: round(v, 1) for m, v in sorted(per_month.items())},
                "onvolledig": sum(1 for r in self._read() if not r["start_km"] or not r["eind_tijd"])}


def _ts(now=None):
    return (now or datetime.now()).isoformat(timespec="seconds")


def handle_event(event, client, log):
    km = client.odometer_km()
    row = log.open_trip(km) if event == "open" else log.close_trip(km)
    return {"event": event, "odometer_km": km, "rit": row}


def make_handler(client, log, token):
    class Handler(BaseHTTPRequestHandler):
        def _reply(self, code, body):
            data = json.dumps(body, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _route(self):
            url = urlparse(self.path)
            supplied = self.headers.get("X-Token") or parse_qs(url.query).get("token", [""])[0]
            if not token or supplied != token:
                return self._reply(401, {"fout": "ongeldig token"})
            path = url.path.strip("/")
            try:
                if path in ("open", "close"):
                    return self._reply(200, handle_event(path, client, log))
                if path == "report":
                    return self._reply(200, log.report(parse_qs(url.query).get("maand", [None])[0]))
            except Exception as e:  # Shortcut moet een leesbare fout krijgen
                return self._reply(502, {"fout": str(e)})
            self._reply(404, {"fout": "onbekend pad"})

        do_GET = do_POST = _route

        def log_message(self, fmt, *args):
            print(f"{_ts()} {self.address_string()} {fmt % args}", flush=True)

    return Handler


def main(argv):
    load_env()
    cmd = argv[1] if len(argv) > 1 else ""
    log = TripLog(cfg("TRIPS_CSV", "ritten.csv"))

    if cmd == "report":
        print(json.dumps(log.report(argv[2] if len(argv) > 2 else None), indent=2, ensure_ascii=False))
    elif cmd == "auth-url":
        print(f"{AUTH_URL}/authorize?" + urlencode({
            "response_type": "code",
            "client_id": cfg("TESLA_CLIENT_ID", required=True),
            "redirect_uri": cfg("TESLA_REDIRECT_URI", required=True),
            "scope": "openid offline_access vehicle_device_data",
            "state": "autlogkm",
        }))
    elif cmd == "auth-code" and len(argv) > 2:
        TeslaClient().exchange_code(argv[2])
        print("Tokens opgeslagen.")
    elif cmd in ("open", "close"):
        print(json.dumps(handle_event(cmd, TeslaClient(), log), indent=2, ensure_ascii=False))
    elif cmd == "serve":
        token = cfg("WEBHOOK_TOKEN", required=True)
        port = int(cfg("PORT", "8080"))
        server = ThreadingHTTPServer(("0.0.0.0", port), make_handler(TeslaClient(), log, token))
        print(f"Luistert op poort {port}")
        server.serve_forever()
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv)
