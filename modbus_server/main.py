# =========================================================================== #
#                                                                             #
#                      实时监控与Modbus TCP服务器应用                         #
#                                                                             #
# =========================================================================== #
#
# 项目简介:
# 本程序是一个集成了图形用户界面（GUI）的Modbus TCP服务器。其核心功能是：
# 1. 通过RS485串口从外部传感器（数字型四电极式电导率传感器）读取实时数据。
# 2. 将读取到的数据存储在Modbus寄存器中，并通过TCP/IP网络提供给Modbus客户端（SCADA）。
# 3. 在本地显示一个全屏的GUI界面，实时展示传感器数据、历史趋势图，并根据数据提供操作建议。
# 4. 整体架构采用多线程，确保GUI的流畅性不受硬件通信延迟的影响。
#
# 依赖版本:
# pymodbus: 3.11.3  (用于实现Modbus TCP服务器)
# gpio: 1.0.1       (用于读取树莓派等的GPIO引脚信号，可选)
#
# 文件结构:
# - main.py:            本文件，主程序入口，负责GUI和线程调度。
# - rs485_handler.py:   负责通过RS485与传感器通信的逻辑。
# - gpio_handler.py:    (可选) 负责处理GPIO输入的逻辑。
# - simulation_handler  (可选) 在没有传感器时模拟传感器数据。
# - config.ini:         配置文件，用于设置服务器IP、端口、Modbus设备ID等，方便修改而无需改动代码。
#
# =========================================================================== #

# --- 核心库导入 ---
import tkinter as tk
from tkinter import font
import threading
import logging
import configparser
import time
from collections import deque
import queue
from datetime import datetime, timedelta

# --- 图表库导入 ---
import matplotlib
matplotlib.use("TkAgg")  # 指定Matplotlib使用Tkinter作为其后端渲染引擎
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.dates as mdates

# --- Modbus库导入 ---
from pymodbus.server import StartTcpServer
from pymodbus.datastore import ModbusSequentialDataBlock, ModbusDeviceContext, ModbusServerContext

# --- 自定义模块导入 ---
# 这两个文件包含了与具体硬件交互的底层代码，将硬件逻辑与主程序界面逻辑解耦。
#from gpio_handler import setup_gpio, update_gpio_loop
from rs485_handler import update_from_rs485_loop      # 负责轮询RS485传感器

# =========================================================================== #
#                               全局常量与配置                                #
# =========================================================================== #

# --- 界面与数据处理相关常量 ---
CHART_UPDATE_INTERVAL = 1000  # 图表刷新频率（毫秒），1000ms = 1秒
DATA_LOGGING_INTERVAL_SECONDS = 60 # 历史数据记录频率（秒），每60秒在图表中增加一个新点
TOTAL_HISTORY_HOURS = 1 # 图表显示多长时间范围内的数据
# 根据以上参数计算图表最多能容纳的数据点数量，防止内存无限增长
MAX_HISTORICAL_POINTS = int((TOTAL_HISTORY_HOURS * 3600) / DATA_LOGGING_INTERVAL_SECONDS)

# --- 业务逻辑相关常量（阈值）---
# 这些值定义了“正常”、“过高”、“过低”的状态，用于生成操作建议。
IDEAL_CONDUCTIVITY = 12500 # 理想电导率 (已取消)
UPPER_LIMIT_COND = 15000   # 电导率上限 (已取消)
LOWER_LIMIT_COND = 10000   # 电导率下限 (已取消)
IDEAL_CONCENTRATION = 1.0  # 理想浓度
UPPER_LIMIT_CONC = 1.2     # 浓度上限，超过此值则建议添加纯水
LOWER_LIMIT_CONC = 0.8     # 浓度下限，低于此值则建议添加碳酸钠

# =========================================================================== #
#                                 初始化设置                                  #
# =========================================================================== #

# --- 日志系统配置 ---
# 配置日志格式，方便调试。日志会包含时间、线程名、日志级别和具体信息。
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(threadName)s - %(levelname)s - %(message)s')
log = logging.getLogger()

# --- 配置文件加载 ---
# 从 'config.ini' 文件中读取配置。
config = configparser.ConfigParser()
config.read('config.ini')

