#numpy version: 2.3.4
#matplotlib version: 3.10.7

import matplotlib.pyplot as plt
import numpy as np # 用于科学计算

# 数据
cond = [7336.02, 12223.35, 9228.36, 9020.66, 9807.96, 11438.37, 12239.79, 
        8310.85, 10798.86, 12417.43, 8300, 11720.63, 11800.08, 11680.29, 
        11701.11, 11625.01, 11807.38, 11540.57, 11550.89, 12610.63, 12300.7, 12675.71, 12464.98, 12231.56, 12541.9, 12506.25, 11822.03, 11920.93, 11900.38, 12045.01, 11800.77, 11771.63, 11728.53, 11756.08, 11908.88, 11756.77, 11800.08, 11572.93, 11587, 11821.33, 11851.42, 11785.14, 11794.51, 11991.98, 9090, 9063, 11251.3, 11334.11, 12042.69, 11953.35, 11855.74]

conc = [0.53, 1.0176, 0.7208, 0.72, 0.8268, 0.975, 1.081, 0.61, 0.87, 
        1.02, 0.583, 0.961, 0.97, 0.96, 0.94, 0.93, 0.932, 0.975, 0.954, 0.975, 1.025, 0.98, 0.968, 0.947, 0.975, 0.975, 0.968, 0.968, 0.926, 0.989, 0.949, 0.982, 0.975, 0.947, 0.94, 0.968, 0.954, 0.947, 0.961, 0.954, 0.975, 0.975, 0.961, 0.947, 0.707, 0.693, 0.933, 0.94, 0.947, 0.954, 0.954]

# 1. 使用 numpy.polyfit 进行线性拟合，1 表示拟合为1次多项式（即直线）
#    它会返回直线的斜率 (slope) 和截距 (intercept)
slope, intercept = np.polyfit(cond, conc, 1)

# 2. 创建拟合直线的 x 和 y 坐标
#    我们只需要直线的两个端点就可以画出整条线
x_fit = np.array([min(cond), max(cond)])
y_fit = slope * x_fit + intercept

# 3. 打印出拟合的直线方程
print(f"拟合的直线方程为: y = {slope:.6f}x + {intercept:.6f}")

# --- 绘图代码 ---
plt.figure(figsize=(10, 7)) # 设置画布大小

# 绘制原始数据点的散点图
plt.scatter(cond, conc, color='blue', label='Original Data') 

# 绘制拟合出来的直线
plt.plot(x_fit, y_fit, color='red', linewidth=2, label=f'Fitted Line\ny = {slope:.6f}x + {intercept:.6f}')

# 添加标题和坐标轴标签
plt.title('Concentration vs. Conductivity with Linear Fit') # 图表标题
plt.xlabel('Conductivity (cond)') # X轴标签
plt.ylabel('Concentration (conc)') # Y轴标签
plt.grid(True) # 显示网格
plt.legend() # 显示图例

# 显示图像
plt.show()