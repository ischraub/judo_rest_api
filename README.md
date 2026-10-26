# Version 1.8.1
**A reading outside what the device can physically be measuring is refused.** After a scene expired, a device reported a water temperature of 5891 °C. That is not a measurement, and letting it through puts it in the recorder's statistics, where it wrecks the scale of every graph it appears in - the same damage the truncated water readings did before 1.1.0.

An item can now state the range it must fall in. Outside it the entity goes unavailable, which is what a value nobody can use deserves. The water temperature is bounded to 0-80 °C.

This is a guard, not an explanation: the device really does report that number, and why it does after a scene expires is still open.

# Version 1.8.0
**One action for a scene and its duration.** Setting them with two `select.select_option` calls works, but only in the right order - the scene reads the duration as it is activated, so the duration has to be set first. `judo_rest_api.activate_scene` takes both, and there is no order to get wrong:

```yaml
actions:
  - action: judo_rest_api.activate_scene
    target:
      entity_id: select.judo_wasserszene
    data:
      scene: scene_body_care
      duration: duration_2_h
```

`duration` and `days` are optional; without them the values currently set are used. `days` applies to the holiday scene, which counts in days rather than hours. The scene and duration appear as dropdowns in the automation editor.

The two selects stay as they are for operating the device by hand.

# Version 1.7.1
**A spent duration is no longer restored after a restart.** Up to 1.6.3 the duration select displayed its default when nothing was set, and Home Assistant recorded that as the entity's state. On the first restart after upgrading, `RestoreEntity` brought it back as though it had been chosen - so a device sitting on the base scene showed "2 hours" where 1.7.0 means to show nothing.

The value is only restored while a timed scene is running. On the base scene nothing is in force, so there is nothing to restore - the same rule 1.7.0 applies while running.

This clears the leftover by itself on the next restart. The holiday days are unaffected; they are a standing setting, not a value that gets used up.

# Version 1.7.0
**The scene duration clears once it has been used.** A scene started for fifteen minutes returns to the base scene by itself, and from that moment no limit is running - but the duration select went on showing "15 minutes", which reads as if one were.

It is now emptied the moment the device falls back to the base scene. Only that step clears it, so a duration picked in advance survives until it has been used, and switching between two timed scenes keeps it.

Empty means no duration is in force, not that the default applies: a scene started with the field empty is sent the default of two hours, which the log records.

This matters because the duration cannot be read back. Nothing in the API reports it, so the field can only ever show what was last sent from Home Assistant - a change made in the Judo app in the meantime stays invisible here.

# Version 1.6.3
**The scene duration no longer jumps back to its default.** A scan rebuilds the coordinator data from the items it reads, and the two values that live only in Home Assistant - the scene duration and the holiday days - were not among them, so a minute after being set they fell back to the default. The select then showed two hours when the user had chosen fifteen minutes, which reads as if two hours were in force.

Both values are carried over between scans now.

Two things confirmed on a device in the meantime, neither needing a change:

* **The duration is applied.** A scene activated for fifteen minutes returned to the base scene by itself. The Judo app shows no duration for a scene activated over the local API because it takes that from Judo's portal, which never sees a local activation - so the app saying nothing is not the integration failing to set it.
* **"Alltag meistern" can be activated**, although the document gives command 36's scene range as "1...9 + A". The device also reports it as the one scene whose `timer_not_allowed` bit is set, which is what 1.6.2 relies on.

# Version 1.6.2
**"Alltag meistern" has no duration.** It is the base scene the device falls back to and runs until something replaces it, which is why the Judo app offers no duration for it. It was being sent with whatever the duration select happened to hold - two hours by default - and is now always sent as "unendlich".

Three of the eleven scenes treat the duration differently: the base scene ignores it, "Urlaub genießen" counts in days, and the other nine take the hours from the select.

# Version 1.6.1
**Command 41 only starts the holiday mode; it has no "off".** Written with the active bit cleared the device answers HTTP 500, "invalid argument" - `/api/rest/41000002` was refused where `/api/rest/41000102` had been accepted a moment earlier. Leaving holiday mode through it failed, so switching away from the holiday scene raised an error instead of switching.

The mode ends by activating another scene, which is what the device does anyway: it runs the holiday mode exactly while that scene is active. Choosing another scene now simply sends command 36.

