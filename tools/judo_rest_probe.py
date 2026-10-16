#!/usr/bin/env python3
"""Print the raw answer of every known command of a Judo connectivity module.

Not part of the integration - it is a bench tool for checking payload layouts
against a real device, which is how the decoding in restobject.py was verified.
It lives outside custom_components/ so it is not shipped to users.

    python3 tools/judo_rest_probe.py 192.168.1.42
    python3 tools/judo_rest_probe.py 192.168.1.42 -u admin -p secret
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
import urllib.error
import urllib.request

# Command codes as documented in
# https://judo.eu/app/uploads/2024/11/API-KOMMANDOZEILEN.pdf
COMMANDS = {
    "Geraetetyp": "FF00",
    "Geraetenummer": "0600",
    "SW-Version": "0100",
    "Inbetriebnahmedatum": "0E00",
    "Betriebsstundenzaehler": "2500",
    "Kundendienst-Serviceadresse": "5800",
    "Wunschwasserhaerte": "5100",
    "Salzvorrat": "5600",
    "Salzreichweite": "5700",
    "Gesamtwassermenge": "2800",
    "Weichwassermenge": "2900",
    "Tagesstatistik": "FB00",
    "Wochenstatistik": "FC00",
    "Monatsstatistik": "FD00",
    "Jahresstatistik": "FE00",
}


def fetch(base_url: str, command: str, auth_header: str, timeout: float) -> str:
    """Run one command and return its raw hex payload."""
    request = urllib.request.Request(
        base_url + command, headers={"Authorization": auth_header}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        return json.loads(response.read().decode())["data"]


def main() -> int:
    """Probe the device and print one line per command."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("host", help="IP address or host name of the module")
    parser.add_argument("--port", default=80, type=int)
    parser.add_argument("-u", "--username", default="admin")
    parser.add_argument("-p", "--password", default="Connectivity")
    parser.add_argument("-t", "--timeout", default=10.0, type=float)
    args = parser.parse_args()

    base_url = f"http://{args.host}:{args.port}/api/rest/"
    token = base64.b64encode(f"{args.username}:{args.password}".encode()).decode()
    auth_header = f"Basic {token}"

    width = max(len(name) for name in COMMANDS)
    for name, command in COMMANDS.items():
        try:
            data = fetch(base_url, command, auth_header, args.timeout)
        except (urllib.error.URLError, OSError, ValueError, KeyError) as err:
            print(f"{name:{width}}  {command}  !! {err}")
            continue
        print(f"{name:{width}}  {command}  {data}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
