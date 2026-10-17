# Bench tools

The **current** API command list is linked from https://judo.eu/produkte/api/
and lives at https://judo.eu/ftp-upload/download/REST-API/RESTAPI_Kommandos.pdf
The 2024 PDF that this integration was originally written against is outdated
and misses command 69.

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

Every command on this API is `<command byte><00><data>`: `/api/rest/380001`
resets scene 1, `/api/rest/570014` sets the salt warning to 20 days. All ten
examples in the document follow it. Putting the data where that fixed `00`
belongs gets a `400 Bad Request` back.

| URL | Meaning |
|---|---|
| `3600` + scene + duration | Activate a scene now (3 data bytes) |
| `3700` + scene | Read a scene back (1 data byte) |
| `3700` + full payload | Write/edit a scene |
| `3800` + scene | Reset a scene to its factory setting |

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

The module serves one request at a time and starts refusing or resetting
connections when they arrive back to back: a run of 22 commands made it drop
several, including ones that had answered fine moments earlier. The tool
therefore waits a second before each request (`--delay`) and retries a dropped
connection once. This is the same reason the integration serialises every call
through a lock.

### Confirmed against the Judo app

For an i-soft PRO the app reports: software version 1.4.17, commissioning date
13.05.2025, water total 36,492 m3 - all three match what the API returns and
how it is decoded here. The app's "Geraete ID" (`03J053180005F6`) is NOT the
device number of command `0600`: neither reading of `24146BA8` appears in it.

The app reports an operating time of **783 days** where the counter in command
`2500` reads 521 big-endian or 2306 little-endian, so it matches neither.
521 is the number of days since the commissioning date the same device
reports, to the day, and 783 would predate commissioning. To settle the byte
order, read `2500` again N days later: if the device stores the counter
big-endian the day bytes go `0209` -> `020C` after 3 days, if little-endian
they go `0209` -> `0509`.

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

### Scene layout, as a device actually answers it

The document's field list for command 37 does not match what comes back: it
begins with a scene number the answer does not contain, and lists ten fixed
bytes where there are eight. What is left lines up exactly.

| Byte | Meaning |
|---|---|
| 0 | Target hardness in dH, `FF` = unchanged (bypass) |
| 1 | The same hardness in degrees f (byte 0 x 1.7848) |
| 2 | Leakage protection active |
| 3 | Withdrawal volume monitored |
| 4 | Flow rate monitored |
| 5 | Withdrawal time monitored |
| 6 | Favourite |
| 7 | Time control on/off |
| 8..12 | Weekly schedule: active days (bit 0 = Sunday), start HH MM, end HH MM |
| 8..15 | Only for "Urlaub geniessen": start year (2 byte little-endian), month, day, stop year, month, day |

So a normal scene answers with 13 bytes and "Urlaub geniessen" with 16.

Scene numbering is **0-based** on the wire, and the document's list order is
the wire order. Three independent checks on one device: scene 3 is the only
one with a date block, and the document says that block belongs to "Urlaub
geniessen"; scene 7 "Heizung befuellen" asks for 0 dH, fully softened, which
is what a heating system wants; scenes 2 and 6, "Garten bewaessern" and "Pool
befuellen", are set to bypass, which is what a garden and a pool want.

### Open points for the scenes

1. Its example for command 36 (`/api/rest/36000200200`) has an odd number of
   hex characters. `3600` + `02` + `0200` is the consistent form.
2. ~~Scene numbering 0-based or 1-based~~ - settled, it is 0-based, see above.

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


## Command 69: device status

Needs device software newer than 1.5.31. 16 byte answer:

| Byte | Meaning |
|---|---|
| 0 | Active scene (same numbering as command 36) |
| 1 | Active scene options (bit per option) |
| 2 | Global leakage protection status |
| 3 | Leakage reason |
| 4-5 | Current flow in l/h (little-endian) |
| 6-7 | Current draw duration in minutes |
| 8-9 | Current draw amount in litres |
| 10-11 | Water temperature in degrees C |
| 12-15 | unused |

This is the only way to ask which scene is running.

## HTTP errors the module returns

Documented in the Smart Home manual (1702574, 2026/01), chapter 7:

| Status | Meaning |
|---|---|
| 400 | No arguments, or the command is not allowed |
| 429 | Device control did not answer within 1.5 s; `Retry-After: 2` |
| 500 | Arguments wrong or longer than 80 bytes |

A response from the device control that starts with `FF` is an error, not
data: `FF0001` is a checksum error. A full-length answer that happens to begin
with `FF` is not - a scene set to bypass answers `FFFF...`.
