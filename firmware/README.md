# ESP32 acquisition firmware

Two compile profiles share the same backend packet contract:

- esp32-sim: explicitly tagged synthetic data, no sensor hardware required.
- esp32-sensors: MAX30102 optical HR/SpO2, MPU6050 raw acceleration, AD8232 ECG, DS18B20 temperature, SSD1306 OLED and buzzer drivers.

Copy include/secrets.example.h to include/secrets.h and configure locally. The default sample file permits compilation without storing credentials. Do not upload sample credentials as a working configuration.

| Connection | ESP32 |
|---|---|
| MAX30102, MPU6050, OLED SDA/SCL | GPIO21 / GPIO22 |
| AD8232 analogue output | GPIO34 |
| AD8232 LO+ / LO- | GPIO25 / GPIO26 |
| DS18B20 data | GPIO4, appropriate pull-up to 3.3V |
| Buzzer control | GPIO27, use a suitable driver for the actual buzzer |

From the mediassist folder:

```powershell
.\\.venv\\Scripts\\python.exe -m pip install platformio
.\\.venv\\Scripts\\python.exe -m platformio run -d firmware
.\\.venv\\Scripts\\python.exe -m platformio run -d firmware -e esp32-sensors
```

Compilation does not require a connected board. Upload only after wiring and power checks: append -t upload to the chosen profile. Use battery-powered isolated acquisition hardware for body-connected ECG; a breadboard prototype is not a medical device.

ECG runs in a dedicated FreeRTOS task targeting 250 samples/s, independently of WiFi/MQTT reconnects. A two-frame queue drops old frames on overflow; timestamps expose gaps to the backend. The ADC representation is normalized around midscale, not calibrated millivolts. NTP must be synchronized before publishing. No fabricated physical readings are substituted for missing sensors or invalid temperatures/optical results. Lead loss sends a signal event and suppresses ECG frames.

MAX30102 uses the vendor four-second estimation algorithm; waveform quality, HR/SpO2 calibration and sample timing remain unverified without hardware. Acceleration is tagged raw (includes gravity); the server applies impact plus stillness detection. A local buzzer pulse is only a prototype impact indication. The DS18B20 reading is sensor temperature and cannot be assumed to equal core body temperature.

MQTT topics: mediassist/{device_id}/vitals, /ecg, /events. Use the included integrations/mqtt_bridge.py to authenticate ingestion. The default WiFiClient transport is for a private development broker; deployment needs TLS and per-device broker credentials. Neither provider connectivity nor physical hardware has been validated here.
