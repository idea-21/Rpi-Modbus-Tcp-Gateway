# rs485_handler.py
import logging
import time
import struct
from pymodbus.client import ModbusSerialClient
#import csv
#from datetime import datetime
#import os

log = logging.getLogger(__name__)

def conductivity_to_concentration(conductivity):
    """
    Calculates the sodium carbonate concentration (%) based on the conductivity value (uS/cm).
    The calculation uses a specified linear formula.
    
    Historical formulas:
    Formula 1: y = 1.959077 + (-4705.243 - 1.959077) / (1 + (x / 3.141543) ** 1.034152)
    Formula 2: y = 1.488193 + (0.0005473823 - 1.488193)/(1 + (x/9185.638)^2.768677)
    Formula 3: y = 0.000093x + -0.140785
    New calibration 1: y = 0.000091x + -0.122020
    New calibration 2: y = 0.000091x + -0.120919
    New calibration 3: y = 0.000091x + -0.122480
    New calibration 4: y = 0.000091x + -0.120737
    #New calibration 5 (currently active): y = 0.000092x + -0.126115
    
    Where x is the conductivity (uS/cm) and y is the concentration (%).
    """
    try:
        # To maintain consistency with the formula, assign conductivity to x
        # Also, ensure the input is a numeric type
        x = float(conductivity)

        # 1. Physical boundary check: conductivity should not be negative
        if x < 0:
            print(f"Warning: The input conductivity is negative ({x}). Returning concentration 0.0.")
            return 0.0

        # 2. Apply the active linear formula
        # Formula: y = 0.000092x - 0.126115
        concentration = 0.000092 * x - 0.126115
        
        # 3. Result boundary check: concentration should not be negative
        # If the calculated result is negative, it means the conductivity is too low
        # to be physically meaningful, so return 0.
        if concentration < 0:
            return 0.0
            
        return concentration

    except (ValueError, TypeError):
        # Handle the exception if the input value cannot be converted to a number
        print(f"Error: Input value '{conductivity}' is not a valid number.")
        return 0.0
    except Exception as e:
        print(f"An unknown error occurred while calculating concentration for input value {conductivity}: {e}")
        return 0.0


def update_from_rs485_loop(config, context, device_id):
    """
    Continuously polls the RS485 device and updates the Modbus context.
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
        write_addr_conc = config.getint('RS485', 'WriteAddressConcentration')
    except Exception as e:
        log.error(f"RS485 configuration error in config.ini: {e}")
        log.error("RS485 thread will not start.")
        return

    client = ModbusSerialClient(port=port, baudrate=baudrate, stopbits=1, bytesize=8, parity='N')
    is_configured = False
    data_point_counter = 0

    while True:
        try:
            if not client.is_socket_open():
                log.warning("Connection lost. Attempting to reconnect...")
                if not client.connect():
                    log.error("Reconnect failed. Retrying in the next cycle.")
                    time.sleep(poll_interval)
                    continue
                
            #******************************************#
            # One-time device configuration block
            if not is_configured:
                log.info("Performing one-time device configuration check...")
                try:
                    # Read the current value of the temperature compensation mode
                    current_mode = client.read_holding_registers(address=32, count=1, device_id=slave_id)
                    if current_mode.isError():
                        log.warning(f"Could not read temp comp mode to check if config is needed. Error: {current_mode}")
                    # If the read is successful and the current value is not 1, then write 1
                    elif current_mode.registers[0] != 1:
                        log.info(f"Current temp comp mode is {current_mode.registers[0]}. Changing to 1.")
                        write_result = client.write_register(address=32, value=1, device_id=slave_id)
                        if write_result.isError():
                            log.error(f"Failed to set temp comp mode. Error: {write_result}")
                        else:
                            log.info("Successfully set temp comp mode to 1.")
                    else:
                        log.info("Temp comp mode is already set to 1. No action needed.")
                    
                    # Regardless of success or failure, set the flag to True to prevent repeated attempts
                    is_configured = True
                    log.info("One-time device configuration check complete.")

                except Exception as config_e:
                    log.error(f"An error occurred during one-time configuration: {config_e}")
                    # Even if configuration fails, set the flag to avoid continuous retries
                    # which could block the main functionality.
                    is_configured = True
            #******************************************#

            result = client.read_holding_registers(address=read_addr, count=read_count, device_id=slave_id)
            
            result2 = client.read_holding_registers(address=32, count=1, device_id=slave_id)
            log.info(f"Device {slave_id}, Temp Comp Type: {result2.registers}")
            
            if result.isError():
                log.error(f"Modbus RTU read error: {result}")
            else:
                data_point_counter += 1
                raw_registers = result.registers
                log.info(f"[Data Point #{data_point_counter}] Read from RS485 Slave {slave_id} and updated TCP Server: {result.registers}")
                if len(raw_registers) == 2:
                    try:
                        # Big-Endian: The registers are combined to form a 32-bit float.
                        # raw_registers[1] is the high word, raw_registers[0] is the low word.
                        # Use the struct module for conversion.
                        # '>HH': Pack two unsigned short integers (H) into 4 bytes in big-endian order (>).
                        # '>f' : Unpack these 4 bytes into a 32-bit float (f) in big-endian order (>).
                        packed_bytes = struct.pack('>HH', raw_registers[1], raw_registers[0])
                        conductivity_value = struct.unpack('>f', packed_bytes)[0]
                        print(f"Conductivity: {conductivity_value:.2f} uS/cm")
                        
                        context[device_id].setValues(3, write_addr, [raw_registers[0], raw_registers[1]])
                        concentration_value = conductivity_to_concentration(conductivity_value)
                        log.info(f"Calculated Concentration: {concentration_value:.2f} %")
                        
                        #timestamp = datetime.now()
                        #log_concentration_to_csv(timestamp, conductivity_value, concentration_value)
                        
                        # Multiply by 100 to send as an integer (e.g., 1.23% -> 123)
                        concentration_register_value = int(concentration_value * 100)
                        
                        context[device_id].setValues(3, write_addr_conc, [concentration_register_value])
                        log.info(f"Updated context at addr {write_addr_conc} with concentration value: {concentration_register_value} (representing {concentration_value:.2f} %)")
                        
                        #**************************************************************#
                        if gui_vars:
                            gui_vars['conductivity'].set(f"{conductivity_value:.2f} uS/cm")
                            gui_vars['concentration'].set(f"{concentration_value:.4f} %")
                            gui_vars['status'].set(f"RS485 | OK | {time.strftime('%H:%M:%S')}")
                        #**************************************************************#
                            
                    except Exception as e:
                        log.error(f"Error converting registers to float: {e}")
        except Exception as e:
            log.error(f"Error in RS485 polling loop: {e}")
            client.close()

        time.sleep(poll_interval)
    client.close()