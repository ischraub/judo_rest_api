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
