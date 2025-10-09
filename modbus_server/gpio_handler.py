# gpio_handler.py
import logging
import time
from gpiozero import Button

log = logging.getLogger(__name__)

# GPIO引脚定义
RED_LIGHT_PIN = 17
YELLOW_LIGHT_PIN = 27
GREEN_LIGHT_PIN = 22


def setup_gpio():
    """初始化并返回GPIO输入对象"""
    try:
        red_input = Button(RED_LIGHT_PIN, pull_up=True)
        yellow_input = Button(YELLOW_LIGHT_PIN, pull_up=True)
        green_input = Button(GREEN_LIGHT_PIN, pull_up=True)
        log.info("GPIO setup complete.")
        return (red_input, yellow_input, green_input)
    except Exception as e:
        log.error(f"Failed to initialize GPIO. Running in simulation mode. Error: {e}")

        class MockButton:
            def __init__(self, state=False):
                self._state = state

            @property
            def is_pressed(self):
                return self._state

        return (MockButton(), MockButton(True), MockButton())


def update_gpio_loop(context, device_id, inputs):
    """
    循环读取GPIO状态并更新Modbus上下文。
    """
    log.info("Starting GPIO update loop...")
    red_light, yellow_light, green_light = inputs

    while True:
        try:
            is_red_on = red_light.is_pressed
            is_yellow_on = yellow_light.is_pressed
            is_green_on = green_light.is_pressed

            light_states = [is_red_on, is_yellow_on, is_green_on]
            context[device_id].setValues(2, 0, light_states)

            log.info(f"Updated Lights Status [R:{is_red_on}, Y:{is_yellow_on}, G:{is_green_on}]")
            time.sleep(1)

        except Exception as e:
            log.error(f"Error in GPIO update loop: {e}")
            time.sleep(5)