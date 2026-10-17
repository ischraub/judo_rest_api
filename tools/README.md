# Bench tools

Not shipped with the integration.

## judo_rest_probe.py

Prints the raw answer of every known command of a connectivity module. Use it
to check a payload layout against a real device before changing the decoding in
`custom_components/judo_rest_api/restobject.py`.

```
python3 tools/judo_rest_probe.py 192.168.1.42
```

## Scenes (i-soft PRO family only)

Device types 0x58, 0x4b and 0x4c know "Wasserszenen", page 2 of the API
document. They are not in the integration yet.

| Command | Length | Meaning |
|---|---|---|
| `36` | 3 byte | Activate a scene now: scene number, then duration as HH MM |
| `37` | 1 byte in | Read a scene back |
| `37` | full payload | Write/edit a scene |
| `38` | 1 byte | Reset a scene to its factory setting |

Scene numbers: 0 Alltag meistern, 1 Koerper pflegen, 2 Garten bewaessern,
3 Urlaub geniessen, 4 Waesche waschen, 5 Hochdruckreinigen, 6 Pool befuellen,
7 Heizung befuellen, 8-A Custom 1-3.

Durations listed for command 36: `000F` 15 min, `001E` 30 min, `002D` 45 min,
`0100` 1 h, `0200` 2 h, `0600` 6 h, `0C00` 12 h, `FFFF` unlimited.

Read them back without changing anything:

```
python3 tools/judo_rest_probe.py <ip> -p <password> --scenes
```

Two things the document leaves open and that a device has to settle before
this can go into the integration:

1. Its example for command 36 (`/api/rest/36000200200`) has an odd number of
   hex characters. `3600` + `02` + `0200` would be the consistent form.
2. Scene numbering is given as "1...10" for commands 37 and 38 but the list
   itself starts at "Szene 0" and ends at "Szene A", so it is unclear whether
   the wire value is 0-based or 1-based.

### Reference payloads

Captured from two devices and used to verify the decoding. The byte order of
the day counter in `2500` differs between the two, which is why it is an
explicit `read_endian` on the item.

| Command | i-soft, FW 2.21k | i-soft PRO, FW 1.04 | Layout |
|---|---|---|---|
| `FF00` device type | | `5800` | type in the first byte |
| `0600` device number | `64d90100` -> 121188 | `24146ba8` -> unverified | 4 byte little-endian |
| `0100` SW version | `6b1502` -> 2.21k | -> 1.04 | letter, minor, major; letter only when printable |
| `0E00` commissioning | | `0d0507e9` -> 13.05.2025 | day, month, year **big-endian** |
| `2500` operating time | `060c7500` -> 6 min, 12 h, 117 d (little-endian) | `0f030209` -> 15 min, 3 h, 521 d (**big-endian**) | minutes, hours, days (2 byte) |
| `5100` target hardness | `0600` -> 6 °dH | | 2 byte little-endian |
| `5600` salt | `f6541100` -> 21.75 kg, 17 d | | mass in g, then days |
| `5800` service contact | `2b34392037313935...` -> "+49 7195 692517" | | 16 byte ASCII |
| `2800` water total | `EC221000` -> 1057.516 m3 | | 4 byte little-endian, litres |
| `2900` water treated | `2EDC0000` -> 56.366 m3 | | 4 byte little-endian, litres |