# Version 1.6.0
**The holiday mode is one of the scenes, so it is picked like one.** Choosing "Urlaub genießen" starts it for the days set next to the scene; choosing anything else ends it and runs that scene instead.

The separate **Start holiday mode** button from 1.5.0 is gone. It only existed because the holiday duration is counted in days where the scene duration is in hours, which is a detail of the device, not a reason to split one choice across two controls. The button is removed from the entity registry on upgrade.

The three controls now sort together: **Water scene**, **Water scene duration** (hours, for the ordinary scenes) and **Water scene holiday days** (1 to 60).

# Version 1.5.1
**The holiday mode is read from the active scene.** It runs exactly while scene 3, "Urlaub genießen", is the active one, which is command 69 byte 0.

1.5.0 read it from command 41 instead and reported it as on while the device was running "Alltag meistern" with the mode off. Read back, command 41 reports the **stored configuration** - the flags and day count the next start will use - not the running state: a device with the mode off still answers `0106`, flags "active" and six days.

That makes three readings of the holiday state in a row that were wrong, each from a field that looked plausible. The active scene is the one the device itself shows, so it is the one to trust.

Command 41 is still read before writing, so switching the mode on or off keeps its other flags unchanged. It is fetched when needed rather than polled, which also saves a request per scan.

# Version 1.5.0
**Command 41 can be read.** Sent without data it answers with its two bytes, the flag byte and the duration in days, which corrects a wrong assumption in 1.4.0 and makes the holiday mode a proper entity.

* **1.4.0 read the holiday state from the wrong place.** It took bit 5 of command 69 byte 1, but that byte mirrors the options of the *active scene*: the bit says this scene has no holiday timer, not that the device has none. On a device sitting on scene 0 with the holiday mode switched on, 1.4.0 saw it as off and left it running. The state now comes from command 41 itself.
* Switching the holiday mode off writes the flags and the day count back **exactly as the device reported them**, with only the active bit cleared. 1.4.0 rebuilt them from command 69, which risked silently turning other options off.

Three new entities:

* **Holiday mode** - a binary sensor, on while the device runs it.
* **Holiday days** - 1 to 60, held in Home Assistant and restored after a restart.
* **Start holiday mode** - a button. It takes the day count from the number above and keeps the other flags the device reports.

Choosing any other scene still ends the holiday mode, now on a correct reading of it.

# Version 1.4.0
**Choosing a scene now leaves holiday mode.** Holiday mode is not started by command 36 and is not left by it either, so coming back from holiday and picking a scene used to change nothing. The scene select now checks command 69 first and, if the holiday timer is running, switches it off with command 41 before activating the scene you picked.

Holiday mode itself is still started at the device or in the Judo app, not here - command 41 takes a duration in days where the scene duration is in hours. Picking "Holiday" in the select says so rather than failing silently.

Command 41 has no documented read, so the other options it carries - the two micro leakage settings - are rebuilt from the leakage protection status in command 69 byte 2, where they correspond by name. Its bit 7, "leakage protection globally off", is **never set**: command 69 does not report it in a form that can be read back, and of the two possible mistakes only leaving protection on is safe. `tools/judo_rest_probe.py --holiday` tries whether command 41 can be read after all, which would make the rebuild unnecessary.

# Version 1.3.3
* The software version's third byte is interpreted by **device family**, not by whether the byte happens to be printable. On the i-soft PRO family it is a number, elsewhere a letter. The old guess survived 1.5.32 only because `0x20` is a space: 1.5.33 would have rendered as "1.05!", and 1.5.48 as "1.050".

Three things an i-soft PRO on 1.5.32 confirmed against real hardware:

* **Command 69 works and the 16 byte layout is right.** Every bit of its scene-options byte that has a counterpart in the command 37 scene data agrees with it, so the two layouts cross-check each other. Active scene, current flow and water temperature now have values.
* **The operating day counter is big-endian.** Predicted `020E` for big-endian and `0709` for little-endian after five days; the device answered `020E`. The document's little-endian example is copy-pasted from another page and wrong for this family.
* The software version decodes to 1.5.32 from `200501`, as predicted.

# Version 1.3.2
* `hacs.json` sets `hide_default_branch`, so HACS can only track releases and never the `main` branch. A repository that offers both can end up comparing the installed release against the branch head, which makes the update check look broken.

