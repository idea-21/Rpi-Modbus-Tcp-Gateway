# =========================================================================== #
#                                                                             #
#                         RS485 传感器数据处理器                              #
#                                                                             #
# =========================================================================== #
#
# 文件简介:
# 这个模块的核心职责是通过 Modbus RTU 协议与外部传感器进行通信。
# 它在一个独立的后台线程中运行，以固定的时间间隔轮询传感器，读取数据，
# 对数据进行处理和转换，然后将结果更新到 Modbus TCP 服务器的内存中，并发送给 GUI 线程。
#
# 主要功能:
# 1. 连接到指定的串口设备。
# 2. 定期向传感器发送 Modbus 读指令。
# 3. 解析传感器返回的原始数据 (32位浮点数)。
# 4. 根据电导率值，使用一个多次滴定实验验证的线性公式计算出碳酸钠浓度。
# 5. 将处理后的数据写入 Modbus TCP 服务器的上下文中，供客户端访问。
# 6. 将数据放入线程安全的队列中，供 GUI 线程消费和显示。
#
# =========================================================================== #

import logging
import time
import struct
from pymodbus.client import ModbusSerialClient

# 记录CSV日志
# import csv
# from datetime import datetime
# import os

# 获取一个专用于此模块的日志记录器，方便在主程序日志中区分来源
log = logging.getLogger(__name__)

def conductivity_to_concentration(conductivity):
    """
    根据电导率值 (uS/cm) 计算碳酸钠浓度 (%)。
    将物理测量值转换为有意义的化学浓度。
    
    Attention：如果更换传感器或测量介质，这个公式需要重新校准。

    历史校准公式 (保留作参考):
    Formula 1: y = 1.959077 + (-4705.243 - 1.959077) / (1 + (x / 3.141543) ** 1.034152)
    Formula 2: y = 1.488193 + (0.0005473823 - 1.488193)/(1 + (x/9185.638)^2.768677)
    Formula 3: y = 0.000093x + -0.140785
    Formula 4: y = 0.000091x + -0.122020
    Formula 5: y = 0.000091x + -0.120919
    Formula 6: y = 0.000091x + -0.122480
    Formula 7: y = 0.000091x + -0.120737
    # Formula 8 (当前使用): y = 0.000092x + -0.126115
    
    其中 x 是电导率 (uS/cm)，y 是浓度 (%)。
    """
    try:
        x = float(conductivity)

        # 1. 物理边界检查：电导率在物理上不应为负数。
        if x < 0:
            log.warning(f"Warning: Input conductivity is negative ({x}). Returning concentration 0.0.")
            return 0.0

        # 2. 应用当前有效的线性公式
        # 公式: y = 0.000092x - 0.126115
        concentration = 0.000092 * x - 0.126115
        
        # 3. 结果边界检查：浓度在实际应用中不应为负数。
        # 如果计算结果为负，说明电导率太低，可能处于传感器的测量下限或纯水状态，
        # 此时返回0是物理上有意义的做法。
        if concentration < 0:
            return 0.0
            
        return concentration

    except (ValueError, TypeError):
        # 处理输入值无法转换为数字的异常情况
        log.error(f"Error: Input value '{conductivity}' is not a valid number.")
        return 0.0
    except Exception as e:
        # 捕获其他未知错误，增加程序的健壮性
        log.error(f"Error calculating concentration for input {conductivity}: {e}")
        return 0.0
    
