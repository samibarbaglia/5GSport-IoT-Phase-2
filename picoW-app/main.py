import uasyncio as asyncio
import machine
import time

from config import (SW_0_PIN, SW_1_PIN, SW_2_PIN, LED1, LED2, LED3)

from wifi_connection import connect_wifi
from data_queue import state
from movesense_controller import movesense_task, blink_task, movesense_tasks
from led import Led
from mqtt import connect_mqtt, publish_to_mqtt
from bynav_GNSS import gnss_setup, gnss_task

led1 = Led(LED1)
led2 = Led(LED2)
led3 = Led(LED3)
button1 = machine.Pin(SW_1_PIN, machine.Pin.IN, machine.Pin.PULL_UP)
button2 = machine.Pin(SW_2_PIN, machine.Pin.IN, machine.Pin.PULL_UP)
button0 = machine.Pin(SW_0_PIN, machine.Pin.IN, machine.Pin.PULL_UP)

button_pressed = False
last_pressed_btn = 0
DEBOUNCE_MS = 500

#moi

def button_handler(pin):
    """IRQ callback for button presses."""
    global last_pressed_btn
    current_time = time.ticks_ms()
    if time.ticks_diff(current_time, last_pressed_btn) > DEBOUNCE_MS:
        if pin == button1:
            state.running_state = not state.running_state
        # print(f"Button pressed. Running state {state.running_state}")
        elif pin == button2:
            state.trigger_connecting_network = True
        elif pin == button0:
            state.trigger_ble_scan = True
        last_pressed_btn = current_time

async def running_state_on_led():
    """Control LED1 based on running state."""
    while True:
        led1.led_on() if state.running_state else led1.led_off()
        await asyncio.sleep_ms(500)

async def network_status_led():
    """Control LED2 to indicate network connection status."""
    while True:
        led2.led_on() if state.network_connection_state else led2.led_off()
        await asyncio.sleep_ms(600)

async def movesense_detect_status_led():
    """Led3 turn on if movesensor sensor is found"""
    while True:
        led3.led_on() if state.movesense_detect else led3.led_off()
        await asyncio.sleep_ms(600)

def read_picoW_unique_id():
    """Read the unique ID of the Pico W."""
    id_bytes = machine.unique_id()
    picoW_id = id_bytes.hex()
    return picoW_id

async def reconnect_network():
    """Check and reconnect to the network if triggered."""
    while True:
        if state.trigger_connecting_network:
            await connect_wifi()
            mqtt_client = await connect_mqtt()
            state.trigger_connecting_network = False
        await asyncio.sleep_ms(100)

async def main():
    try:
        picoW_id = read_picoW_unique_id()
        print(f"PicoW ID is {picoW_id}")
        await connect_wifi()
        sock, rtk_uart, gga = await gnss_setup()
        mqtt_client = await connect_mqtt()
        await asyncio.gather(
            movesense_task(picoW_id),
            # movesense_tasks(picoW_id),
            gnss_task(sock, rtk_uart, picoW_id),
            publish_to_mqtt(mqtt_client),
            # blink_task(),
            running_state_on_led(),
            network_status_led(),
            reconnect_network(),
            movesense_detect_status_led(),
        )
    except Exception as e:
        print(f"Error: {e}")
    finally:
        print("Shutting down event loop...")
        loop = asyncio.get_event_loop()
        loop.stop()  # Stops event loop gracefully

button1.irq(trigger=machine.Pin.IRQ_FALLING, handler=button_handler)
button2.irq(trigger=machine.Pin.IRQ_FALLING, handler=button_handler)
button0.irq(trigger=machine.Pin.IRQ_FALLING, handler=button_handler)


# Run the event loop manually
loop = asyncio.get_event_loop()
loop.create_task(main())

try:
    print("Start running...")
    loop.run_forever()
except KeyboardInterrupt:
    print("Stopped by user")
finally:
    loop.close()