# Version 1.3.1
* Fixes a regression in 1.3.0: the water scene select went unavailable on device software older than 1.5.31, which took the control away entirely. Activating a scene does not depend on reading one, so the select stays operable and only the shown active scene stays unknown until the firmware supports command 69.
* The scene duration is named so that it sorts directly below the scene in the controls.

# Version 1.3.0
Built on the **current** API command list, `https://judo.eu/ftp-upload/download/REST-API/RESTAPI_Kommandos.pdf`, linked from https://judo.eu/produkte/api/. The November 2024 PDF this integration was written against is outdated and misses command 69 entirely.

* **The active water scene can be read** - command `69` returns a 16 byte device status. The scene select now shows what the device reports instead of what was last sent from here. **Requires device software newer than 1.5.31**; on older firmware the entity stays unavailable, because the API offers no other way to ask and showing the last command would claim more than it knows.
* Two new sensors out of the same answer: **current water flow** in L/h and **water temperature**.
* The scene duration is no longer a configuration entity, so it sits next to the scene in the controls.
* HTTP **429** is retried. Judo documents it as "device control did not reply within 1.5 s" and answers with `Retry-After: 2`, which this now waits.
* Each read command is fetched **once per scan**, not once per entity. Four entities come out of commands `5600` and `6900`, and this device drops connections when requests arrive in quick succession.

# Version 1.2.0
Water scenes for the i-soft PRO family (device types 0x58, 0x4b, 0x4c).

Two new entities:

* **Water scene** - a select with the eleven scenes the device knows: everyday, body care, garden watering, holiday, laundry, pressure washing, filling the pool, filling the heating system and three custom ones. Selecting one activates it on the device.
* **Scene duration** - 15/30/45 minutes, 1/2/6/12 hours or unlimited. It is not stored on the device, so it lives in Home Assistant and is restored after a restart. Default is 2 hours rather than unlimited, which would leave a bypass scene running with leakage protection off.

The scene select is **write only**: the API has no command that reports which scene is running, so what it shows is the scene last activated from Home Assistant. It does not tell you whether that scene is still running, or whether somebody changed it at the device.

Scene numbering was confirmed against a device rather than taken from the document, which contradicts itself about it. `tools/README.md` has the evidence and the field layout of the scene settings, which the probe tool can read out without changing anything:

```
python3 tools/judo_rest_probe.py <ip> -p <password> --scenes
```

# Version 1.1.8
Two decoding corrections for the i-soft PRO family, checked against what the Judo app shows for the same device.

* The software version has a numeric third component on this family. The third byte is a printable letter on an i-soft (`6b1502` reads 2.21k) but a number on an i-soft PRO (`0C0001` reads 1.0.12). 1.1.1 dropped the byte when it was not printable, so `110401` showed as "1.04" where the Judo app shows **1.4.17**. All three forms now decode correctly.
* The device number is read big-endian. The i-soft PRO page of the API document is the only one whose example is not copy-pasted from another page, and `10D36F28` = 282292008 only works big-endian while every other page's example only works little-endian. Note this is not the alphanumeric "Geräte ID" the app shows - that is a different identifier, and neither reading of the number appears in it.

Still open: the app reports an operating time of 783 days where the device's own counter reads 521 (big-endian) or 2306 (little-endian). 521 is the number of days since the commissioning date the same device reports, to the day; 783 would predate it. See `tools/README.md` for the experiment that settles the byte order.

# Version 1.1.7
* The password field in the setup dialog no longer pre-fills the factory setting. Someone who set their own password on the connectivity module and clicks through the form used to store "Connectivity" silently; the entry then fails with 401 and nothing says why. The field is required now, and the factory setting is offered as a hint under it instead. The reconfigure dialog keeps pre-filling the stored password - a password the user set must never be replaced by a default.
* Diagnostics no longer redacts the user name. It is not a secret, and a wrong one was just as invisible as a wrong password.

# Version 1.1.6
* Reverts the re-authentication prompt from 1.1.5. Credentials are entered once when the integration is set up and stay in force until the user changes them through the reconfigure dialog; the integration must not ask for them again because the device had a bad night. A transient 401 - the module answered one whole nightly scan with 401 and was fine afterwards - would have pushed a credentials dialog at a password that was never wrong.
* What stays from 1.1.5 is the part that was actually useful: a 401 says so. The setup error now reads "Judo device refused the configured credentials" instead of "Cannot reach Judo device", which no longer sends you looking for a network problem. The entry keeps retrying like after any other failure.

