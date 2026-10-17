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

The statistics commands need a date appended (day, month, year as 2 bytes
little-endian): `/api/rest/FB001506E807` is 21.06.2024. Without it the device
answers empty, and `FE00` answers with a chunked body whose framing is broken,
which takes a plain HTTP client down. Pass `--statistics` to query them for
today.

Read the scenes back without changing anything:

```
python3 tools/judo_rest_probe.py <ip> -p <password> --scenes
```

### What the document gets wrong for this family

The i-soft PRO page (device types 0x58, 0x4b, 0x4c) is the only one whose
examples are not copy-pasted from the i-soft page, and it differs in two
places:

* **Device number is big-endian.** Its example `10D36F28` = 282292008 only
  works big-endian; every other page's example (`64d90100` = 121188,
  `0774ed0b` = 200111111) only works little-endian.
* **SW version has a numeric third component.** `0C0001` = 1.0.12, where the
  other pages read the same byte as a letter (`6b1502` = 2.21k).

And one place where the document is wrong about this family: it gives
`060c7500` = 117 days for the operating day counter, which is little-endian.
That very example appears verbatim on pages 1, 4 and 5 as well, so it was
copied, not measured. On a real i-soft PRO the counter is **big-endian**:
`0209` reads 521, which is exactly the number of days since the commissioning
date the same device reports, while little-endian would give 2306 days for a
device commissioned in 2025.

### Open points for the scenes

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
| `0600` device number | `64d90100` -> 121188 (**little**-endian) | `24146BA8` -> 605318056 (**big**-endian) | 4 byte, endianness differs by family |
| `0100` SW version | `6b1502` -> 2.21k | `110401` -> 1.4.17 | patch, minor, major; a printable patch byte is a letter suffix (`2.21k`), a numeric one a third component (`1.4.17`) |
| `0E00` commissioning | | `0d0507e9` -> 13.05.2025 | day, month, year **big-endian** |
| `2500` operating time | `060c7500` -> 6 min, 12 h, 117 d (little-endian) | `0E150209` -> 14 min, 21 h, 521 d (**big-endian**) | minutes, hours, days (2 byte) |
| `5100` target hardness | `0600` -> 6 °dH | | 2 byte little-endian |
| `5600` salt | `f6541100` -> 21.75 kg, 17 d | | mass in g, then days |
| `5800` service contact | `2b34392037313935...` -> "+49 7195 692517" | | 16 byte ASCII |
| `2800` water total | `EC221000` -> 1057.516 m3 | | 4 byte little-endian, litres |
| `2900` water treated | `2EDC0000` -> 56.366 m3 | | 4 byte little-endian, litres |
