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
