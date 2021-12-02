from jukebox import Display, RotaryEncoder, LCD
from jukebox.screen import Screen
from jukebox.screen.directory import Directory
import pigpio
from Adafruit_GPIO.SPI import SpiDev
from Adafruit_MCP3008 import MCP3008
import asyncio


if __name__ == '__main__':
    pi = pigpio.pi('musicpi.local')
    print('pi connected')
    try:
        display = Display(
            pi,
            LCD(pi, d4=24, d5=23, d6=22, d7=27, rs=6, e=5,
                bl_red=18, bl_green=17, bl_blue=4  # backlight
                ),
            RotaryEncoder(pi, 19, 16),
            rotary_switch=21,
            adc_spi_channel=0,
            buttons_adc_channel=2,
        )
        main_menu = Directory('Main Menu', display)
        sub_menu  = Directory('Sub Menu', main_menu)
        class TestScreen(Screen):
            def on_switched_to(self):
                self.display.lcd.set_color(0.5, 1)
        test = TestScreen(display, sub_menu)
        sub_menu.children.append(('Test', test))
        display.switch_screen(main_menu)
        display.mainloop()  # run one iteration of the main loop and schedule the next one
        asyncio.get_event_loop().run_forever()
    finally:
        pi.stop()
