# Phase 9: firmware software gate

Both PlatformIO profiles compiled successfully on 27 October 2026:

| Profile | Build | Observed memory |
|---|---|---|
| esp32-sim | SUCCESS | Synthetic source tagged in every packet |
| esp32-sensors | SUCCESS | RAM 47,648 / 327,680 bytes; flash 826,561 / 1,310,720 bytes |

The physical profile contains MAX30102, MPU6050, AD8232, DS18B20, OLED and buzzer drivers. Shared I2C uses GPIO21/22; ECG uses GPIO34 with lead-off inputs GPIO25/26; temperature uses GPIO4; buzzer uses GPIO27.

The 250Hz acquisition task is independent of MQTT reconnects; frames have timestamps and a bounded queue. Missing/invalid physical measurements are withheld. NTP synchronization is required before publishing. Both profile flags and representative packet schemas are checked by backend/test_firmware_contract.py.

Compiler warnings originate in the pinned SparkFun I2C buffer macro and OneWire undef directives. They did not stop the two builds. Hardware calibration, timing measurements, power/wiring, body-safe isolation and broker connectivity remain untested: no board or sensors are available. See firmware/README.md before hardware activation.
