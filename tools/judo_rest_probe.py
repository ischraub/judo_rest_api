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
import datetime
import http.client
import json
import sys
import time
import urllib.error
import urllib.request

# Command codes as documented in
# https://judo.eu/app/uploads/2024/11/API-KOMMANDOZEILEN.pdf
#
# Every command is <command byte><00><data>: /api/rest/380001 resets scene 1,
# /api/rest/570014 sets the salt warning to 20 days. Sending the data in place
# of that fixed 00 gets a 400 back.
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
    # Needs device software newer than 1.5.31 on the i-soft PRO family.
    "Geraetestatus": "6900",
}

# The statistics commands need a date appended: day, month, year as 2 bytes
# little-endian. Without it the device answers empty, and FE00 answers with a
# chunked body whose framing is broken, which takes the HTTP client down.
STATISTICS = {
    "Tagesstatistik": "FB00",
    "Wochenstatistik": "FC00",
    "Monatsstatistik": "FD00",
    "Jahresstatistik": "FE00",
}


# http.client.IncompleteRead is an HTTPException, not an OSError, so it used to
# escape the handler and abort the whole run.
FETCH_ERRORS = (
    urllib.error.URLError,
    http.client.HTTPException,
    OSError,
    ValueError,
    KeyError,
)


def fetch(
    base_url: str, command: str, auth_header: str, timeout: float, delay: float = 0.0
) -> str:
    """Run one command and return its raw hex payload.

    The module serves one request at a time and starts refusing or resetting
    connections when they arrive back to back - a run of 22 commands made it
    drop several, including ones that had answered fine moments earlier. So
    each call waits first, and a dropped connection is tried once more.
    """
    request = urllib.request.Request(
        base_url + command, headers={"Authorization": auth_header}
    )
    for attempt in range(2):
        if delay:
            time.sleep(delay)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
                return json.loads(response.read().decode())["data"]
        except (urllib.error.URLError, OSError, http.client.HTTPException):
            if attempt:
                raise
    raise RuntimeError("unreachable")


def date_suffix(day: datetime.date) -> str:
    """Encode a date the way the statistics commands expect it."""
    return f"{day.day:02X}{day.month:02X}{day.year & 0xFF:02X}{day.year >> 8:02X}"


def describe_scene(raw: str) -> str:
    """Spell out the fields of a scene as command 37 returns them.

    Derived from the answers of a real i-soft PRO, because the document's
    field list does not match them: it begins with a scene number that the
    answer does not contain, and lists ten fixed bytes where there are eight.
    What is left lines up exactly - every scene's content matches its name,
    and byte 1 is byte 0 converted from degrees dH to degrees f (x 1.7848).

    8 fixed bytes, then either 5 bytes of weekly schedule or, for "Urlaub
    geniessen", 8 bytes of start and stop date.
    """
    try:
        data = bytes.fromhex(raw)
    except ValueError:
        return "not hex"
    if len(data) < 8:
        return f"only {len(data)} bytes, expected at least 8"

    hardness = "unchanged (bypass)" if data[0] == 0xFF else f"{data[0]} dH / {data[1]} f"
    flags = [
        name
        for name, value in (
            ("Leckageschutz", data[2]),
            ("Entnahmemenge", data[3]),
            ("Durchfluss", data[4]),
            ("Entnahmezeit", data[5]),
            ("Favorit", data[6]),
            ("Zeitsteuerung", data[7]),
        )
        if value
    ]
    out = [f"Haerte={hardness}", "aktiv=" + (", ".join(flags) if flags else "nichts")]

    rest = data[8:]
    if len(rest) >= 8:
        # "Urlaub geniessen": start and stop date instead of a weekly schedule
        start_year = int.from_bytes(rest[0:2], "little")
        stop_year = int.from_bytes(rest[4:6], "little")
        out.append(
            f"Urlaub={rest[3]:02d}.{rest[2]:02d}.{start_year}"
            f"-{rest[7]:02d}.{rest[6]:02d}.{stop_year}"
        )
    elif len(rest) >= 5:
        # Bit 0 is Monday. The document says the days run "Sa..So", but its
        # own example gives 0x07 for a scene it describes as running on Mo,
        # Di and Mi, which only works counting from Monday.
        days = [
            name
            for bit, name in enumerate(("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"))
            if rest[0] & (1 << bit)
        ]
        out.append(
            f"Plan={'+'.join(days) if days else 'keine Tage'} "
            f"{rest[1]:02d}:{rest[2]:02d}-{rest[3]:02d}:{rest[4]:02d}"
        )
    return ", ".join(out)