# 从配置文件中获取具体参数，如果文件中没有，则使用 fallback 提供的默认值。
DEVICE_ID = config.getint('Modbus', 'UnitID', fallback=1)          # Modbus从站ID
SERVER_IP = config.get('TCPServer', 'Host', fallback='0.0.0.0')    # Modbus服务器监听的IP地址, '0.0.0.0'表示监听所有网络接口
SERVER_PORT = config.getint('TCPServer', 'Port', fallback=5020)    # Modbus服务器监听的端口

# =========================================================================== #
#                            图形用户界面 (GUI) 主类                            #
# =========================================================================== #
class ServerDisplayApp:
    """
    这个类封装了GUI的所有元素和逻辑。
    它负责创建窗口、显示数据、绘制图表，并与后台线程进行数据同步。
    """
    def __init__(self, root, data_queue):
        """
        类的构造函数，在创建类的实例时被调用。负责所有初始化工作。
        - root: Tkinter的主窗口对象。
        - data_queue: 一个线程安全的队列，用于从后台线程（RS485）接收数据。
        """
        self.root = root
        self.data_queue = data_queue
        self.root.title("Modbus Server Status")
        self.root.attributes('-fullscreen', True)  # 设置窗口全屏显示
        self.root.configure(bg='#1c1c1c')          # 设置背景色为深灰色
        self.root.bind("<Escape>", lambda e: root.destroy()) # 绑定'Esc'键为退出程序快捷键

        # --- 数据存储 ---
        # 使用deque（双端队列）存储历史数据，maxlen确保队列不会无限变长，自动丢弃最旧的数据。
        self.conductivity_data = deque(maxlen=MAX_HISTORICAL_POINTS)
        self.concentration_data = deque(maxlen=MAX_HISTORICAL_POINTS)

        # 用于临时存储从队列中获取的最新值，以便记录到历史数据中
        self.last_conductivity_value = None
        self.last_concentration_value = None

        # --- Tkinter动态变量 ---
        # StringVar是Tkinter的特殊变量，当它的值改变时，绑定到它的GUI组件会自动更新显示内容。
        self.conductivity_var = tk.StringVar(value="--.-- uS/cm")
        self.concentration_var = tk.StringVar(value="-.---- %")
        self.status_var = tk.StringVar(value="Initializing...")
        self.advice_var = tk.StringVar(value="Waiting for data...")

        # --- 启动GUI的周期性任务 ---
        # 这些方法会使用Tkinter的 `after` 机制来定时执行，从而实现界面的动态更新，而不会阻塞主线程。
        self.log_data_point() # 开始定期记录历史数据点
        self.create_widgets() # 创建界面上的所有静态组件
        self.update_chart()   # 开始定期刷新图表
        self.process_queue()  # 开始定期检查并处理数据队列data_queue

    def process_queue(self):
        """
        核心方法：处理来自后台线程的数据。
        它以非阻塞方式从队列中取出数据，并更新界面上的StringVar，从而触发界面刷新。
        """
        try:
            # 循环处理队列中的所有消息，直到队列为空
            while not self.data_queue.empty():
                message = self.data_queue.get_nowait() # get_nowait()不会阻塞，如果队列为空会抛出异常
                # 消息格式是一个元组，例如 ('conductivity', 12500)
                key, value = message

                # 根据key更新对应的变量和UI
                if key == 'conductivity':
                    self.conductivity_var.set(f"{value:.2f} uS/cm")
                    self.last_conductivity_value = value
                elif key == 'concentration':
                    self.concentration_var.set(f"{value:.4f} %")
                    self.last_concentration_value = value
                    self.update_advice(value) # 收到新浓度值后，立即更新操作建议
        except queue.Empty:
            # 如果队列为空，get_nowait()会抛出此异常
            pass
        finally:
            # 无论是否处理了数据，都在100ms后再次调用自己，形成一个持续的轮询循环。
            self.root.after(100, self.process_queue)

    def log_data_point(self):
        """
        定期将最新的传感器读数存入历史数据队列，用于绘制趋势图。
        这个方法的执行频率由 DATA_LOGGING_INTERVAL_SECONDS 控制。
        """
        now = datetime.now() # 获取当前时间戳

        # 只有在已经接收到有效数据时才记录
        if self.last_conductivity_value is not None:
            self.conductivity_data.append((now, self.last_conductivity_value))

        if self.last_concentration_value is not None:
            self.concentration_data.append((now, self.last_concentration_value))

        # 安排下一次执行
        self.root.after(DATA_LOGGING_INTERVAL_SECONDS * 1000, self.log_data_point)

    def create_widgets(self):
        """
        创建并布局GUI界面上的所有静态组件。
        这个方法只在初始化时调用一次。
        """
        # --- 主体布局 ---
        # 使用Grid布局管理器，将窗口分为左右两部分
        main_frame = tk.Frame(self.root, bg='#1c1c1c')
        main_frame.pack(expand=True, fill='both', padx=20, pady=20)
        main_frame.grid_rowconfigure(0, weight=1)
        main_frame.grid_columnconfigure(0, weight=1) # 左侧数据面板，占据1份宽度
        main_frame.grid_columnconfigure(1, weight=3) # 右侧图表面板，占据3份宽度，显得更大

        # --- 左侧数据面板 ---
        left_panel = tk.Frame(main_frame, bg='#1c1c1c')
        left_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 20))

        # --- 右侧图表面板 ---
        right_panel = tk.Frame(main_frame, bg='#1c1c1c')
        right_panel.grid(row=0, column=1, sticky="nsew")

        # --- 定义字体样式 ---
        title_font = ("Helvetica", 20, "bold")
        value_font = ("Helvetica", 40, "bold")
        status_font = ("Helvetica", 10)
        advice_font = ("WenQuanYi Zen Hei", 24, "bold")

        # --- 在左侧面板中创建数据显示区 ---
        data_frame = tk.Frame(left_panel, bg='#1c1c1c')
        data_frame.pack(pady=20, fill='x', expand=True)

        # 电导率显示
        tk.Label(data_frame, text="Conductivity", font=title_font, fg='white', bg='#1c1c1c').pack()
        tk.Label(data_frame, textvariable=self.conductivity_var, font=value_font, fg='#00BFFF', bg='#1c1c1c').pack()

        # 浓度显示
        tk.Label(data_frame, text="Concentration", font=title_font, fg='white', bg='#1c1c1c').pack(pady=(20, 0))
        tk.Label(data_frame, textvariable=self.concentration_var, font=value_font, fg='#32CD32', bg='#1c1c1c').pack()

        # 分隔线
        separator = tk.Frame(data_frame, height=2, bg="grey", bd=0)
        separator.pack(fill='x', pady=40, padx=20)

        # 操作建议显示
        tk.Label(data_frame, text="建议", font=title_font, fg='white', bg='#1c1c1c').pack()
        self.advice_label = tk.Label(data_frame, textvariable=self.advice_var, font=advice_font, fg='yellow', bg='#1c1c1c')
        self.advice_label.pack(pady=10)

        # 在右侧面板创建图表
        self.create_chart(right_panel)

        # --- 状态栏 ---
        # 位于窗口底部，用于显示程序运行状态
        tk.Label(self.root, textvariable=self.status_var, font=status_font, fg='grey', bg='#1c1c1c', anchor='w').pack(side="bottom", fill="x", padx=10, pady=5)

    def create_chart(self, parent):
        """
        初始化Matplotlib图表并将其嵌入到Tkinter窗口中。
        - parent: 放置图表的Tkinter父组件（right_panel）。
        """
        self.fig = Figure(figsize=(8, 6), dpi=100)
        self.fig.patch.set_facecolor('#1c1c1c') # 设置图表外部背景色

        # 创建主坐标轴(ax1)用于显示电导率
        self.ax1 = self.fig.add_subplot(111)
        # 创建共享X轴的次坐标轴(ax2)用于显示浓度，这样两条曲线就可以使用不同的Y轴刻度
        self.ax2 = self.ax1.twinx()

        # --- 美化坐标轴样式 (ax1 - 电导率) ---
        self.ax1.set_facecolor('#2a2a2a') # 设置绘图区域背景色
        self.ax1.tick_params(axis='x', colors='white') # X轴刻度颜色
        self.ax1.tick_params(axis='y', colors='white') # Y轴刻度颜色
        for spine in self.ax1.spines.values(): # 边框颜色
            spine.set_color('white')
        self.ax1.title.set_color('white') # 标题颜色
        self.ax1.xaxis.label.set_color('white') # X轴标签颜色
        self.ax1.yaxis.label.set_color('#00BFFF') # Y轴标签颜色 (蓝色)

        # --- 美化坐标轴样式 (ax2 - 浓度) ---
        self.ax2.tick_params(axis='y', colors='#32CD32') # Y轴刻度颜色 (绿色)
        for spine in self.ax2.spines.values(): # 边框颜色
            spine.set_color('white')
        self.ax2.yaxis.label.set_color('#32CD32') # Y轴标签颜色 (绿色)

        # --- 将Matplotlib图表嵌入Tkinter ---
        self.canvas = FigureCanvasTkAgg(self.fig, master=parent)
        self.canvas.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self.canvas.draw()

    def update_chart(self):
        """
        定期刷新图表上的数据曲线。
        这个方法会被周期性调用，以反映最新的历史数据。
        """
        self.ax1.clear() # 清空主坐标轴
        self.ax2.clear() # 清空次坐标轴

        # --- 绘制电导率曲线 ---
        if self.conductivity_data:
             timestamps, values = zip(*self.conductivity_data)
             self.ax1.plot(timestamps, values, label="Conductivity", color="#00BFFF", linewidth=2)

        # --- 绘制浓度曲线 ---
        if self.concentration_data:
            timestamps_c, values_c = zip(*self.concentration_data)
            self.ax2.plot(timestamps_c, values_c, label = "Concentration", color="#32CD32", linewidth=2)

        # --- 绘制浓度阈值参考线 ---
        self.ax2.axhline(y=UPPER_LIMIT_CONC, color='magenta', linestyle='--', label=f"Cond_upper: {UPPER_LIMIT_CONC}")
        self.ax2.axhline(y=LOWER_LIMIT_CONC, color='cyan', linestyle='--', label=f"Cond_lower: {LOWER_LIMIT_CONC}")
        self.ax2.axhline(y=IDEAL_CONCENTRATION, color='orange', linestyle=':', label=f"Cond_ideal: {IDEAL_CONCENTRATION}")

        # --- 设置图表样式 ---
        current_date = datetime.now().strftime('%Y-%m-%d')
        self.ax1.set_title(
            f"Historical Data Trend - {current_date} (Last {TOTAL_HISTORY_HOURS} hours)",
            color='white'
        )
        self.ax1.set_ylabel("Conductivity (uS/cm)", color='#00BFFF')
        self.ax2.set_ylabel("Concentration (%)", color='#32CD32')
        self.ax1.grid(True, linestyle='--', alpha=0.3) # 显示网格线，Alpha通道：透明度
        # --- 格式化X轴的时间显示 ---
        self.ax1.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
        self.fig.autofmt_xdate() # 自动旋转日期标签以防重叠

        # 设置X轴的显示范围为固定的历史时长
        end_time = datetime.now()
        start_time = end_time - timedelta(hours=TOTAL_HISTORY_HOURS)
        self.ax1.set_xlim(start_time, end_time)

        # --- 动态调整Y轴范围 ---
        # 自动调整Y轴的显示范围，确保所有数据点和参考线都在可视范围内，并留出一些边距。
        if self.conductivity_data:
            all_cond_values = [item[1] for item in self.conductivity_data]
            min_val = min(min(all_cond_values), LOWER_LIMIT_COND)
            max_val = max(max(all_cond_values), UPPER_LIMIT_COND)
            self.ax1.set_ylim(min_val * 0.95, max_val * 1.05)

        if self.concentration_data:
            all_conc_values = [item[1] for item in self.concentration_data]
            min_c = min(min(all_conc_values), LOWER_LIMIT_CONC)
            max_c = max(max(all_conc_values), UPPER_LIMIT_CONC)
            self.ax2.set_ylim(min_c - abs(min_c)*0.05, max_c + abs(max_c)*0.05)


        # --- 合并显示图例 ---
        lines1, labels1 = self.ax1.get_legend_handles_labels()
        lines2, labels2 = self.ax2.get_legend_handles_labels()
        legend = self.ax1.legend(lines1 + lines2, labels1 + labels2, loc='upper left')
        for text in legend.get_texts(): # 设置图例文本为白色
            text.set_color("white")

        # --- 最终绘制 ---
        self.fig.tight_layout() # 调整布局防止标签重叠
        self.canvas.draw()      # 将更新后的图表绘制到画布上

        # 安排下一次刷新
        self.root.after(CHART_UPDATE_INTERVAL, self.update_chart)

    def update_advice(self, concentration_value):
        """
        根据传入的浓度值，更新界面上的操作建议文本和颜色。
        """
        if concentration_value > UPPER_LIMIT_CONC:
            self.advice_var.set("浓度过高，请添加纯水")
            self.advice_label.config(fg='red') # 红色表示警报
        elif concentration_value < LOWER_LIMIT_CONC:
            self.advice_var.set("浓度过低，请添加碳酸钠")
            self.advice_label.config(fg='red') # 红色表示警报
        else:
            self.advice_var.set("运行正常，无需操作")
            self.advice_label.config(fg='#32CD32') # 绿色表示正常

