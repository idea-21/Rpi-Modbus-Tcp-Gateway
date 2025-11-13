#pymodbus version: 3.11.3
#gpio version: 1.0.1

# server_with_gui.py
import tkinter as tk
from tkinter import font
import threading
import logging
import configparser
import time
from collections import deque
import queue

import matplotlib
matplotlib.use("TkAgg")
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

# Modbus Imports
from pymodbus.server import StartTcpServer
from pymodbus.datastore import ModbusSequentialDataBlock, ModbusDeviceContext, ModbusServerContext

# Import your custom handlers
from gpio_handler import setup_gpio, update_gpio_loop
from rs485_handler import update_from_rs485_loop

CHART_DATA_POINTS = 100
CHART_UPDATE_INTERVAL = 1000
IDEAL_CONDUCTIVITY = 12500.0
UPPER_LIMIT_COND = 15000.0
LOWER_LIMIT_COND = 10000.0
IDEAL_CONCENTRATION = 1.0
UPPER_LIMIT_CONC = 1.2
LOWER_LIMIT_CONC = 0.8

# --------------------------------------------------------------------------- #
# Basic Configuration
# --------------------------------------------------------------------------- #
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(threadName)s - %(levelname)s - %(message)s')
log = logging.getLogger()

config = configparser.ConfigParser()
config.read('config.ini')

DEVICE_ID = config.getint('Modbus', 'UnitID', fallback=1)
SERVER_IP = config.get('TCPServer', 'Host', fallback='0.0.0.0')
SERVER_PORT = config.getint('TCPServer', 'Port', fallback=5020)

# --------------------------------------------------------------------------- #
# GUI Application Class
# --------------------------------------------------------------------------- #
class ServerDisplayApp:
    def __init__(self, root, data_queue):
        self.root = root
        self.data_queue = data_queue
        self.root.title("Modbus Server Status")
        self.root.attributes('-fullscreen', True)
        self.root.configure(bg='#1c1c1c')
        # Press ESC to exit fullscreen and close the application
        self.root.bind("<Escape>", lambda e: root.destroy())
        
        self.conductivity_data = deque(maxlen=CHART_DATA_POINTS)
        self.concentration_data = deque(maxlen=CHART_DATA_POINTS)

        # --- Create data variables ---
        self.conductivity_var = tk.StringVar(value="--.-- uS/cm")
        self.concentration_var = tk.StringVar(value="-.---- %")
        self.status_var = tk.StringVar(value="Initializing...")
        self.red_light_var = tk.StringVar(value="OFF")
        self.yellow_light_var = tk.StringVar(value="OFF")
        self.green_light_var = tk.StringVar(value="OFF")
        
        self.create_widgets()
        self.update_chart()
        self.process_queue()
        
    def process_queue(self):
        """
        Process messages from the data_queue in a thread-safe way.
        """
        try:
            while not self.data_queue.empty():
                message = self.data_queue.get_nowait()
                # Expected message format: a tuple ('key', value)
                key, value = message
                
                if key == 'conductivity':
                    self.conductivity_var.set(f"{value:.2f} uS/cm")
                elif key == 'concentration':
                    self.concentration_var.set(f"{value:.4f} %")
                elif key == 'status':
                    self.status_var.set(str(value))
                elif key == 'red_light':
                    self.red_light_var.set(str(value))
                elif key == 'yellow_light':
                    self.yellow_light_var.set(str(value))
                elif key == 'green_light':
                    self.green_light_var.set(str(value))
                
        except queue.Empty:
            pass
        finally:
            # Schedule the next check in 100ms
            self.root.after(100, self.process_queue)
    
    def create_widgets(self):
        main_frame = tk.Frame(self.root, bg='#1c1c1c')
        main_frame.pack(expand=True, fill='both', padx=20, pady=20)
        main_frame.grid_rowconfigure(0, weight=1)
        main_frame.grid_columnconfigure(0, weight=1) # Left side
        main_frame.grid_columnconfigure(1, weight=3) # Right side (chart) takes more space
        
        # --- Left panel for data and lights ---
        left_panel = tk.Frame(main_frame, bg='#1c1c1c')
        left_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 20))
        
        # --- Right panel for the chart ---
        right_panel = tk.Frame(main_frame, bg='#1c1c1c')
        right_panel.grid(row=0, column=1, sticky="nsew")
        
        # --- Setup fonts ---
        title_font = ("Helvetica", 20, "bold")
        value_font = ("Helvetica", 40, "bold")
        status_font = ("Helvetica", 10)

        # --- Light status section ---