def update_from_rs485_loop(config, context, device_id, data_queue=None):
    """
    在一个无限循环中持续轮询RS485设备，并更新Modbus上下文和GUI数据队列。
    这个函数是整个RS485线程的执行体。

    参数:
    - config: 从 config.ini 加载的配置对象。
    - context: Modbus TCP 服务器(树莓派)的数据存储区。此函数会直接修改它。
    - device_id: Modbus TCP 服务器的设备ID。
    - data_queue: 线程安全的队列，用于将数据发送给GUI线程。
    """
    log.info("Starting RS485 polling loop thread...")

    # --- 1. 从配置文件加载RS485通信参数 ---
    try:
        slave_id = config.getint('RS485', 'SlaveID')             # RS485从站（传感器）的地址
        port = config.get('RS485', 'Port')                       # 串口设备名，如 'COM7' (Windows) 或 '/dev/ttyUSB0' (树莓派)
        baudrate = config.getint('RS485', 'Baudrate')            # 波特率
        poll_interval = config.getfloat('RS485', 'PollInterval') # 每次读取之间的时间间隔（秒）
        read_addr = config.getint('RS485', 'ReadAddress')        # 要读取的Modbus寄存器起始地址
        read_count = config.getint('RS485', 'ReadCount')         # 要读取的寄存器数量 (电导率是32位浮点数，占2个16位寄存器)
        write_addr = config.getint('RS485', 'WriteAddress')      # 要写入Modbus TCP服务器的电导率寄存器地址
        write_addr_conc = config.getint('RS485', 'WriteAddressConcentration') # 要写入Modbus TCP服务器的浓度寄存器地址
    except Exception as e:
        log.error(f"RS485 configuration error. Please check the config.ini file: {e}")
        log.error("RS485 thread will not be started.")
        return # 无法启动，直接退出函数

    # --- 2. 初始化Modbus RTU客户端 ---
    client = ModbusSerialClient(port=port, baudrate=baudrate, stopbits=1, bytesize=8, parity='N')
    is_configured = False # 一个标志，用于确保一次性配置只执行一次（设置温度补偿模式）
    data_point_counter = 0 # 简单的数据点计数器，用于日志输出，方便调试

    # --- 3. 主循环 ---
    while True:
        try:
            # --- 检查并维持连接 ---
            if not client.is_socket_open():
                log.warning("RS485 connection lost. Attempting to reconnect...")
                if not client.connect():
                    log.error("Reconnection failed. Will retry on the next cycle.")
                    time.sleep(poll_interval) # 等待一段时间再重试
                    continue # 跳过本次循环的剩余部分

            #******************************************#
            # --- 一次性设备配置块 ---
            # 设置温度补偿模式。
            if not is_configured:
                log.info("Performing one-time device configuration check...")
                try:
                    # 尝试读取温度补偿模式的当前值 (地址为32)
                    current_mode = client.read_holding_registers(address=32, count=1, unit=slave_id)
                    if current_mode.isError():
                        log.warning(f"Failed to read temperature compensation mode to check for configuration. Error: {current_mode}")
                    # 如果读取成功，并且当前值不是我们想要的1，那么就写入1
                    elif current_mode.registers[0] != 1:
                        log.info(f"Current temperature compensation mode is {current_mode.registers[0]}. Changing to 1.")
                        write_result = client.write_register(address=32, value=1, unit=slave_id)
                        if write_result.isError():
                            log.error(f"Failed to set temperature compensation mode. Error: {write_result}")
                        else:
                            log.info("Successfully set temperature compensation mode to 1.")
                    else:
                        log.info("Temperature compensation mode is already 1, no action required.")
                    
                    # 无论成功或失败，都将标志设为True，以防止重复尝试
                    is_configured = True
                    log.info("One-time device configuration check complete.")

                except Exception as config_e:
                    log.error(f"An error occurred during one-time configuration: {config_e}")
                    # 即使配置失败，也要设置标志，以避免连续重试阻塞主功能。
                    is_configured = True
            #******************************************#
            
            # --- 读取传感器数据 ---
            # 从指定的从站ID和寄存器地址读取数据
            result = client.read_holding_registers(address=read_addr, count=read_count, unit=slave_id)
            
            # --- 数据处理与更新 ---
            if result.isError():
                log.error(f"Modbus RTU read error: {result}")
            else:
                data_point_counter += 1
                raw_registers = result.registers # 获取原始的16位寄存器列表，例如 [reg1, reg2]
                log.info(f"[Data point #{data_point_counter}] Read from RS485 slave {slave_id}: {result.registers}")

                if len(raw_registers) == 2: # 确保我们收到了预期的两个寄存器
                    try:
                        # --- 核心数据转换：将两个16位寄存器合并成一个32位浮点数 ---
                        # 传感器使用大端序(Big-Endian)发送数据，意味着高位字节在前。
                        # `raw_registers[1]` 是高位，`raw_registers[0]` 是低位。
                        # 使用Python的 `struct` 模块来完成这个转换。
                        # '>HH': 将两个无符号短整型(H)按照大端序(>)打包成4个字节。
                        # '>f' : 将这4个字节按照大端序(>)解包成一个32位浮点数(f)。
                        packed_bytes = struct.pack('>HH', raw_registers[1], raw_registers[0])
                        conductivity_value = struct.unpack('>f', packed_bytes)[0]
                        log.info(f"Parsed conductivity: {conductivity_value:.2f} uS/cm")
                        
                        # --- 更新Modbus TCP服务器上下文 ---
                        # 1. 更新电导率 (原始寄存器值)
                        # 将从传感器读到的原始寄存器值直接写入TCP服务器的保持寄存器(功能码3)
                        context[device_id].setValues(3, write_addr, [raw_registers[0], raw_registers[1]])
                        
                        # 2. 计算并更新浓度
                        concentration_value = conductivity_to_concentration(conductivity_value)
                        log.info(f"Calculated concentration: {concentration_value:.4f} %")
                        
                        # 为了通过Modbus传输，将浮点数乘以一个系数（100）转换为整数。
                        concentration_register_value = int(concentration_value * 100)
                        
                        # 将计算出的浓度整数值写入TCP服务器的指定地址
                        context[device_id].setValues(3, write_addr_conc, [concentration_register_value])
                        log.info(f"Updated concentration value at TCP server address {write_addr_conc} to: {concentration_register_value} (representing {concentration_value:.2f} %)")

                        #**************************************************************#
                        # --- 将数据发送给GUI线程 ---
                        # 如果GUI队列存在，就把最新的数据放进去，供界面显示。
                        if data_queue:
                            data_queue.put(('conductivity', conductivity_value))
                            data_queue.put(('concentration', concentration_value))
                            data_queue.put(('status', f"RS485 OK | {time.strftime('%H:%M:%S')}"))
                        #**************************************************************#
                    except Exception as e:
                        log.error(f"Error converting registers to float or updating context: {e}")

        except Exception as e:
            # 捕获循环中的任何其他异常，防止线程崩溃
            log.error(f"Fatal error in RS485 polling loop: {e}")
            client.close() # 发生严重错误时尝试关闭连接

        # --- 循环延时 ---
        # 等待指定的时间间隔，然后开始下一次轮询
        time.sleep(poll_interval)

    # 保留关闭连接。
    client.close()