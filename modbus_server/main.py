# main.py
import threading
import logging
import configparser

from pymodbus.server import StartTcpServer
from pymodbus.datastore import ModbusSequentialDataBlock, ModbusDeviceContext, ModbusServerContext

from gpio_handler import setup_gpio, update_gpio_loop
from rs485_handler import update_from_rs485_loop
from simulation_handler import update_simulated_data_loop

# --------------------------------------------------------------------------- #
# 基本配置
# --------------------------------------------------------------------------- #
logging.basicConfig(level=logging.INFO)
log = logging.getLogger()

config = configparser.ConfigParser()
config.read('config.ini')

DEVICE_ID = config.getint('Modbus', 'UnitID', fallback=1)
SERVER_IP = "0.0.0.0"
SERVER_PORT = 502

# --------------------------------------------------------------------------- #
# 主程序
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    # 1. 初始化Modbus数据存储
    store = ModbusDeviceContext(
        di=ModbusSequentialDataBlock(0, [False] * 100),
        co=ModbusSequentialDataBlock(0, [False] * 100),
        hr=ModbusSequentialDataBlock(0, [0] * 100),
        ir=ModbusSequentialDataBlock(0, [0] * 100),
    )
    context = ModbusServerContext(devices={DEVICE_ID: store}, single=False)

    # 2. 设置并启动GPIO处理线程
    gpio_inputs = setup_gpio()
    gpio_thread = threading.Thread(
        target=update_gpio_loop,
        args=(context, DEVICE_ID, gpio_inputs),
        daemon=True
    )
    gpio_thread.start()

    # 3. 启动RS485处理线程
    rs485_thread = threading.Thread(
        target=update_from_rs485_loop,
        args=(config, context, DEVICE_ID),
        daemon=True
    )
    rs485_thread.start()

    try:
        simulation_enabled = config.getboolean('Simulation', 'Enable', fallback=False)
    except (configparser.NoSectionError, configparser.NoOptionError):
        simulation_enabled = False

#     if simulation_enabled:
#         log.info("Simulation mode is enabled. Starting simulation thread.")
#         simulation_thread = threading.Thread(
#             target=update_simulated_data_loop,
#             args=(config, context, DEVICE_ID),
#             daemon=True,
#             name="Simulation_Thread"
#         )
#         simulation_thread.start()
#     else:
#         log.info("Simulation mode is disabled.")

    # 4. 启动Modbus TCP服务器 (主线程)
    log.info(f"Starting Modbus TCP server on {SERVER_IP}:{SERVER_PORT}...")
    StartTcpServer(context=context, address=(SERVER_IP, SERVER_PORT))