# =========================================================================== #
#                                 程序主入口                                  #
# =========================================================================== #
if __name__ == "__main__":
    """
    执行入口。
    主要负责：
    1. 初始化Modbus数据存储区。
    2. 创建并启动所有后台线程（Modbus服务器，RS485数据采集）。
    3. 创建GUI实例并启动其主事件循环。
    """
    # --- 步骤 1: 初始化Modbus数据存储区 ---
    # 这里定义了Modbus服务器的内存布局，客户端可以读写这些区域。
    # di: 离散输入, co: 线圈, hr: 保持寄存器, ir: 输入寄存器。
    store = ModbusDeviceContext(
        di=ModbusSequentialDataBlock(0, [False] * 100),
        co=ModbusSequentialDataBlock(0, [False] * 100),
        hr=ModbusSequentialDataBlock(0, [0] * 100),
        ir=ModbusSequentialDataBlock(0, [0] * 100),
    )
    # context将设备ID和其数据存储区关联起来
    context = ModbusServerContext(devices={DEVICE_ID: store}, single=False)

    # --- 步骤 2: 创建线程间通信的队列 ---
    # 这个队列是后台线程向GUI线程发送数据的唯一通道，确保线程安全。
    data_queue = queue.Queue()

    # --- 步骤 3: 创建并初始化GUI ---
    log.info("Starting GUI...")
    root_window = tk.Tk() # 创建Tkinter根窗口
    app = ServerDisplayApp(root_window, data_queue) # 创建GUI应用

    # --- 步骤 4: 启动RS485数据采集线程 ---
    # 这个线程会独立于GUI运行，在后台不断通过RS485读取传感器数据，
    # 并将数据放入`data_queue`中。
    log.info("Starting RS485 polling thread...")
    rs485_thread = threading.Thread(
        target=update_from_rs485_loop, # 线程要执行的函数
        args=(config, context, DEVICE_ID, data_queue), # 传递给函数的参数
        daemon=True, # 设置为守护线程，这样主程序退出时该线程也会自动结束
        name="RS485_Thread" # 为线程命名，方便调试
    )
    rs485_thread.start() # 启动线程

    # --- 步骤 5: 启动Modbus TCP服务器线程 ---
    # 这个线程也独立于GUI运行，在后台监听指定的IP和端口，
    # 等待Modbus客户端的连接和请求。
    log.info(f"Starting Modbus TCP server on {SERVER_IP}:{SERVER_PORT}...")
    server_thread = threading.Thread(
        target=StartTcpServer, # 启动服务器的函数
        kwargs={'context': context, 'address': (SERVER_IP, SERVER_PORT)}, # 传递给函数的参数
        daemon=True,
        name="Modbus_Server_Thread"
    )
    server_thread.start()

    # --- 步骤 6: 启动GUI主循环 ---
    # 这是程序的主线程，它将停留在这里，负责处理所有GUI事件（如按钮点击、窗口刷新）。
    # `mainloop()`是一个阻塞调用，只有当窗口被关闭时，它才会返回。
    app.status_var.set("All services are up and running...")
    root_window.mainloop()

    # --- 程序结束 ---
    # 当用户关闭GUI窗口后，`mainloop()`返回，程序执行到这里。
    log.info("GUI closed. Exiting program...")