# Version 1.1.5
* A 401 is now reported as what it is. Before, a refused password surfaced as "Cannot reach Judo device", which sends you looking for a network problem although the device is answering perfectly well. Setup now raises `ConfigEntryAuthFailed` and Home Assistant offers a re-authentication dialog to enter the credentials again.
* During normal operation a re-authentication is only requested after three consecutive scans that failed authentication from start to finish, so a single transient 401 does not pop a dialog. A transient 401 is still retried once.
* 1.1.4 also asked the base URL whenever a 401 came back, on the theory that it would make the module hand out a fresh session. That was speculative and tripled the requests of a failing scan, which risks driving a device that locks out after failed attempts further into it. Removed.

# Version 1.1.4
* A single REST call is retried once on a transient failure (timeout, connection error, HTTP 401/403/5xx). The connectivity module answered every command of one nightly scan with 401 and was fine again afterwards; without a retry that single hiccup took the whole scan down and put an error in the log. On 401 the base URL is touched first, which makes the module hand out a fresh session.
* This repository now publishes GitHub releases. Without them HACS tracks the default branch and labels the installed version with the short commit SHA instead of a version number.
* `hacs.json` carries a readable display name.

# Version 1.1.3
* `operating_time` now declares a `deadband` of 1 hour. The counter advances by 1/60 h every minute, so at a 60 s scan interval every single scan was a state change: ~1440 recorder rows a day for a number that is only interesting to the hour. Now ~23. Simulated over a week the reported value stayed within 15 minutes of the real counter - the deadband bounds the lag, it does not accumulate.
* `water_total` and `water_treated` deliberately keep no deadband: they resolve to one litre and change often while water runs, but that is the data the water dashboard needs.

# Version 1.1.2
* Items can now declare a `deadband`: a change smaller than that is not reported, so it produces neither a state change nor a recorder row. The deadband is measured against the last reported value rather than the last reading, so slow genuine drift still accumulates until it crosses the threshold - the value is quantised, not lost, and the reported value never lags by more than one deadband.
  * `salt_storage_mass`: 50 g. The scale wobbles by a gram or two while nothing is being used, which produced a state change on every single scan. 50 g is the step the entity can be set in anyway and far below the ~250 g one regeneration uses. Against a measured series this cut 11 events in 25 minutes down to 1.

# Version 1.1.1
Follow-up to 1.1.0, from testing against an i-soft PRO.

* `device_type` and `service_contact` had gone unavailable. The length check introduced in 1.1.0 was too strict for them: the device answers `FF00` with one byte and `5800` with fewer than the declared 16. The check now only applies exactly to numeric fields, where a short payload silently loses its high-order bytes; text takes whatever arrives. `device_type` is declared as the one byte it is.
* Because `device_type` failed, the device stayed on the fallback name "Judo Device". Device info is now pushed into the device registry once the values arrive, instead of only being read when an entity is added.
* `device_number` is decoded as a string, so it can no longer render as "2825589796.0" nor be recorded as a statistic.
* Diagnostics now reports the raw payload and the error of items that failed to decode - previously exactly the items you want to look at were the ones missing from it.

# Version 1.1.0
Stability and decoding fixes.

**Corrected values** - if you track these in statistics, the history before this version is wrong:
* `install_date` was decoded as a unix timestamp and reported a date in the 1970s. Command `0E00` is day / month / year, with the year big-endian. It is now a proper date sensor.
* `operating_days` read its counter little-endian and reported e.g. 2306 instead of 521 days.
* All sensors showed two decimals because the parameter was spelled `preciosion` instead of `precision`, so the configured precision never applied.
* `device_number` was a MEASUREMENT and was recorded as a statistic. It is an identifier now.
* The software version appended a replacement glyph when the firmware does not put a printable letter in the version bytes.
* A truncated answer from the device was decoded silently and produced a value off by orders of magnitude (e.g. 8.94 m3 instead of 1057.5 m3). Payloads are now length-checked and a bad answer makes the entity unavailable instead.

