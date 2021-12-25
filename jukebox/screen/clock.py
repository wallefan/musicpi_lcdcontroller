from . import Screen, on_button_pressed, on_encoder_tick
from ..util import Buttons
import time

COLORS = ((0,0),(0,1),(0.25,1),(0.5,1),(0.75,1))

class Clock(Screen):
    def __init__(self, display, next_screen):
        super().__init__(display, next_screen)

        self.seconds_shown = False
        self.blinking = False
        self.twenty_four_hour = False
        self.color = 0
        self.brightness = 0

    def on_switched_to(self):
        self.display.lcd.set_color(*COLORS[self.color])
        self.display.clear()
        self.show_time()
        self.brightness = int(self.display.lcd.backlight_brightness * 256)

    def show_time(self):
        t = time.time()
        index = (self.twenty_four_hour) << 2 | (self.seconds_shown) << 1 | (self.blinking and t % 1 > 0.5)
        format = ('%I:%M %p', '%I %M %p', '%I:%M:%S %p', '%I %M %S %p',
                  '%H:%M',    '%H %M',    '%H:%M:%S',    '%H %M %S')[index]
        string = time.strftime(format)
        self.display.write(0, string.center(16))
        self.display.call_later(0.5 - t % 0.5, self.show_time)

    @on_button_pressed(Buttons.PAUSE)
    def toggle_blink(self):
        self.blinking = not self.blinking

    @on_button_pressed(Buttons.REPEAT)
    def toggle_24hr(self):
        self.twenty_four_hour = not self.twenty_four_hour

    @on_button_pressed(Buttons.SHUFFLE)
    def toggle_seconds(self):
        self.seconds_shown = not self.seconds_shown

    @on_button_pressed(Buttons.PREVIOUS)
    def previous_color(self):
        self.color -= 1
        self.color %= len(COLORS)
        self.display.lcd.set_color(*COLORS[self.color])

    @on_button_pressed(Buttons.NEXT)
    def next_color(self):
        self.color += 1
        self.color %= len(COLORS)
        self.display.lcd.set_color(*COLORS[self.color])

    @on_encoder_tick(1)
    def adjust_brightness(self, n):
        self.brightness = max(0, min(256, self.brightness+n))
        self.display.lcd.set_backlight_brightness(self.brightness/256)
        self.display.lcd.set_color(*COLORS[self.color])
