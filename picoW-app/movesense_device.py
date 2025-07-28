import time
import bluetooth
import uasyncio as asyncio
from micropython import const
from struct import unpack
import machine  
import json
from data_queue import ecg_queue, imu_queue, hr_queue, state


# GSP Service and Characteristic UUIDs
_GSP_SERVICE_UUID = bluetooth.UUID("34802252-7185-4d5d-b431-630e7050e8f0")
_GSP_WRITE_UUID = bluetooth.UUID("34800001-7185-4d5d-b431-630e7050e8f0")
_GSP_NOTIFY_UUID = bluetooth.UUID("34800002-7185-4d5d-b431-630e7050e8f0")

# Command IDs
_CMD_HELLO = const(0)
_CMD_SUBSCRIBE = const(1)
_CMD_UNSUBSCRIBE = const(2)


class MovesenseDevice:
    BYTES_PER_ELEMENT = 4

    def __init__(self, movesense_series, pico_id, imu_ref=99, hr_ref=98, ecg_ref=97):
        self.ms_series = str(movesense_series)
        self.picoW_id = str(pico_id)
        self.imu_ref = imu_ref
        self.hr_ref = hr_ref
        self.ecg_ref = ecg_ref
        self.connection = None
        self.sensor_service = None
        self.write_char = None
        self.notify_char = None

    def log(self, msg):
        print(f"[Movesense {self.ms_series}]: {msg}")

    async def connect_ble(self, device):
        try:
            self.log(f"Connecting to BLE device {device}...")
            self.connection = await device.connect(timeout_ms=10000)
        except asyncio.TimeoutError:
            self.log("Connection timeout")
            return
        self.log("Connected")

        try:
            self.sensor_service = await self.connection.service(_GSP_SERVICE_UUID)
            self.notify_char = await self.sensor_service.characteristic(_GSP_NOTIFY_UUID)
            self.write_char = await self.sensor_service.characteristic(_GSP_WRITE_UUID)
        except asyncio.TimeoutError:
            self.log("Timeout discovering services/characteristics")
            return

        if not self.sensor_service or not self.write_char or not self.notify_char:
            self.log("Required service/characteristics not found")
            return

        await self.notify_char.subscribe(notify=True)

    async def subscribe_sensor(self, sensor_type, sensor_rate=None):
        if sensor_type == "IMU9":
            cmd = bytearray([_CMD_SUBSCRIBE, self.imu_ref]) + bytearray(f"Meas/IMU9/{sensor_rate}", "utf-8")
            self.imu_sensor = sensor_type
        elif sensor_type == "IMU6":
            cmd = bytearray([_CMD_SUBSCRIBE, self.imu_ref]) + bytearray(f"Meas/IMU6/{sensor_rate}", "utf-8")
            self.imu_sensor = sensor_type
        elif sensor_type == "HR":
            cmd = bytearray([_CMD_SUBSCRIBE, self.hr_ref]) + bytearray("Meas/HR", "utf-8")
        elif sensor_type == "ECG":
            cmd = bytearray([_CMD_SUBSCRIBE, self.ecg_ref]) + bytearray(f"Meas/ECG/{sensor_rate}", "utf-8")
        else:
            self.log("Invalid sensor type")
            return
        
        self.log(f"Subscribing to {sensor_type} with command: {cmd.hex()}")
        await self.write_char.write(cmd)

    async def process_notification(self):
        self.log("Waiting for notifications...")

        while state.running_state and self.connection.is_connected():
            try:
                data = await self.notify_char.notified(timeout_ms=300)
                if data:
                    ref_code = data[1]
                    if ref_code == self.imu_ref:
                        self._process_imu_data(data)
                    elif ref_code == self.ecg_ref:
                        self._process_ecg_data(data)
                    elif ref_code == self.hr_ref:
                        self._process_hr_data(data)
                    else:
                        self.log("Unknown data received")
            except asyncio.TimeoutError:
                continue

    def _process_imu_data(self, data):
        sensor_count = 3 if self.imu_sensor == "IMU9" else 2
        sample_count = len(data[6:]) // MovesenseDevice.BYTES_PER_ELEMENT
        unpacked_data = list(unpack(f'<BBI{sample_count}f', data))
        timestamp = unpacked_data[2]
        sensordata = [round(v, 3) for v in unpacked_data[3:]]
        sensordata = list(zip(sensordata[::3], sensordata[1::3], sensordata[2::3]))
        samples_per_sensor = len(sensordata) // sensor_count
        json_data = {
            "Movesense_series": self.ms_series,
            "Pico_ID": self.picoW_id,
            "Timestamp_UTC": time.time(),
            "Timestamp_ms": timestamp,
            "ArrayAcc": [],
            "ArrayGyro": [],
            "ArrayMagn": []
        }
        for i in range(samples_per_sensor):
            if self.imu_sensor in ["IMU6", "IMU9"]:
                acc = sensordata[i]
                acc_dict = {"x": acc[0], "y": acc[1], "z": acc[2]}
                gyro = sensordata[i + samples_per_sensor]
                gyro_dict = {"x": gyro[0], "y": gyro[1], "z": gyro[2]}
                json_data["ArrayAcc"].append(acc_dict)
                json_data["ArrayGyro"].append(gyro_dict)
            if self.imu_sensor == "IMU9":
                magn = sensordata[i + samples_per_sensor * 2]
                magn_dict = {"x": magn[0], "y": magn[1], "z": magn[2]}
                json_data["ArrayMagn"].append(magn_dict)
        self.log(f"{self.imu_sensor} _json data {json_data}")
        imu_queue.enqueue(json_data)

    def _process_hr_data(self, data):
        unpacked_data = list(unpack('<BBfH', data))
        avg_hr = unpacked_data[2]
        rr_interval = unpacked_data[3]
        json_data = {
            "Movesense_series": self.ms_series,
            "Pico_ID": self.picoW_id,
            "Timestamp_UTC": time.time(),
            "average": avg_hr,
            "rrData": [rr_interval]
        }
        self.log(f"HR data {json_data}")
        hr_queue.enqueue(json_data)

    def _process_ecg_data(self, data):
        sample_count = len(data[6:]) // self.BYTES_PER_ELEMENT
        unpacked_data = list(unpack(f'<BBI{sample_count}i', data))
        ts = unpacked_data[2]
        sensordata = unpacked_data[3:]
        json_data = {
            "Movesense_series": self.ms_series,
            "Pico_ID": self.picoW_id,
            "Timestamp_UTC": time.time(),
            "Timestamp_ms": ts,
            "Samples": sensordata
        }
        self.log(f"ECG json data:{json_data}")
        ecg_queue.enqueue(json_data)

    async def disconnect_ble(self):
        unsub_cmds = [
            bytearray([_CMD_UNSUBSCRIBE, self.imu_ref]),
            bytearray([_CMD_UNSUBSCRIBE, self.hr_ref]),
            bytearray([_CMD_UNSUBSCRIBE, self.ecg_ref]),
        ]
        if self.connection and self.connection.is_connected():
            self.log("Unsubscribing from sensors...")
            for cmd in unsub_cmds:
                await self.write_char.write(cmd)
                await asyncio.sleep_ms(100)
            await self.connection.disconnect()
            self.log("Disconnected")
