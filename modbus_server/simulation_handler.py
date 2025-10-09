# simulation_handler.py
import logging
import time
import random
from pymodbus.client import ModbusTcpClient

log = logging.getLogger(__name__)


def update_simulated_data_loop(config, context, device_id):
    """
    循环生成模拟的化学分析数据 (S.G., HCl, H2O2) 并更新Modbus上下文。
    """
    log.info("Starting simulated chemical data generation loop...")

    try:
        write_addr = config.getint('Simulation', 'WriteAddress', fallback=20)
        update_interval = config.getfloat('Simulation', 'UpdateInterval', fallback=1.0)
    except Exception as e:
        log.error(f"Simulation configuration error in config.ini: {e}")
        write_addr = 20
        update_interval = 1.0

    while True:
        try:
            # 1. 生成随机的模拟数据
            simulated_sg = round(random.uniform(1.10, 1.25), 4)
            simulated_hcl = round(random.uniform(30.0, 38.0), 2)
            simulated_h2o2 = round(random.uniform(30.0, 40.0), 2)

            # 2. 将浮点数转换为Modbus寄存器格式 (16-bit integers)

            payload_registers = []
            payload_registers.extend(
                ModbusTcpClient.convert_to_registers(
                    value=simulated_sg,
                    data_type=ModbusTcpClient.DATATYPE.FLOAT32
                )
            )
            payload_registers.extend(
                ModbusTcpClient.convert_to_registers(
                    value=simulated_hcl,
                    data_type=ModbusTcpClient.DATATYPE.FLOAT32
                )
            )
            payload_registers.extend(
                ModbusTcpClient.convert_to_registers(
                    value=simulated_h2o2,
                    data_type=ModbusTcpClient.DATATYPE.FLOAT32
                )
            )

            # 3. 将寄存器列表写入Modbus服务器的上下文中
            # 使用功能码 3 表示写入 Holding Registers
            context[device_id].setValues(3, write_addr, payload_registers)

            log.info(
                f"Updated Simulated Data -> "
                f"S.G.: {simulated_sg}, HCl: {simulated_hcl}%, H2O2: {simulated_h2o2}%"
            )

            time.sleep(update_interval)

        except Exception as e:
            log.error(f"Error in simulated data loop: {e}")
            time.sleep(5)