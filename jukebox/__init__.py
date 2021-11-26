import colorsys
import time
from typing import Union, Tuple

from RPi import GPIO as gpio
import asyncio
from Adafruit_MCP3008 import MCP3008

from .screen import BaseScreen
from .util import Buttons

BACKLIGHT_PWM_HZ = 5000


class LCD:
    def __init__(self, rs, e, d4, d5, d6, d7, bl_red, bl_green, bl_blue):
        gpio.setup(rs, gpio.OUT)
        gpio.setup(e, gpio.OUT)
        gpio.setup(d4, gpio.OUT)
        gpio.setup(d5, gpio.OUT)
        gpio.setup(d6, gpio.OUT)
        gpio.setup(d7, gpio.OUT)
        gpio.output(e, True)

        self.rs = rs
        self.e = e
        self.d4 = d4
        self.d5 = d5
        self.d6 = d6
        self.d7 = d7

        self._enable_delay = 0.001
        self._lcd_write(bytes([
            0x33,
            0x32,
            0b00000110,  # cursor move direction (move right, do not shift display)
            0b00001100,  # display on, cursor off, blink off
            0b00101000,  # init
            0b00000001,  # clear.
        ]), False)
        self._enable_delay = 0.0000001

        gpio.setup(bl_red, gpio.OUT)
        gpio.setup(bl_green, gpio.OUT)
        gpio.setup(bl_blue, gpio.OUT)

        self.backlight_brightness = 1  # 0 to 1 float.

        self.red = gpio.PWM(bl_red, BACKLIGHT_PWM_HZ)
        self.green = gpio.PWM(bl_green, BACKLIGHT_PWM_HZ)
        self.blue = gpio.PWM(bl_blue, BACKLIGHT_PWM_HZ)
        self.red.start(100)
        self.green.start(100)
        self.blue.start(100)
        self.lock = asyncio.Lock()

    def set_color(self, hue, saturation):
        """Set the color of the display backlight using HSV.
        """
        r, g, b = colorsys.hsv_to_rgb(hue, saturation, self.backlight_brightness)
        self.red.ChangeDutyCycle(100 - r * 100)
        self.green.ChangeDutyCycle(100 - g * 100)
        self.blue.ChangeDutyCycle(100 - b * 100)

    def set_backlight_brightness(self, brightness):
        """Change the backlight brightness.  This will not take effect until the next time set_color() is invoked.
        """
        # XXX decide whether to fix the fact that this will not take effect until the next time set_color is invoked.
        self.backlight_brightness = brightness

    def backlight_off(self):
        self.red.ChangeDutyCycle(100)
        self.green.ChangeDutyCycle(100)
        self.blue.ChangeDutyCycle(100)

    def _lcd_write(self, data, rs):
        # assert self.lock.locked()
        gpio.output(self.rs, rs)
        if not isinstance(data, bytes):
            data = bytes([data])
        for d in data:
            gpio.output(self.e, True)
            gpio.output(self.d4, bool(d & 0x10))
            gpio.output(self.d5, bool(d & 0x20))
            gpio.output(self.d6, bool(d & 0x40))
            gpio.output(self.d7, bool(d & 0x80))
            self._toggle_enable()
            gpio.output(self.d4, bool(d & 0x01))
            gpio.output(self.d5, bool(d & 0x02))
            gpio.output(self.d6, bool(d & 0x04))
            gpio.output(self.d7, bool(d & 0x08))
            self._toggle_enable()

    def _toggle_enable(self):
        # I'd use asyncio.sleep() here, but asyncio.sleep() probably has more than 100ns of overhead
        # besides, we really shouldn't be handing control back to the event loop *while* writing data to the screen
        # if the loop actually decides to wake up and invoke another subroutine during that time, it's going to
        # confuse the heck out of the user
        time.sleep(self._enable_delay)
        gpio.output(self.e, False)
        time.sleep(self._enable_delay)
        gpio.output(self.e, True)

    def write(self, column: int, text: bytes):
        self._lcd_write(column | 0x80, False)
        self._lcd_write(text, True)

    def clear(self):
        self._lcd_write(0x01, False)


class RotaryEncoder:
    def __init__(self, a, b):
        self.a = a
        self.b = b
        gpio.setup(a, gpio.IN, gpio.PUD_UP)
        gpio.setup(b, gpio.IN, gpio.PUD_UP)
        self.reset()
        gpio.add_event_detect(a, gpio.BOTH, self.on_transition)
        gpio.add_event_detect(b, gpio.BOTH, self.on_transition)

    def reset(self):
        self._last_a_state = True
        self._last_b_state = True
        # if the encoder isn't already in a "notch" (i.e. neither of the contacts are closed), set _settling to True
        # this will cause all encoder ticks to be ignored until the encoder settles.
        self._settling = not (gpio.input(self.a) and gpio.input(self.b))
        self._count = 0
        self._pressed_time = None

    def on_transition(self, pin):
        # The rotary encoder used in this project is quite prone to switch bounce, so this callback (which is called by
        # the hardware on both the rising and falling edge of either pin) may be called many times in response to a
        # single state change.  Further, the delay between this method getting called and it reading the GPIO pins
        # is sufficient that the switch may bounce in that time, and reading the GPIO pins may return the same results
        # as when they were read last time.

        # I could mitigate this by adding a capacitor debounce circuit, but 1) that's effort and 2) that takes perfboard
        # space I don't have.  This problem really only presents itself when the knob is turned *very* slowly, so
        # I may just not worry about it and just implement a software fix.
        a = gpio.input(self.a)
        b = gpio.input(self.b)
        if self._settling:
            if a and b:  # wait for the encoder to settle to (1,1), i.e. one of the tactile notches
                self._settling = False
            return
        if a != self._last_a_state:
            if a ^ b:
                self._count -= 1
            else:
                self._count += 1
        elif b != self._last_b_state:
            if a ^ b:
                self._count += 1
            else:
                self._count -= 1
        self._last_a_state = a
        self._last_b_state = b
        print(self._count)

    def get(self):
        return self._count


