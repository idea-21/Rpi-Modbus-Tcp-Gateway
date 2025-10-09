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
SERVER_IP = "192.168.10.1" #192.168.181.220 & 192.168.10.1
SERVER_PORT = 502
UNIT_ID = 1
READ_INTERVAL_S = 1
RECONNECT_DELAY_S = 5

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
                continue  # 跳过本次循环的剩余部分，直接进入下一次重连尝试
            else:
                log.info("Connection successful! Starting data acquisition.")

        # --- 2. 如果连接成功，则读取数据 ---
        try:
            # 读取离散量输入 (Discrete Inputs)
            rr_di = client.read_discrete_inputs(address=0, count=3, device_id=UNIT_ID)
            if rr_di.isError():
                log.error(f"Error reading discrete inputs: {rr_di}. Closing connection to force reconnect.")
                client.close()  #当读取失败时，关闭连接，以便下次循环时自动重连
                continue

            # 处理离散量数据
            red_str = "ON" if rr_di.bits[0] else "OFF"
            yellow_str = "ON" if rr_di.bits[1] else "OFF"
            green_str = "ON" if rr_di.bits[2] else "OFF"
            print(f"--- Lights Status ---\n"
                  f"Red: {red_str}, Yellow: {yellow_str}, Green: {green_str}")

            # 读取保持寄存器 (Holding Registers)
            rr_hr = client.read_holding_registers(address=20, count=6, device_id=UNIT_ID)
            if rr_hr.isError():
                log.error(f"Error reading holding registers: {rr_hr}. Closing connection to force reconnect.")
                client.close()
                continue
            
            # 处理保持寄存器数据
            all_registers = rr_hr.registers
            sg_value = client.convert_from_registers(
                all_registers[0:2], data_type=ModbusTcpClient.DATATYPE.FLOAT32, word_order="big"
            )
            hcl_value = client.convert_from_registers(
                all_registers[2:4], data_type=ModbusTcpClient.DATATYPE.FLOAT32, word_order="big"
            )
            h2o2_value = client.convert_from_registers(
                all_registers[4:6], data_type=ModbusTcpClient.DATATYPE.FLOAT32, word_order="big"
            )

            print(f"--- Etch Status ---\n"
                  f"S.G.: {sg_value:.4f}\n"
                  f"HCl: {hcl_value:.2f} %\n"
                  f"H2O2: {h2o2_value:.2f} %")
            print("-" * 30)

        except Exception as e:
            # 这个异常捕获的是更严重的通信错误，比如连接被对方重置
            log.error(f"A major communication exception occurred: {e}")
            client.close() # 发生任何严重错误时，都关闭连接，让主循环去处理重连

        # 在每次成功的读取后等待指定的时间
        time.sleep(READ_INTERVAL_S)


if __name__ == "__main__":
    run_resilient_modbus_client()