#pymodbus version: 3.11.3
#gpio version: 1.0.1

# server_with_gui.py
import tkinter as tk
from tkinter import font
import threading
import logging
import configparser
import time

# Modbus Imports
from pymodbus.server import StartTcpServer
from pymodbus.datastore import ModbusSequentialDataBlock, ModbusDeviceContext, ModbusServerContext

# Import your custom handlers
from gpio_handler import setup_gpio, update_gpio_loop
from rs485_handler import update_from_rs485_loop

# --------------------------------------------------------------------------- #
# Basic Configuration
# --------------------------------------------------------------------------- #
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(threadName)s - %(levelname)s - %(message)s')
log = logging.getLogger()

config = configparser.ConfigParser()
config.read('config.ini')

DEVICE_ID = config.getint('Modbus', 'UnitID', fallback=1)
SERVER_IP = config.get('TCPServer', 'Host', fallback='0.0.0.0')
SERVER_PORT = config.getint('TCPServer', 'Port', fallback=502)

# --------------------------------------------------------------------------- #
# GUI Application Class
# --------------------------------------------------------------------------- #
class ServerDisplayApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Modbus Server Status")
        self.root.attributes('-fullscreen', True)
        self.root.configure(bg='#1c1c1c')
        # Press ESC to exit fullscreen and close the application
        self.root.bind("<Escape>", lambda e: root.destroy()) 

        # --- Create data variables ---
        self.conductivity_var = tk.StringVar(value="--.-- uS/cm")
        self.concentration_var = tk.StringVar(value="-.---- %")
        self.status_var = tk.StringVar(value="Initializing...")
        self.red_light_var = tk.StringVar(value="OFF")
        self.yellow_light_var = tk.StringVar(value="OFF")
        self.green_light_var = tk.StringVar(value="OFF")

        # --- Setup fonts ---
        title_font = ("Helvetica", 20, "bold")
        value_font = ("Helvetica", 40, "bold")
        status_font = ("Helvetica", 10)

        # --- Main layout frame ---
        main_frame = tk.Frame(root, bg='#1c1c1c')
        main_frame.pack(expand=True, fill='both', padx=20, pady=20)

        # --- Light status section ---
#         lights_frame = tk.Frame(main_frame, bg='#1c1c1c')
#         lights_frame.pack(pady=20, fill='x', expand=True)
#         self.create_light_indicator(lights_frame, "Red Light", self.red_light_var, "red")
#         self.create_light_indicator(lights_frame, "Yellow Light", self.yellow_light_var, "#FFC300")
#         self.create_light_indicator(lights_frame, "Green Light", self.green_light_var, "green")

        # --- Measurement data display section ---
        data_frame = tk.Frame(main_frame, bg='#1c1c1c')
        data_frame.pack(pady=20, fill='x', expand=True)

        tk.Label(data_frame, text="Conductivity", font=title_font, fg='white', bg='#1c1c1c').pack()
        tk.Label(data_frame, textvariable=self.conductivity_var, font=value_font, fg='#00BFFF', bg='#1c1c1c').pack()
        
        tk.Label(data_frame, text="Concentration", font=title_font, fg='white', bg='#1c1c1c').pack(pady=(20, 0))
        tk.Label(data_frame, textvariable=self.concentration_var, font=value_font, fg='#32CD32', bg='#1c1c1c').pack()

        # --- Status Bar ---
        tk.Label(root, textvariable=self.status_var, font=status_font, fg='grey', bg='#1c1c1c', anchor='w').pack(side="bottom", fill="x", padx=10, pady=5)

    def create_light_indicator(self, parent, text, variable, color):
        frame = tk.Frame(parent, bg='#1c1c1c')
        frame.pack(side='left', expand=True)
        tk.Label(frame, text=text, font=("Helvetica", 16), fg='white', bg='#1c1c1c').pack()
        label = tk.Label(frame, textvariable=variable, font=("Helvetica", 24, "bold"), fg=color, bg='#1c1c1c', width=4)
        label.pack()

# --------------------------------------------------------------------------- #
# Main Execution Block
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    # 1. Initialize Modbus Data Store
    store = ModbusDeviceContext(
        di=ModbusSequentialDataBlock(0, [False] * 100),
        co=ModbusSequentialDataBlock(0, [False] * 100),
        hr=ModbusSequentialDataBlock(0, [0] * 100),
        ir=ModbusSequentialDataBlock(0, [0] * 100),
    )
    context = ModbusServerContext(devices={DEVICE_ID: store}, single=False)

    # 2. Create GUI window and variables
    log.info("Starting GUI...")
    root_window = tk.Tk()
    app = ServerDisplayApp(root_window)
    
    gui_variables = {
        'conductivity': app.conductivity_var,
        'concentration': app.concentration_var,
        'status': app.status_var,
        'red_light': app.red_light_var,
        'yellow_light': app.yellow_light_var,
        'green_light': app.green_light_var,
    }

    # 3. Setup and start GPIO handler thread
    log.info("Starting GPIO polling thread...")
    gpio_inputs = setup_gpio()
    gpio_thread = threading.Thread(
        target=update_gpio_loop,
        args=(context, DEVICE_ID, gpio_inputs, gui_variables), # pass GUI variables
        daemon=True,
        name="GPIO_Thread"
    )
    gpio_thread.start()

    # 4. Start RS485 handler thread
    log.info("Starting RS485 polling thread...")
    rs485_thread = threading.Thread(
        target=update_from_rs485_loop,
        args=(config, context, DEVICE_ID, gui_variables), # pass GUI variables
        daemon=True,
        name="RS485_Thread"
    )
    rs485_thread.start()

    # 5. Start Modbus TCP server (in a background thread)
    log.info(f"Starting Modbus TCP server on {SERVER_IP}:{SERVER_PORT}...")
    server_thread = threading.Thread(
        target=StartTcpServer,
        kwargs={'context': context, 'address': (SERVER_IP, SERVER_PORT)},
        daemon=True,
        name="Modbus_Server_Thread"
    )
    server_thread.start()

    # 6. Start GUI main loop (occupies the main thread)
    app.status_var.set("All services started, running...")
    root_window.mainloop()

    log.info("GUI closed. Program exiting.")