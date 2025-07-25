import machine
import time
import uasyncio as asyncio

import ubinascii
import usocket
import uselect
import json

from data_queue import gnss_queue, state
from password import NTRIP_CONFIG
from config import TX_PIN, RX_PIN, UART_BAUD_RATE


# UART setup (GPIO 4 and 5 on Raspberry Pi Pico WH, baud rate 115200)
uart1 = machine.UART(1, baudrate=UART_BAUD_RATE, tx=machine.Pin(TX_PIN), rx=machine.Pin(RX_PIN))

gnss_ready_event = asyncio.ThreadSafeFlag()

# PARSE GPGGA DATA FUNCTION
def parse_gpgga(sentence):
    parts = sentence.split(',')
    if parts[0] != "$GPGGA":
        return None
    try:
        fix_quality = int(parts[6])
        if fix_quality < 4:  # Accept only RTK fixes 4 or 5 (float and fixed)
            return None

        lat_raw = parts[2]
        lon_raw = parts[4]
        lat_dir = parts[3]
        lon_dir = parts[5]

        if not lat_raw or not lon_raw:
            return None

        lat_deg = int(lat_raw[:2])
        lat_min = float(lat_raw[2:])
        lat = lat_deg + (lat_min / 60)

        if lat_dir == 'S':
            lat = -lat

        lon_deg = int(lon_raw[:3])
        lon_min = float(lon_raw[3:])
        lon = lon_deg + (lon_min / 60)

        if lon_dir == 'W':
            lon = -lon

        return {
            "date": time.time(),
            "lat": lat,
            "lon": lon
        }

    except (ValueError, IndexError):
        return None


# FIND VALID COORDINATES FUNCTION
async def find_gga():
    print("Checking for GGA fix...")
    if uart1.any():
        print('sanity check')
        line = uart1.readline()
        print(line)
        if line and line.startswith(b"$GPGGA"):
            try:
                decoded = line.decode().strip()
                parsed = parse_gpgga(decoded)
                if parsed:
                    print("Valid GPGGA fix found:", decoded)
                    return decoded
                else:
                    print("No GGA fix:", decoded)
            except Exception as e:
                print("Decode error in find_gga:", e)
    await asyncio.sleep(0.5)
    return None


# MAIN GNSS TASK
async def gnss_task(picoW_id):
    # NTRIP authentication (Base64)
    auth = ubinascii.b2a_base64(
        f"{NTRIP_CONFIG['username_ntrip']}:{NTRIP_CONFIG['password_ntrip']}".encode()
    ).decode().strip()

    print("Waiting for valid GPGGA sentence...")
    gga = await find_gga()

    if not gga:
        print("GGA failed (90s timeout). Exiting GNSS task.")
        return  # Exit task gracefully

    print("GGA fix:", gga)

    # NTRIP GET request
    ntrip_request = (
        "GET /{} HTTP/1.1\r\n"
        "Host: {}\r\n"
        "Ntrip-Version: Ntrip/2.0\r\n"
        "User-Agent: MicroPython NTRIP Client\r\n"
        "Authorization: Basic {}\r\n"
        "Ntrip-GGA: {}\r\n"
        "\r\n"
    ).format(NTRIP_CONFIG['mountpoint'], NTRIP_CONFIG['host'], auth, gga)

    try:
        # Open TCP connection
        sock = usocket.socket()
        sock.connect((NTRIP_CONFIG['host'], NTRIP_CONFIG['port']))
        sock.send(ntrip_request.encode())

        while True:
            line = sock.readline()
            if not line or line == b'\r\n':
                break

        print("Connected to NTRIP caster, streaming RTCM data...")
    except Exception as e:
        print("Failed to connect to NTRIP caster:", e)
        return

    # Setup polling for RTCM socket
    poller = uselect.poll()
    poller.register(sock, uselect.POLLIN)
    last_gga_ms = time.ticks_ms()
    gnss_ready_event.set()

    while state.running_state:
        # Handle RTCM input
        events = poller.poll(0)
        for fileno, event in events:
            if event & uselect.POLLIN:
                try:
                    rtcm_data = sock.recv(512)
                    if rtcm_data:
                        uart1.write(rtcm_data)
                    else:
                        print("No RTCM data from caster, server closed connection?")
                        return
                except OSError as e:
                    print("Socket error:", e)
                    return

        # Read incoming GNSS data
        if uart1.any():
            nmea_line = uart1.readline()
            if nmea_line.startswith(b"$GPGGA"):
                now = time.ticks_ms()
                if time.ticks_diff(now, last_gga_ms) > 1000:
                    try:
                        sock.send(nmea_line)
                        last_gga_ms = now
                    except Exception as e:
                        print("Failed to send GGA to caster:", e)

                try:
                    nmea_str = nmea_line.decode()
                    result = parse_gpgga(nmea_str)
                    if result:
                        gnss_data = {
                            "Pico_ID": picoW_id,
                            "Timestamp": time.time(),
                            "Latitude": result['lat'],
                            "Longitude": result['lon'],
                        }
                        print(f"GNSS data: {gnss_data}")
                        gnss_queue.enqueue(gnss_data)
                        await asyncio.sleep_ms(1000)
                except Exception as e:
                    print("Error parsing/logging GNSS data:", e)

        await asyncio.sleep_ms(50)