def describe_status(raw: str) -> str:
    """Spell out the 16 byte device status of command 6900."""
    try:
        data = bytes.fromhex(raw)
    except ValueError:
        return "not hex"
    if len(data) < 12:
        return f"only {len(data)} bytes, expected 16 (needs device SW > 1.5.31)"
    scene = SCENES.get(data[0], f"unknown 0x{data[0]:02X}")
    return (
        f"aktive Szene={data[0]:X} {scene}, Optionen=0x{data[1]:02X}, "
        f"Leckageschutz=0x{data[2]:02X}, Leckagegrund=0x{data[3]:02X}, "
        f"Durchfluss={int.from_bytes(data[4:6], 'little')} l/h, "
        f"Dauer={int.from_bytes(data[6:8], 'little')} min, "
        f"Menge={int.from_bytes(data[8:10], 'little')} l, "
        f"Temperatur={int.from_bytes(data[10:12], 'little')} C"
    )


def read_holiday(base_url: str, auth_header: str, timeout: float, delay: float) -> None:
    """Try whether command 41 has a read form.

    Commands 3E, 3F and 40 are documented as "ohne Data liefert aktuellen Wert
    des Geraetes zurueck", and 41's length column reads "0/1", so it may do
    the same. If it does, the holiday flags can be read back and written with
    only the holiday bit cleared, instead of being rebuilt from command 69.

    Not part of the default run: 41 is a write command, and sending it without
    data may be taken as a write of empty flags, which would end holiday mode.
    """
    print("\nKommando 41 ohne Daten (Leseversuch):")
    try:
        data = fetch(base_url, "4100", auth_header, timeout, delay)
    except FETCH_ERRORS as err:
        print(f"  4100  !! {err}")
        print("  -> kein Lesezugriff; die Flags muessen aus 6900 abgeleitet werden")
        return
    print(f"  4100  {data}")
    if data:
        b = bytes.fromhex(data)
        print(f"  -> {len(b)} Byte. Byte 0 waeren die Flags: 0x{b[0]:02X}"
              + (f", Byte 1 Urlaubstage: {b[1]}" if len(b) > 1 else ""))


def read_scenes(
    base_url: str, auth_header: str, timeout: float, delay: float
) -> None:
    """Read every scene back. Read only: it sends the scene number alone."""
    print("\nSzenen (Kommando 37, nur lesend):")
    for number, name in SCENES.items():
        command = f"3700{number:02X}"
        try:
            data = fetch(base_url, command, auth_header, timeout, delay)
        except FETCH_ERRORS as err:
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
        "-d",
        "--delay",
        default=1.0,
        type=float,
        help="seconds to wait before each request (the module drops "
        "connections when they arrive back to back)",
    )
    parser.add_argument(
        "--statistics",
        action="store_true",
        help="also query the statistics commands for today's date",
    )
    parser.add_argument(
        "--holiday",
        action="store_true",
        help="try whether command 41 can be read (may end holiday mode)",
    )
    parser.add_argument(
        "--scenes",
        action="store_true",
        help="also read the scene settings (i-soft PRO family only)",
    )
    args = parser.parse_args()

    base_url = f"http://{args.host}:{args.port}/api/rest/"
    token = base64.b64encode(f"{args.username}:{args.password}".encode()).decode()
    auth_header = f"Basic {token}"

    today = datetime.date.today()
    queries = dict(COMMANDS)
    if args.statistics:
        queries.update(
            {name: code + date_suffix(today) for name, code in STATISTICS.items()}
        )

    width = max(len(name) for name in queries)
    for name, command in queries.items():
        try:
            data = fetch(base_url, command, auth_header, args.timeout, args.delay)
        except FETCH_ERRORS as err:
            print(f"{name:{width}}  {command}  !! {err}")
            continue
        print(f"{name:{width}}  {command}  {data}")
        if command == "6900":
            print(f"{'':{width}}  {'':4}  {describe_status(data)}")

    if args.holiday:
        read_holiday(base_url, auth_header, args.timeout, args.delay)
    if args.scenes:
        read_scenes(base_url, auth_header, args.timeout, args.delay)
    return 0


if __name__ == "__main__":
    sys.exit(main())
