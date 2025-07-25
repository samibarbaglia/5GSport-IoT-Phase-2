import uasyncio as asyncio
from umqtt.robust import MQTTClient
from data_queue import ecg_queue, hr_queue, imu_queue, gnss_queue, state
from password import MQTT_CONFIG

own_mqtt_broker_enabled = True

_MQTT_CLIENT_ID = b'raspberrypi-picow'

IMU_TOPIC = "sensors/imu"
ECG_TOPIC = "sensors/ecg"
HR_TOPIC = "sensors/hr"
GNSS_TOPIC = "sensors/gnss"

async def connect_mqtt():
    try:
        print("Connecting MQTT broker...")
        if own_mqtt_broker_enabled:
            mqtt_client = MQTTClient(client_id=_MQTT_CLIENT_ID,
                                     server=MQTT_CONFIG['server'],
                                     port=MQTT_CONFIG['port'],
                                     user=MQTT_CONFIG['username'],
                                     password=MQTT_CONFIG['password'])
        else:
            mqtt_client = MQTTClient(client_id=_MQTT_CLIENT_ID,
                                    server=MQTT_CONFIG['server'],
                                    port=MQTT_CONFIG['port'],
                                    user=MQTT_CONFIG['username'],
                                    password=MQTT_CONFIG['password'],
                                    keepalive=True,
                                    ssl=True,
                                    ssl_params=MQTT_CONFIG['ssl_params'])
        mqtt_client.connect()
    except Exception as e:
        print(f"Error connecting to MQTT: {e}")
        state.network_connection_state = False
        return None
    else:
        if mqtt_client is not None:
            state.network_connection_state = True
            print("MQTT broker connected")
        else:
            state.network_connection_state = False
            print(f"MQTT broker is {mqtt_client}")
    return mqtt_client

async def publish_to_mqtt(mqtt_client):
    """Task to publish data from queues to MQTT broker."""
    while True:
        if mqtt_client:
            if not imu_queue.is_empty():
                imu_data = imu_queue.dequeue()
                mqtt_client.publish(IMU_TOPIC, str(imu_data).encode())
            if not ecg_queue.is_empty():
                ecg_data = ecg_queue.dequeue()
                mqtt_client.publish(ECG_TOPIC, str(ecg_data).encode())
            if not hr_queue.is_empty():
                hr_data = hr_queue.dequeue()
                mqtt_client.publish(HR_TOPIC, str(hr_data).encode())
            if not gnss_queue.is_empty():
                gnss_data = gnss_queue.dequeue()
                mqtt_client.publish(GNSS_TOPIC, str(gnss_data).encode())
        await asyncio.sleep_ms(100)
