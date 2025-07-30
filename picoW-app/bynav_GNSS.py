import machine
import usocket
import time
import ubinascii
import uselect
import os
import uasyncio as asyncio
import json

from config import TX_PIN, RX_PIN, UART_BAUD_RATE
from password import NTRIP_CONFIG
from data_queue import state, gnss_queue


async def gnss_setup():
    print("Initializing GNSS sensor...")
    
    # UART setup (GPIO 4 and 5 on Raspberry Pi Pico WH)
    rtk_uart = machine.UART(1, baudrate=UART_BAUD_RATE, tx=machine.Pin(TX_PIN), rx=machine.Pin(RX_PIN))
    auth = ubinascii.b2a_base64(f"{NTRIP_CONFIG['username_ntrip']}:{NTRIP_CONFIG['password_ntrip']}".encode()).decode().strip()
    gga = None
    i = 0
    
    # Waits for sensor to connect to satellites (valid GPGGA fix is =! 0)
    while True:
        if rtk_uart.any():
            initial_GPGGA = rtk_uart.readline()
            if initial_GPGGA.startswith(b"$GPGGA"):
                try:
                    gga_str = initial_GPGGA.decode().strip()
                    fields = gga_str.split(',')
                    fix_quality = fields[6]
                    # Check fix > 0 + lat and lon != empty
                    if fix_quality != '0' and fields[2] != '' and fields[4] != '':
                        print("GNSS successfully connected")
                        gga = gga_str
                        break
                    else:
                        # print(f">> GGA {i} found but no coordinates:", gga_str)
                        i += 1
                except Exception:
                    pass
        await asyncio.sleep(0.5)

    # NTRIP request
    request = (
        "GET /{} HTTP/1.1\r\n"
        "Host: {}\r\n"
        "Ntrip-Version: Ntrip/2.0\r\n"
        "User-Agent: MicroPython NTRIP Client\r\n"
        "Authorization: Basic {}\r\n"
        "Ntrip-GGA: {}\r\n"
        "\r\n"
    ).format(NTRIP_CONFIG['mountpoint'], NTRIP_CONFIG['host'], auth, gga)

    # Ping opencater
    addr = usocket.getaddrinfo("opencaster.nls.fi", 2101)
    ip_address = addr[0][-1][0]

    # TCP connection to NTRIP caster
    sock = usocket.socket()
    # sock.connect((ip_address, NTRIP_CONFIG['port'])) # TO DO: Check IP functionality
    sock.connect(("195.156.69.210", NTRIP_CONFIG['port']))
    sock.send(request.encode())
    
    while True:
        line = sock.readline()
        if not line or line == b'\r\n':
            break
    print("Connected to NTRIP caster")
    return sock, rtk_uart, gga


def parse_gpgga(sentence):
    field = sentence.split(',')
    if field[0] != "$GPGGA":
        return None
    try:
        fix_quality = int(field[6])
        if fix_quality < 4:
            return None
        lat_raw = field[2]
        lon_raw = field[4]
        lat_dir = field[3]
        lon_dir = field[5]
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
            "lat": lat,
            "lon": lon,
            "fix_quality": fix_quality
        }
    except (ValueError, IndexError):
        return None


async def gnss_task(sock, rtk_uart, picoW_id):
    poller = uselect.poll()
    poller.register(sock, uselect.POLLIN)
    last_gga_ms = time.ticks_ms()
    # print("Polling")

    # Receive RTK correction data
    while True:
        events = poller.poll(10)
        for fileno, event in events:
            # print('Poll test 1')
            if event & uselect.POLLIN:
                try:
                    rtk_data = sock.recv(512)
                    if rtk_data:
                        rtk_uart.write(rtk_data)
                        # print("RTK data forwarded via UART')
                    else:
                        print("No RTK correction data")
                        return 
                except OSError as e:
                    print("Socket error:", e)
                    return
                
        # Send new coordinates to NTRIP every 1 sec
        if rtk_uart.any():
            rtk_line = rtk_uart.readline()
            if rtk_line.startswith(b"$GPGGA"):
                now = time.ticks_ms()
                if time.ticks_diff(now, last_gga_ms) > 1000:
                    try:
                        sock.send(rtk_line)
                        last_gga_ms = now
                    except Exception as e:
                        print("FAILED to send new coordinates:", e)
                        
                # Parse and send data to queue        
                try:
                    rtk_str = rtk_line.decode()
                    result = parse_gpgga(rtk_str)
                    if result:
                        gnss_data = {
                            "Pico_ID": picoW_id,
                            "Date": time.time(),
                            "Latitude": result['lat'],
                            "Longitude": result['lon'],
                            }
                        if gnss_data:
                            print(f"GNSS data: {gnss_data}")
                            gnss_queue.enqueue(gnss_data)
                except Exception as e:
                    print("Parsing or logging error:", e)
        await asyncio.sleep_ms(50)