#         lights_frame = tk.Frame(main_frame, bg='#1c1c1c')
#         lights_frame.pack(pady=20, fill='x', expand=True)
#         self.create_light_indicator(lights_frame, "Red Light", self.red_light_var, "red")
#         self.create_light_indicator(lights_frame, "Yellow Light", self.yellow_light_var, "#FFC300")
#         self.create_light_indicator(lights_frame, "Green Light", self.green_light_var, "green")

        # --- Measurement data display section ---
        data_frame = tk.Frame(left_panel, bg='#1c1c1c')
        data_frame.pack(pady=20, fill='x', expand=True)

        tk.Label(data_frame, text="Conductivity", font=title_font, fg='white', bg='#1c1c1c').pack()
        tk.Label(data_frame, textvariable=self.conductivity_var, font=value_font, fg='#00BFFF', bg='#1c1c1c').pack()
        
        tk.Label(data_frame, text="Concentration", font=title_font, fg='white', bg='#1c1c1c').pack(pady=(20, 0))
        tk.Label(data_frame, textvariable=self.concentration_var, font=value_font, fg='#32CD32', bg='#1c1c1c').pack()

        self.create_chart(right_panel)
        # --- Status Bar ---
        tk.Label(self.root, textvariable=self.status_var, font=status_font, fg='grey', bg='#1c1c1c', anchor='w').pack(side="bottom", fill="x", padx=10, pady=5)

    def create_chart(self, parent):
        self.fig = Figure(figsize=(8, 6), dpi=100)
        self.fig.patch.set_facecolor('#1c1c1c') # Set figure background color

        #**********conductivity**********#
        self.ax1 = self.fig.add_subplot(111)
        
        self.ax2 = self.ax1.twinx()
         
        self.ax1.set_facecolor('#2a2a2a') # Set axes background color
        self.ax1.tick_params(axis='x', colors='white')
        self.ax1.tick_params(axis='y', colors='white')
        self.ax1.spines['bottom'].set_color('white')
        self.ax1.spines['top'].set_color('white') 
        self.ax1.spines['right'].set_color('white')
        self.ax1.spines['left'].set_color('white')
        self.ax1.title.set_color('white')
        self.ax1.xaxis.label.set_color('white')
        self.ax1.yaxis.label.set_color('#00BFFF')
        
        #***********concentration********#
        self.ax2.tick_params(axis='y', colors='#32CD32')
        self.ax2.spines['top'].set_visible(False)
        self.ax2.spines['bottom'].set_visible(False)
        self.ax2.spines['left'].set_visible(False)
        self.ax2.spines['right'].set_color('white')
        self.ax2.yaxis.label.set_color('#32CD32')
        
        self.canvas = FigureCanvasTkAgg(self.fig, master=parent)
        self.canvas.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self.canvas.draw()

    def update_chart(self):
        # Step 1: Get data from the StringVar
        try:
            conductivity_str = self.conductivity_var.get().split(' ')[0]
            conductivity_value = float(conductivity_str)
            self.conductivity_data.append(conductivity_value)
        except (ValueError, IndexError):
            pass
        
        try:
            concentration_str = self.concentration_var.get().split(' ')[0]
            concentration_value = float(concentration_str)
            self.concentration_data.append(concentration_value)
        except (ValueError, IndexError):
            pass
        
        # Step 2: Redraw the plot
        self.ax1.clear()
        self.ax2.clear()

        # Plot the main data line
        if self.conductivity_data:
             self.ax1.plot(list(self.conductivity_data), label="COND", color="#00BFFF", linewidth=2)
        
        # Plot the three horizontal lines
        self.ax1.axhline(y=UPPER_LIMIT_COND, color='red', linestyle='--', label=f"UPPER: {UPPER_LIMIT_COND}")
        self.ax1.axhline(y=LOWER_LIMIT_COND, color='green', linestyle='--', label=f"LOWER: {LOWER_LIMIT_COND}")
        self.ax1.axhline(y=IDEAL_CONDUCTIVITY, color='yellow', linestyle=':', label=f"IDEAL: {IDEAL_CONDUCTIVITY}")

        if self.concentration_data:
            self.ax2.plot(list(self.concentration_data), label = "Concentration", color="#32CD32", linewidth=2)
            
        self.ax2.axhline(y=UPPER_LIMIT_CONC, color='magenta', linestyle='--', label=f"Conc. Upper: {UPPER_LIMIT_CONC}")
        self.ax2.axhline(y=LOWER_LIMIT_CONC, color='cyan', linestyle='--', label=f"Conc. Lower: {LOWER_LIMIT_CONC}")
        self.ax2.axhline(y=IDEAL_CONCENTRATION, color='orange', linestyle=':', label=f"Conc. Ideal: {IDEAL_CONCENTRATION}")
        # Step 3: Style the plot
        self.ax1.set_title("On-time Chart", color='white')
        self.ax1.set_xlabel("Time (datapoints)", color='white')
        self.ax1.set_ylabel("Conductivity (uS/cm)", color='#00BFFF')
        self.ax2.set_ylabel("Concentration (%)", color='#32CD32')
        self.ax1.grid(True, linestyle='--', alpha=0.3)
        
        lines1, labels1 = self.ax1.get_legend_handles_labels()
        lines2, labels2 = self.ax2.get_legend_handles_labels()
        legend = self.ax1.legend(lines1 + lines2, labels1 + labels2, loc='upper left')
        for text in legend.get_texts():
            text.set_color("white")
        
        # Adjust Y-axis limits for better visibility
        if self.conductivity_data:
            min_val = min(min(self.conductivity_data), LOWER_LIMIT_COND)
            max_val = max(max(self.conductivity_data), UPPER_LIMIT_COND)
            self.ax1.set_ylim(min_val * 0.95, max_val * 1.05)
            
        if self.concentration_data:
            min_c = min(min(self.concentration_data), LOWER_LIMIT_CONC)
            max_c = max(max(self.concentration_data), UPPER_LIMIT_CONC)
            range_c = max_c - min_c
            if range_c < 0.001: range_c = 0.1
            self.ax2.set_ylim(min_c - range_c * 0.1, max_c + range_c * 0.1)

        # Step 4: Redraw canvas
        self.fig.tight_layout()
        self.canvas.draw()
        
        # Step 5: Schedule the next update
        self.root.after(CHART_UPDATE_INTERVAL, self.update_chart)

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
    
    data_queue = queue.Queue()

    # 2. Create GUI window and variables
    log.info("Starting GUI...")
    root_window = tk.Tk()
    app = ServerDisplayApp(root_window, data_queue)

    # 3. Setup and start GPIO handler thread
#     log.info("Starting GPIO polling thread...")
#     gpio_inputs = setup_gpio()
#     gpio_thread = threading.Thread(
#         target=update_gpio_loop,
#         args=(context, DEVICE_ID, gpio_inputs, gui_variables), # pass GUI variables
#         daemon=True,
#         name="GPIO_Thread"
#     )
#     gpio_thread.start()
    
    # 4. Start RS485 handler thread
    log.info("Starting RS485 polling thread...")
    rs485_thread = threading.Thread(
        target=update_from_rs485_loop,
        args=(config, context, DEVICE_ID, data_queue), # pass GUI variables
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
