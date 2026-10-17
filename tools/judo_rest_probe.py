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
#
# Scenes exist on the i-soft PRO family (device type 0x58, 0x4b, 0x4c), page 2
# of that document. Command 37 with only a scene number reads a scene back;
# with a full payload it would write one, so this tool only ever sends the
# number.
SCENES = {
    0x0: "Alltag meistern",
    0x1: "Koerper pflegen",
    0x2: "Garten bewaessern",
    0x3: "Urlaub geniessen",
    0x4: "Waesche waschen",
    0x5: "Hochdruckreinigen",
    0x6: "Pool befuellen",
    0x7: "Heizung befuellen",
    0x8: "Custom Szene 1",
    0x9: "Custom Szene 2",
    0xA: "Custom Szene 3",
}

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


def describe_scene(raw: str) -> str:
    """Spell out the fields of a scene as command 37 returns them."""
    try:
        data = bytes.fromhex(raw)
    except ValueError:
        return "not hex"
    if len(data) < 9:
        return f"only {len(data)} bytes, expected at least 9"
    names = [
        "Szenennummer",
        "Wasserhaerte dH",
        "Wasserhaerte f/mmol/ppm",
        "Leckageschutz",
        "Entnahmemenge",
        "Durchflussmenge",
        "Entnahmezeit",
        "Favorit",
        "Zeitsteuerung",
    ]
    out = [f"{name}={value}" for name, value in zip(names, data[:9])]
    rest = data[9:]
    if rest:
        out.append(f"Zeit/Datum-Teil={rest.hex()}")
    return ", ".join(out)


def read_scenes(base_url: str, auth_header: str, timeout: float) -> None:
    """Read every scene back. Read only: it sends the scene number alone."""
    print("\nSzenen (Kommando 37, nur lesend):")
    for number, name in SCENES.items():
        command = f"37{number:02X}"
        try:
            data = fetch(base_url, command, auth_header, timeout)
        except (urllib.error.URLError, OSError, ValueError, KeyError) as err:
            print(f"  {number:X} {name:<20} {command}  !! {err}")
            continue
        print(f"  {number:X} {name:<20} {command}  {data}")
        print(f"      {describe_scene(data)}")


def main() -> int:
    """Probe the device and print one line per command."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("host", help="IP address or host name of the module")
    parser.add_argument("--port", default=80, type=int)
    parser.add_argument("-u", "--username", default="admin")
    parser.add_argument("-p", "--password", default="Connectivity")
    parser.add_argument("-t", "--timeout", default=10.0, type=float)
    parser.add_argument(
        "--scenes",
        action="store_true",
        help="also read the scene settings (i-soft PRO family only)",
    )
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

    if args.scenes:
        read_scenes(base_url, auth_header, args.timeout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
