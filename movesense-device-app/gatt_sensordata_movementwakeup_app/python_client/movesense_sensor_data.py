# -*- coding: utf-8 -*-
"""
Python gatt_sensordata_app client example using the Bleak GATT client.

This example is based on the examples in the Bleak repo: https://github.com/hbldh/bleak
"""

import logging
import asyncio
import platform
import signal
from bleak import BleakClient
from bleak import _logger as logger
from bleak import discover
from functools import reduce
import struct
import sys

WRITE_CHARACTERISTIC_UUID = (
    "34800001-7185-4d5d-b431-630e7050e8f0"
)

NOTIFY_CHARACTERISTIC_UUID = (
    "34800002-7185-4d5d-b431-630e7050e8f0"
)


# https://stackoverflow.com/a/56243296
class DataView:
    def __init__(self, array, bytes_per_element=1):
        """
        bytes_per_element is the size of each element in bytes.
        By default we are assume the array is one byte per element.
        """
        self.array = array
        self.bytes_per_element = 1

    def __get_binary(self, start_index, byte_count, signed=False):
        integers = [self.array[start_index + x] for x in range(byte_count)]
        _bytes = [integer.to_bytes(
            self.bytes_per_element, byteorder='little', signed=signed) for integer in integers]
        return reduce(lambda a, b: a + b, _bytes)

    def get_uint_16(self, start_index):
        bytes_to_read = 2
        return int.from_bytes(self.__get_binary(start_index, bytes_to_read), byteorder='little')

    def get_uint_8(self, start_index):
        bytes_to_read = 1
        return int.from_bytes(self.__get_binary(start_index, bytes_to_read), byteorder='little')

    def get_uint_32(self, start_index):
        bytes_to_read = 4
        binary = self.__get_binary(start_index, bytes_to_read)
        return struct.unpack('<I', binary)[0]  # <f for little endian

    def get_float_32(self, start_index):
        bytes_to_read = 4
        binary = self.__get_binary(start_index, bytes_to_read)
        return struct.unpack('<f', binary)[0]  # <f for little endian



async def run_queue_consumer(queue: asyncio.Queue):
    while True:
        data = await queue.get()
        if data is None:
            logger.info(
                "Got message from client about disconnection. Exiting consumer loop..."
            )
            break
        else:
            # print to stdout
            print(data)

PACKET_TYPE_DATA = 2
PACKET_TYPE_DATA_PART2 = 3
ongoing_data_update = None

async def run_ble_client(end_of_serial: str, queue: asyncio.Queue):

    # Check the device is available
    devices = await discover()
    found = False
    address = None
    for d in devices:
        logger.debug("device:", d)
        if d.name and d.name.endswith(end_of_serial):
            logger.info("device found")
            address = d.address
            found = True
            break

    # This event is set if device disconnects or ctrl+c is pressed
    disconnected_event = asyncio.Event()

    def raise_graceful_exit(*args):
        disconnected_event.set()

    def disconnect_callback(client):
        logger.info("Disconnected callback called!")
        disconnected_event.set()

    async def notification_handler(sender, data):
        """Simple notification handler which prints the data received."""
        d = DataView(data)

        packet_type= d.get_uint_8(0)
        global ongoing_data_update
        # print("packet ", packet_type, ", ongoing:",ongoing_data_update)
        if packet_type == PACKET_TYPE_DATA:
            # print("PACKET_TYPE_DATA")
            # Store 1st part of the incoming data
            ongoing_data_update = d
        
        elif packet_type == PACKET_TYPE_DATA_PART2:
            # print("PACKET_TYPE_DATA_PART2. len:",len(data))
            
            # Create combined DataView that contains the whole data packet
            # (skip type_id + ref num of the data_part2)
            d = DataView( ongoing_data_update.array + data[2:])
            ongoing_data_update = None

            # Dig data from the binary
            # msg = "Data: offset: {}, len: {}".format(d.get_uint_32(2), 
            #     len(d.array))
            timestamp = d.get_uint_32(2)
            for i in range(0,8):
                # Interpolate timestamp within the data notification
                row_timestamp = timestamp + int(i*1000/104)
                ## IMU9 package starts with timestamp and then three arrays (len 8*4 bytes) of xyz's 
                ## Each "row" therefore starts (3*4 bytes after each other interleaving to acc, gyro and magn)
                offset = 6 + i * 3* 4
                skip = 3*8*4
                msg_row = "{},{:.2f},{:.2f},{:.2f},{:.2f},{:.2f},{:.2f},{:.2f},{:.2f},{:.2f}".format(row_timestamp
                                                            ,  d.get_float_32(offset)
                                                            ,  d.get_float_32(offset+4)
                                                            ,  d.get_float_32(offset+8)
                                                            ,  d.get_float_32(offset+skip+0)
                                                            ,  d.get_float_32(offset+skip+4)
                                                            ,  d.get_float_32(offset+skip+8)
                                                            ,  d.get_float_32(offset+2*skip+0)
                                                            ,  d.get_float_32(offset+2*skip+4)
                                                            ,  d.get_float_32(offset+2*skip+8))
                # queue message for later consumption (output)
                await queue.put(msg_row)

    if found:
        async with BleakClient(address, disconnected_callback=disconnect_callback) as client:

            # Add signal handler for ctrl+c
            signal.signal(signal.SIGINT, raise_graceful_exit)
            signal.signal(signal.SIGTERM, raise_graceful_exit)
           
            # Start notifications and subscribe to acceleration @ 13Hz
            logger.info("Enabling notifications")
            await client.start_notify(NOTIFY_CHARACTERISTIC_UUID, notification_handler)
            logger.info("Subscribing datastream")
            await client.write_gatt_char(WRITE_CHARACTERISTIC_UUID, bytearray([1, 99])+bytearray("/Meas/IMU9/104", "utf-8"), response=True)

            # Run until disconnect event is set
            await disconnected_event.wait()
            logger.info(
                "Disconnect set by ctrl+c or real disconnect event. Check Status:")

            # Check the conection status to infer if the device disconnected or crtl+c was pressed
            status = client.is_connected
            logger.info("Connected: {}".format(status))

            # If status is connected, unsubscribe and stop notifications
            if status:
                logger.info("Unsubscribe")
                await client.write_gatt_char(WRITE_CHARACTERISTIC_UUID, bytearray([2, 99]), response=True)
                logger.info("Stop notifications")
                await client.stop_notify(NOTIFY_CHARACTERISTIC_UUID)
            
            # Signal consumer to exit
            await queue.put(None)
            
            await asyncio.sleep(1.0)

    else:
        # Signal consumer to exit
        await queue.put(None)
        print("Sensor  ******" + end_of_serial, "not found!")



async def main(end_of_serial: str):

    queue = asyncio.Queue()
    client_task = run_ble_client(end_of_serial, queue)
    consumer_task = run_queue_consumer(queue)
    await asyncio.gather(client_task, consumer_task)
    logger.info("Main method done.")

if __name__ == "__main__":

    logging.basicConfig(level=logging.INFO)

    # print usage if command line arg not given
    if len(sys.argv)<2:
        print("Usage: python movesense_sensor_data <end_of_sensor_name>")
        exit(1);
    end_of_serial = sys.argv[1]

    asyncio.run(main(end_of_serial))