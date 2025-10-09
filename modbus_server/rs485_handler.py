# rs485_handler.py
import logging
import time
from pymodbus.client import ModbusSerialClient

log = logging.getLogger(__name__)


def update_from_rs485_loop(config, context, device_id):
    """
    循环轮询RS485设备并更新Modbus上下文。
    """
    log.info("Starting RS485 polling loop...")

    try:
        slave_id = config.getint('RS485', 'SlaveID')
        port = config.get('RS485', 'Port')
        baudrate = config.getint('RS485', 'Baudrate')
        poll_interval = config.getfloat('RS485', 'PollInterval')
        read_addr = config.getint('RS485', 'ReadAddress')
        read_count = config.getint('RS485', 'ReadCount')
        write_addr = config.getint('RS485', 'WriteAddress')
    except Exception as e:
        log.error(f"RS485 configuration error in config.ini: {e}")
        log.error("RS485 thread will not start.")
        return

    client = ModbusSerialClient(port=port, baudrate=baudrate, stopbits=1, bytesize=8, parity='N')

    while True:
        try:
            if not client.is_socket_open():
                log.warning("Connection lost. Attempting to reconnect...")
                if not client.connect():
                    log.error("Reconnect failed. Retrying in the next cycle.")
                    time.sleep(poll_interval)
                    continue

            result = client.read_holding_registers(address=read_addr, count=read_count, device_id=slave_id)

            if result.isError():
                log.error(f"Modbus RTU read error: {result}")
            else:
                context[device_id].setValues(3, write_addr, result.registers)
                log.info(f"Read from RS485 Slave {slave_id} and updated TCP Server: {result.registers}")

        except Exception as e:
            log.error(f"Error in RS485 polling loop: {e}")
            client.close()

        time.sleep(poll_interval)
    client.close()