class ScreenReservation:
    def __init__(self, start_column: int, end_column: int, time_duration: float, force_color: Tuple[float, float]):
        self.first_col = start_column
        self.last_col = end_column
        self.end_time = time.monotonic() + time_duration
        self.force_color = force_color


class Display:
    def __init__(self, lcd: LCD, adc: MCP3008, rotary_encoder: RotaryEncoder, rotary_switch: int,
                 loop: asyncio.BaseEventLoop = None):
        self.lcd = lcd
        self.adc = adc
        self.rotary_encoder = rotary_encoder
        self.rotary_encoder_switch = rotary_switch
        gpio.setup(rotary_switch, gpio.IN, gpio.PUD_UP)
        self._loop = loop or asyncio.get_event_loop()
        self._screen: BaseScreen = None
        self._pressed_button = None
        self._button_pressed_time = None
        self._last_fire_time = None
        self._screen_local_handles = []  # handles (from loop.call_later()) that must be cleared when we switch screens
        self._button_hold_handles = [] # handles (from loop.call_later()) that must be cleared when a button is released
        self._screen_text = bytearray(b' ' * 128)
        self._screen_reservations: list[ScreenReservation] = []

    def poll_switches(self):
        if not gpio.input(self.rotary_encoder_switch):
            # rotary knob is pushed in
            pass
        else:
            # rotary is not pressed
            pass
        adc_reading = self.adc.read_adc(2)
        if adc_reading < 5:
            pressed_button = None
        elif 335 < adc_reading < 350:
            pressed_button = Buttons.MODE
        elif adc_reading == 1023:
            pressed_button = Buttons.PAUSE
        elif 150 < adc_reading < 160:
            pressed_button = Buttons.SHUFFLE
        elif 765 < adc_reading < 775:
            pressed_button = Buttons.REPEAT
        elif 610 < adc_reading < 625:
            pressed_button = Buttons.PREVIOUS
        elif 510 < adc_reading < 520:
            pressed_button = Buttons.NEXT
        else:
            return

        if pressed_button != self._pressed_button:
            if pressed_button is not None:
                self._button_pressed_time = time.monotonic()
                if self._pressed_button is None:
                    # the purpose of this if statement is to not register button pressed events unless the state
                    # transitioned from nothing pressed to something pressed, rather than from one button being pressed
                    # to another.
                    # this way if the user presses a button, presses another button, and releases the first one,
                    # we won't fire a second event for the second button.
                    # This is pretty much a personal preference thing but I like it this way.

                    # get all listeners on the current screen that listen for this button being held for at least 0
                    # seconds, and fire them.
                    if self._screen is not None:
                        for event, funcs in self._screen.events.items():
                            # each event is a 2-tuple of the button and how many seconds it must be held
                            # (0 means as soon as it is pressed)
                            # a hold time of -1 means call when the button is released
                            if event[0] == pressed_button and event[1] >= 0:
                                for func in funcs:
                                    self._button_hold_handles.append(self._loop.call_later(event[1], func))
                else:
                    if self._pressed_button is not None and self._screen is not None:
                        for handle in self._button_hold_handles:
                            # the button is no longer being held; cancel any that were waiting for it to be held longer
                            handle.cancel()
                        for func in self._screen.events.get((self._pressed_button, -1)):
                            func()
            self._pressed_button = pressed_button

        if self._screen is not None and pressed_button is not None:
            pass

    def write(self, column, text):
        if isinstance(text, str):
            text = text.encode('ascii')

        self._screen_text[column:column + len(text)] = text

        # before writing to the screen, check that it does not overlap any temporary text
        splits = [slice(0, len(text))]
        for res in self._screen_reservations:
            for i, split in enumerate(splits):
                if (res.first_col <= split.start < res.last_col) \
                        or (res.first_col <= split.stop < res.last_col):
                    break
            else:
                continue
            split = splits.pop(i)
            if split.start < res.first_col:
                splits.append(slice(split.start, res.first_col))
            if split.stop > res.last_col:
                splits.append(slice(res.last_col, split.stop))

        for split in splits:
            self.lcd.write(column + split.start, text[split])


    def clear(self):
        self.lcd.clear()


    def mainloop(self):
        self.poll_switches()

        # check for expried screen reservations
        i = 0
        while i < len(self._screen_reservations):
            res = self._screen_reservations[i]
            if time.monotonic() > res.end_time:
                del self._screen_reservations[i]
                self.lcd.write(res.first_col, self._screen_text[res.first_col:res.last_col])
            else:
                i += 1

        self._loop.call_later(0.05, self.mainloop)

    def show_popup(self, column, text: Union[str, bytes], duration: float, force_color=None):
        if self._screen is not None and self._screen.disallow_popups:
            return False
        if isinstance(text, str):
            text = text.encode('ascii')
        self.lcd.write(column, text)
        self._screen_reservations.append(ScreenReservation(column, column + len(text), duration, force_color))

    def switch_screen(self, new_screen: BaseScreen):
        for handle in self._button_hold_handles:
            handle.cancel()
        self._button_hold_handles.clear()
        for handle in self._screen_local_handles:
            handle.cancel()
        self._screen_local_handles.clear()
        self._screen = new_screen
        new_screen.on_switched_to()

