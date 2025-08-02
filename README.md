# 🌐 Metropolia x Nokia 5G Sport Project (IoT)

This project was the second phase of Metropolia UAS' 5G Sport project for Nokia. It integrates a **Movesense device** and a **Bynav M10 module** with a **Raspberry Pi Pico WH**, forming an IoT system that collects movement and GNSS data and forwards it to an MQTT broker over Wi-Fi. 

**Phase 2** added new GNSS functionality for better location accuracy by replacing DFRobot TEL0157 with Bynav M10. The respository for [Phase 1 can be found here](https://github.com/hannahhoang2704/IoTSport-IceHockey-Tracker).

---

## 📱 movesense-device-app

Firmware application for the Movesense device.

### 🔧 Description

The application utilizes the GATT SensorData protocol to communicate with a client device (Raspberry Pi Pico WH). It includes a movement detection feature and implements power-saving behavior:

- If no movement is detected and BLE connection is lost for 60 seconds, the Movesense device enters PowerOff mode to conserve battery.
- The device automatically wakes from PowerOff when:
  - Movement is detected, or
  - A BLE connection is re-established.

---

## 🧠 picoW-app

Firmware application for the Raspberry Pi Pico WH.

### 🔧 Description

The Pico WH functions as both a microcontroller, an IoT gateway, and RTK bridge, performing the following tasks:

- Connects to the Movesense device using the GATT SensorData service to retrieve sensor data.
- Reads location data from a GNSS module (Bynav M10).
- Connects to caster to send location data to VRS + forwards RTK correction data from VRS back to Bynav.
- Forwards combined data to a pre-configured MQTT broker over Wi-Fi.

Tested on MicroPython firmware v1.22.

### 🧠 MicroPython firmware v1.22

The BLE stack is re-configured with built firmware `micropython-v1.22-blestack.uf2`, allowing the Pico WH to connect to up to 3 peripherals simultaneously with GATT protocol.

### 📦 Required MicroPython Packages

- `micropython-umqtt.simple`
- `micropython-umqtt.robust`

### 🔗  RTK and NTRIP connectivity

The project requires the usage of [FINPOS RTK-service](https://www.maanmittauslaitos.fi/en/finpos/rtk) provided by **The National Land Survey of Finland** (fin. Maanmittauslaitos). Create a user on the service and apply for a **testing** licence. Approval takes around 30 minutes and the licence is valid for 3 months at a time. 

### 🎛 Features & Usability

| Button | Function                                                |
| ------ | ------------------------------------------------------- |
| `sw_0` | Scan for available Movesense BLE devices                |
| `sw_1` | Start/stop sensor data collection and MQTT transmission |
| `sw_2` | Reconnect to Wi-Fi and the MQTT broker                  |