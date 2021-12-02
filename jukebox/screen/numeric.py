import time

from . import Screen, on_encoder_tick

custom_characters = bytes([
    # one column on
    0b10000,
    0b10000,
    0b10000,
    0b10000,
    0b10000,
    0b10000,
    0b10000,
    0b10000,
    # two columns on
    0b11000,
    0b11000,
    0b11000,
    0b11000,
    0b11000,
    0b11000,
    0b11000,
    0b11000,
    # three
    0b11100,
    0b11100,
    0b11100,
    0b11100,
    0b11100,
    0b11100,
    0b11100,
    0b11100,
    # four
    0b11110,
    0b11110,
    0b11110,
    0b11110,
    0b11110,
    0b11110,
    0b11110,
    0b11110,
    # five
    0b11111,
    0b11111,
    0b11111,
    0b11111,
    0b11111,
    0b11111,
    0b11111,
    0b11111,
])

class NumericInput(Screen):
    def __init__(self, display, previous_screen, title, getter, setter, value_min, value_max):
        super().__init__(display, previous_screen)
        self.getter = getter
        self.setter = setter
        self.min = value_min
        self.max = value_max
        self.title = title
        self._last_tick = None

    def on_switched_to(self):
        self.display.clear()
        self.display.write(0, self.title)
        # populate the custom  characters
        # send command byte 0x40 (set data pointer to the first byte of the first custom character)
        self.display.lcd._lcd_write(0x40, False)
        # then dump 40 successive bytes to the data register
        self.display.lcd._lcd_write(custom_characters, True)
        self.show_value(self.getter())

    def show_value(self, current_value):
        display_value = int((current_value - self.min) / (self.max - self.min) * 80)
        full, part = divmod(display_value, 5)
        # each character is 5x8 pixels
        # we're building a bar graph so we need characters that are vertical lines of varying widths.
        # our custom characters are set up as follows:
        # 0x00 = 1 pixel /5
        # 0x01 = 2 pixels/5
        # 0x02 = 3 pixels/5
        # 0x03 = 4 pixels/5
        # 0x04 = full block
        # and of course
        # 0x20 = ASCII space = empty
        data = b'\x04'*full + bytes([ (0x20, 0, 1, 2, 3)[part] ]) + b' '*(16-full-1)
        # column 64 is the first character of the second line
        self.display.write(64, data)

    @on_encoder_tick(1)
    def on_tick(self):
        now = time.monotonic()
        if self._last_tick is not None:
            time_delta = now - self._last_tick
        else:
            time_delta = 1

        if time_delta < 0.



