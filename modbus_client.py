import time
import logging
from pymodbus.client import ModbusTcpClient

# --------------------------------------------------------------------------- #
# Configure Logging
# --------------------------------------------------------------------------- #
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s')
log = logging.getLogger()
log.setLevel(logging.INFO)

# --------------------------------------------------------------------------- #
# Client Configuration
# --------------------------------------------------------------------------- #
SERVER_IP = "192.168.104.220" # 服务器的实际IP
SERVER_PORT = 502
UNIT_ID = 1
READ_INTERVAL_S = 1
RECONNECT_DELAY_S = 5

# --- MODBUS地址定义 ---
# 根据服务器的代码
ADDR_CONDUCTIVITY = 0  # 电导率开始地址
ADDR_CONCENTRATION = 2 # 浓度开始地址

def run_resilient_modbus_client():
    """
    Connects to the Modbus TCP server, reads data, and handles reconnections.
    """
    client = ModbusTcpClient(SERVER_IP, port=SERVER_PORT)

    while True:
        # --- 1. 检查和建立连接 ---
        if not client.is_socket_open():
            log.info(f"Socket is closed. Attempting to connect to {SERVER_IP}:{SERVER_PORT}...")
            if not client.connect():
                log.error(f"Connection failed. Retrying in {RECONNECT_DELAY_S} seconds...")
                time.sleep(RECONNECT_DELAY_S)
                continue
            else:
                log.info("Connection successful! Starting data acquisition.")

        # --- 2. 如果连接成功，则读取数据 ---
        try:
            # 读取离散量输入 (Discrete Inputs)
            rr_di = client.read_discrete_inputs(address=0, count=3, device_id=UNIT_ID)
            if rr_di.isError():
                log.error(f"Error reading discrete inputs: {rr_di}. Closing connection to force reconnect.")
                client.close()
                continue

            # 处理离散量数据
            red_str = "ON" if rr_di.bits[0] else "OFF"
            yellow_str = "ON" if rr_di.bits[1] else "OFF"
            green_str = "ON" if rr_di.bits[2] else "OFF"
            print(f"--- Lights Status ---\n"
                  f"Red: {red_str}, Yellow: {yellow_str}, Green: {green_str}")

            # 读取保持寄存器 (Holding Registers)
            # 我们需要从地址0开始，读取3个寄存器：
            # - 地址 0, 7: 存储32位浮点电导率
            # - 地址 2: 存储16位整数浓度
            rr_hr = client.read_holding_registers(address=ADDR_CONDUCTIVITY, count=3, device_id=UNIT_ID)
            if rr_hr.isError():
                log.error(f"Error reading holding registers: {rr_hr}. Closing connection to force reconnect.")
                client.close()
                continue
            
            # 将读取到的所有寄存器存入一个列表
            all_registers = rr_hr.registers
            
            # 1. 解码电导率 (Conductivity)
            # 提取前两个寄存器
            conductivity_registers = all_registers[0:2]
            conductivity_value = client.convert_from_registers(
                conductivity_registers, 
                data_type=ModbusTcpClient.DATATYPE.FLOAT32, 
                word_order="little"  # 字序是 little
            )

            # 2. 解码浓度 (Concentration)
            # 提取第三个寄存器，它是一个16位整数
            concentration_raw = all_registers[2]
            # 根据服务器逻辑，需要除以100.0来还原真实值
            concentration_value = concentration_raw / 100.0

            # 打印结果
            print(f"--- Concentration Status ---\n"
                  f"Conductivity: {conductivity_value:.2f} uS/cm\n"
                  f"Concentration: {concentration_value:.4f} %")
            print("-" * 30)

        except Exception as e:
            log.error(f"A major communication exception occurred: {e}")
            client.close()

        time.sleep(READ_INTERVAL_S)


if __name__ == "__main__":
    run_resilient_modbus_client()