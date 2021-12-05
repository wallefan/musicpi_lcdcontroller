from . import Screen, on_button_pressed
from ..util import Buttons
import time

class Clock(Screen):
    def __init__(self, display, next_screen):
        super().__init__(display, next_screen)

        self.seconds_shown = False
        self.blinking = False
        self.twenty_four_hour = False

    def on_switched_to(self):
        self.display.clear()
        self.show_time()

    def show_time(self):
        t = time.time()
        index = (self.twenty_four_hour) << 2 | (self.seconds_shown) << 1 | (self.blinking and t % 1 < 0.5)
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
