from . import Display, RotaryEncoder, LCD
from .screen import Screen
from .screen.directory import Directory
import RPi.GPIO as gpio
from Adafruit_GPIO.SPI import SpiDev
from Adafruit_MCP3008 import MCP3008
import asyncio


if __name__ == '__main__':
    gpio.setmode(gpio.BCM)
    display = Display(
        LCD(d4=24, d5=23, d6=22, d7=27, rs=6, e=5,
            bl_red=18, bl_green=17, bl_blue=4  # backlight
            ),
        MCP3008(spi=SpiDev(0, 0)),
        RotaryEncoder(19, 20),
        rotary_switch=21,
    )
    try:
        main_menu = Directory('Main Menu', display)
        sub_menu  = Directory('Sub Menu', main_menu)
        test = Screen(display, sub_menu)
        sub_menu.children.append(('Test', test))
        display.switch_screen(main_menu)
        display.lcd.set_color(1, 1)
        asyncio.get_event_loop().run_forever()
    finally:
        gpio.cleanup()