**Stability**
* Requests use aiohttp instead of blocking `requests` calls, share one session and are serialised with a lock, so a write no longer collides with a running scan.
* A scan stops at a time budget derived from the poll interval instead of being cancelled halfway through.
* Read errors raise `UpdateFailed`; an unreachable device raises `ConfigEntryNotReady` so HA retries instead of loading a broken integration.
* `logging.basicConfig()` no longer reconfigures the logging of the whole HA process.

**Multiple devices**
* The device postfix is now part of the unique ids and the device identifiers. Two config entries no longer overwrite each other's readings and no longer collapse into one device. Existing unique ids are migrated automatically.
* The config flow tests the connection, rejects a duplicate host and a postfix that is already in use.

**Entities**
* `operating_minutes`, `operating_hours` and `operating_days` were three sensors for three fields of one counter, so "operating hours" only ever showed the 0..23 remainder. They are replaced by a single `operating_time` sensor in hours (TOTAL_INCREASING). The three old entities are removed from the registry automatically on upgrade.

**Diagnostics**
* The raw payloads moved from the entity attributes into the diagnostics download (device page -> three dots -> "Download diagnostics"). In the attributes they changed on every scan, which wrote a new recorder row per entity per scan.

# Version 1.0.3
Added control for changing salt mass. The control shows the current salt mass. When refilling, the mass that was refilled has to be added to the shown mass.

# judo_rest_api
Home Assistant integration to connect to judo water treatment directly via REST API based on this documentation:
https://judo.eu/app/uploads/2024/11/API-KOMMANDOZEILEN.pdf
Some more basic info can be found here: https://judo.eu/app/downloads/files/de/8203521/manuals/1702574_202405.pdf

Please have a look here to learn more about the communication module that provides the REST API:

https://judo.eu/produkte/connectivity-modul-wlan/

# Judo_rest_api

This integration lets you monitor and control your Judo water treatment device locally through it's REST API.
![image](https://github.com/user-attachments/assets/50a6e267-7844-46cf-a449-fa1fdc747504)





## Installation

### HACS (manually add Repository)

Add this repository to HACS.
* In the HACS GUI, select "Custom repositories"
* Enter the following repository URL: https://github.com/OStrama/judo_rest_api
* Category: Integration
* After adding the integration, restart Home Assistant.
* Now press the button "Add Integration" in Configuration -> Integrations to install it in Home assistant.
* Now under Configuration -> Integrations, "Judo REST API" should be available.

### Manual install

Create a directory called `judo_rest_api` in the `<config directory>/custom_components/` directory on your Home Assistant
instance. Install this component by copying all files in `/custom_components/judo_rest_api/` folder from this repo into the
new `<config directory>/custom_components/judo_rest_api/` directory you just created.

This is how your custom_components directory should look like:

```bash
custom_components
├── judo_rest_api
│   ├── __init__.py
│   ├── ...
│   ├── ...
│   ├── ...
│   └── sensor.py  
```

Note: `tools/` in this repository holds a bench script for dumping the raw answers of a device. It is not part of the integration and does not need to be copied.
## Configuration
![image](https://github.com/user-attachments/assets/36f25cdd-d969-4b80-bdf8-bdedd86e57ad)


The only mandatory parameters are:
* The IP-Address of your Judo water treatment device. The port should be ok at default (80) unless you changed it in the configuration of the connectivity module.
* The user name. The default value of the connectivity module is "admin". You can change it on the web interface of the connectivity module
* The password. The default value of the connectivity module is "Connectivity". You can change it on the web interface of the connectivity module

The "Device Postfix" has a default value of "". It can be used to add multiple devices to one home assistant. For compatibility this should be left empty on your first device. If you want to add another device, use a name that helps to identify the devices - each entry needs its own postfix, the config flow rejects a duplicate.
The "Scan interval" determines how often the REST API is polled. The default value is every 60 seconds, the minimum is 10. Too small values will cause more timeouts: the connectivity module answers one request at a time and the integration reads about 15 commands per scan.


# Disclaimer
The developers of this integration are not affiliated with Judo. They have created the integration as open source in their spare time on the basis of publicly accessible information. 
The use of the integration is at the user's own risk and responsibility. The developers are not liable for any damages arising from the use of the integration.


More coming soon to this theater ;-)
