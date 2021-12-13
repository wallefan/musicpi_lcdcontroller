import colorsys
import inspect
import time
import weakref
from typing import Union, Tuple

import pigpio
from pigpio import INPUT, OUTPUT, PUD_UP, EITHER_EDGE
import asyncio

import my_aiompd
from .screen import BaseScreen, EncoderTickWatcher
from .util import Buttons

import ruamel.yaml

BACKLIGHT_PWM_HZ = 5000

DEFAULTS = {'text scroll time': 0.5, 'text scroll first time': 1.5, 'text scroll gap': 5}


class LCD:
    def __init__(self, pi: pigpio.pi, rs, e, d4, d5, d6, d7, bl_red, bl_green, bl_blue):
        pi.set_mode(rs, OUTPUT)
        pi.set_mode(e, OUTPUT)
        pi.set_mode(d4, OUTPUT)
        pi.set_mode(d5, OUTPUT)
        pi.set_mode(d6, OUTPUT)
        pi.set_mode(d7, OUTPUT)
        pi.write(e, True)

        self.pi = pi

        self.rs = rs
        self.e = e
        self.d4 = d4
        self.d5 = d5
        self.d6 = d6
        self.d7 = d7
        self._enable_delay = 0.000001

        # LCD init sequence
        # 00110000 - set 8 bit interface (which we're not using, but the LCD needs to have that set at startup
        # to initialize properly for some reason)
        pi.write(rs, 0)
        pi.write(d7, 0)
        pi.write(d6, 0)
        pi.write(d5, 1)
        pi.write(d4, 1)
        self._toggle_enable()
        time.sleep(0.005)
        self._toggle_enable()
        time.sleep(0.0001)
        self._toggle_enable()
        time.sleep(0.0001)
        self._toggle_enable()
        time.sleep(0.0001)
        pi.write(d4, 0)  # change the nibble we're sending to 0010 to set the interface to 4 bit.
        self._toggle_enable()

        # initialize the LCD for real
        self._lcd_write(bytes([
            0b00101000,  # init
            0b00000110,  # cursor move direction (move right, do not shift display)
            0b00001100,  # display on, cursor off, blink off
            0b00000001,  # clear.
        ]), False)

        pi.set_mode(bl_red, OUTPUT)
        pi.set_mode(bl_green, OUTPUT)
        pi.set_mode(bl_blue, OUTPUT)
        pi.set_PWM_frequency(bl_red, 5000)
        pi.set_PWM_frequency(bl_green, 5000)
        pi.set_PWM_frequency(bl_blue, 5000)
        pi.set_PWM_range(bl_red, 1000)
        pi.set_PWM_range(bl_green, 1000)
        pi.set_PWM_range(bl_blue, 1000)

        self.bl_red = bl_red
        self.bl_green = bl_green
        self.bl_blue = bl_blue

        self.backlight_brightness = 1  # 0 to 1 float.

        self.lock = asyncio.Lock()

    def shutdown(self):
        self.clear()
        self.backlight_off()

    def set_color(self, hue, saturation):
        """Set the color of the display backlight using HSV.
        """
        # The backlight is a 3-wire RGB LED with common anode, which I have wired to the Pi's 3.3V rail.
        # Therefore, outputting a solid on signal (3.3V) will turn the color completely off, and a solid off signal (0V)
        # will sink current through the Pi and turn the LED on.
        r, g, b = colorsys.hsv_to_rgb(hue, saturation, self.backlight_brightness)
        self.pi.set_PWM_dutycycle(self.bl_red,   1000 - r * 1000)
        self.pi.set_PWM_dutycycle(self.bl_green, 1000 - g * 1000)
        self.pi.set_PWM_dutycycle(self.bl_blue,  1000 - b * 1000)

    def set_backlight_brightness(self, brightness):
        """Change the backlight brightness.  This will not take effect until the next time set_color() is invoked.
        """
        # XXX decide whether to fix the fact that this will not take effect until the next time set_color is invoked.
        self.backlight_brightness = brightness

    def backlight_off(self):
        self.pi.set_PWM_dutycycle(self.bl_red, 1000)
        self.pi.set_PWM_dutycycle(self.bl_green, 1000)
        self.pi.set_PWM_dutycycle(self.bl_blue, 1000)

    def _lcd_write(self, data, rs):
        # assert self.lock.locked()
        self.pi.write(self.rs, rs)
        if isinstance(data, int):
            data = bytes([data])
        for d in data:
            self.pi.write(self.e, True)
            self.pi.write(self.d4, bool(d & 0x10))
            self.pi.write(self.d5, bool(d & 0x20))
            self.pi.write(self.d6, bool(d & 0x40))
            self.pi.write(self.d7, bool(d & 0x80))
            self._toggle_enable()
            self.pi.write(self.d4, bool(d & 0x01))
            self.pi.write(self.d5, bool(d & 0x02))
            self.pi.write(self.d6, bool(d & 0x04))
            self.pi.write(self.d7, bool(d & 0x08))
            self._toggle_enable()

    def _toggle_enable(self):
        # I'd use asyncio.sleep() here, but asyncio.sleep() probably has more than 100ns of overhead
        # besides, we really shouldn't be handing control back to the event loop *while* writing data to the screen
        # if the loop actually decides to wake up and invoke another subroutine during that time, it's going to
        # confuse the heck out of the user
        self.pi.write(self.e, True)
        time.sleep(self._enable_delay)
        self.pi.write(self.e, False)
        time.sleep(self._enable_delay)
        self.pi.write(self.e, True)

    def write(self, column: int, text: bytes):
        self._lcd_write(column | 0x80, False)
        self._lcd_write(text, True)

    def upload_custom_chars(self, chars, offset=0):
        assert 0 <= offset < 8
        assert isinstance(chars, bytes)
        assert len(chars) % 8 == 0, "Custom characters must be in multiples of 8 bytes"
        self._lcd_write(0x40 + offset * 8, False)
        self._lcd_write(chars, True)

    def clear(self):
        self._lcd_write(0x01, False)


class RotaryEncoder:
    def __init__(self, pi: pigpio.pi, a, b):
        self.pi = pi
        self.a = a
        self.b = b
        pi.set_mode(a, INPUT)
        pi.set_pull_up_down(a, PUD_UP)
        pi.set_mode(b, INPUT)
        pi.set_pull_up_down(b, PUD_UP)
        self.reset()
        pi.callback(a, EITHER_EDGE, self.on_transition)
        pi.callback(b, EITHER_EDGE, self.on_transition)

    def reset(self):
        self._last_a_state = True
        self._last_b_state = True
        # if the encoder isn't already in a "notch" (i.e. neither of the contacts are closed), set _settling to True
        # this will cause all encoder ticks to be ignored until the encoder settles.
        self._settling = not (self.pi.read(self.a) and self.pi.read(self.b))
        self._count = 0
        self._pressed_time = None

    def on_transition(self, pin, newLevel, tick):
        # The rotary encoder used in this project is quite prone to switch bounce, so this callback (which is called by
        # the hardware on both the rising and falling edge of either pin) may be called many times in response to a
        # single step of the encoder.  Further, the delay between this method getting called and it reading the GPIO
        # pins is sufficient that the switch may bounce in that time, and reading the GPIO pins may return the same
        # results as when they were read last time.

        # I could mitigate this by adding a capacitor debounce circuit, but 1) that's effort and 2) that takes perfboard
        # space I don't have.  However, since I modified this method not to read the GPIO pins anymore and instead
        # update its state by the pin and newLevel arguments, since this function is guaranteed to be called exactly
        # once per pin state transition,  if the pin transitions up and down and up and down repeatedly,

        if self._settling:
            # wait for the encoder to settle to (1,1), i.e. in one of the tactile notches.
            # the encoder used for this project counts four pulses for each tactile click.  it is desirable, when the
            # encoder is reset, to not have it register additional pulses after that until it settles in a notch.
            if self.pi.read(self.a) and self.pi.read(self.b):
                self._settling = False
                self._last_a_state = self._last_b_state = True
            return

        if pin == self.a:
            self._last_a_state = newLevel
        elif pin  == self.b:
            self._last_b_state = newLevel

        if self._last_a_state ^ self._last_b_state ^ (pin == self.a):
            self._count += 1
        else:
            self._count -= 1
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
    def __init__(self, pi: pigpio.pi, mpdclient: my_aiompd.Client,
                 lcd: LCD, rotary_encoder: RotaryEncoder, rotary_switch: int,
                 buttons_adc_channel,
                 config_file_location,
                 adc_spi_channel: int = None,
                 adc_miso: int = None, adc_mosi: int = None, adc_cs: int = None, adc_sck: int = None,
                 loop: asyncio.BaseEventLoop = None):
        self.pi = pi
        self.mpd_client = mpdclient
        self.lcd = lcd
        if adc_spi_channel is not None:
            self.adc = pi.spi_open(adc_spi_channel, 1000000, pigpio.SPI_MODE_0)
            self.hwspi = True
        else:
            pi.bb_spi_open(adc_cs, adc_miso, adc_mosi, adc_sck, 1000000, pigpio.SPI_MODE_0)
            self.adc = adc_cs
            self.hwspi = False
        self.buttons_channel = buttons_adc_channel
        self.rotary_encoder = rotary_encoder
        self.rotary_encoder_switch = rotary_switch
        pi.set_mode(rotary_switch, INPUT)
        pi.set_pull_up_down(rotary_switch, PUD_UP)
        self._loop = loop or asyncio.get_event_loop()
        self._screen: BaseScreen = None
        self._last_encoder_pos = 0
        self._pressed_button = None
        self._button_pressed_time = None   # what time.monotonic() was when the button (or encoder switch) was pressed,
        self._encoder_pressed_time = None  # used for tracking how long it has been held down
        self._screen_local_handles = weakref.WeakSet()  # handles (from loop.call_later()) that must be cleared when we switch screens
        self._button_hold_handles = weakref.WeakSet()  # handles (from loop.call_later()) that must be cleared when a button is released
        # separate from button_hold_handles because although only one of the ADC buttons can be pressed at a time,
        # the encoder switch is on its own pin and can be pressed and released independent of them
        self._encoder_hold_handles = weakref.WeakSet()
        self._screen_text = bytearray(b' ' * 128)
        self._screen_reservations: list[ScreenReservation] = []

        self._config_location = config_file_location
        try:
            with open(config_file_location) as f:
                self.config = ruamel.yaml.safe_load(f)
        except (FileNotFoundError, ruamel.yaml.YAMLError):
            self.config = None

        if self.config is None:
            self.config = DEFAULTS.copy()


    def shutdown(self):
        with open(self._config_location, 'w') as f:
            ruamel.yaml.safe_dump(self.config, f)
        # if we don't do this, after a few times rerunning the script, pigpiod will run out of resources
        # and stop giving us a new handle, and must be restarted
        # apparently pi.stop() does not do this implicitly
        if self.hwspi:
            self.pi.spi_close(self.adc)
        else:
            self.pi.bb_spi_close(self.adc)
        self.lcd.shutdown()

    def _adc_read(self, channel):
        assert 0 <= channel <= 7
        # I had started to copy this routine from the Adafruit implementation, then realized they did it really weirdly
        # and arguably wrongly so i just copied the implementation in the MCP3008 datasheet and it seems to work fine
        # and also looks a lot cleaner.

        # start bit, top bit of second byte = read single channel, followed by 3 bits of channel, then 12 blank times
        # for the analog read to come back
        if self.hwspi:
            _, hi, lo = self.pi.spi_xfer(self.adc, [0x01, 0x80 | channel << 4, 0x00])[1]
        else:
            _, hi, lo = self.pi.bb_spi_xfer(self.adc, [0x01, 0x80 | channel << 4, 0x00])[1]
        return (hi & 0b11) << 8 | lo

    def _schedule_if_coro(self, func, *args):
        result = func(*args)
        if inspect.iscoroutine(result):
            task = self._loop.create_task(result)
            self._screen_local_handles.add(task)
            task.add_done_callback(self._report_failure)

    def _report_failure(self, fut: asyncio.Future):
        if not fut.cancelled():
            exc = fut.exception()
            if exc:
                import traceback
                traceback.print_exception(type(exc), exc, exc.__traceback__)

    def poll_switches(self):
        if not self.pi.read(self.rotary_encoder_switch):
            # rotary knob is pushed in
            if self._encoder_pressed_time is None:
                self._encoder_pressed_time = time.monotonic()
                self._encoder_hold_handles.update(self._loop.call_later(event[1], self._schedule_if_coro, func)
                                                  for event, funcs in self._screen.events.items()
                                                  if event[0] == Buttons.ENCODER and event[1] >= 0
                                                  for func in funcs)
        else:
            # rotary is not pressed
            if self._encoder_pressed_time is not None:
                held_time = time.monotonic() - self._encoder_pressed_time
                for handle in self._encoder_hold_handles:
                    handle.cancel()
                self._encoder_hold_handles.clear()
                for func in self._screen.events.get((Buttons.ENCODER, -1),()):
                    self._schedule_if_coro(func, held_time)
                self._encoder_pressed_time = None
        adc_reading = self._adc_read(self.buttons_channel)
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
                                    self._button_hold_handles.add(self._loop.call_later(event[1],
                                                                                        self._schedule_if_coro, func))
            else:
                if self._pressed_button is not None and self._screen is not None:
                    for handle in self._button_hold_handles:
                        # the button is no longer being held; cancel any that were waiting for it to be held longer
                        handle.cancel()
                    held_time = time.monotonic() - self._button_pressed_time
                    for func in self._screen.events.get((self._pressed_button, -1), []):
                        self._schedule_if_coro(func, held_time)
            self._pressed_button = pressed_button

        encoder_pos = self.rotary_encoder.get()
        if encoder_pos != self._last_encoder_pos:
            for watcher in self._screen.events.get('encoder',()):
                watcher: EncoderTickWatcher
                watcher.on_update(encoder_pos)
            # cancel encoder hold events if the encoder is turned, to allow applications to cycle through two different
            # things depending on whether the encoder is pressed or not.
            for h in self._encoder_hold_handles:
                h.cancel()
            self._encoder_hold_handles.clear()
        self._last_encoder_pos = encoder_pos

    @property
    def encoder_pressed(self):
        return not self.pi.read(self.rotary_encoder_switch)

    def write(self, column, text):
        if isinstance(text, str):
            text = text.encode('ascii')

        self._screen_text[column:column + len(text)] = text

        # before writing to the screen, check that it does not overlap any temporary text
        splits = [slice(0, len(text))]
        for res in self._screen_reservations:
            for i, split in enumerate(splits):
                if (res.first_col <= split.stop + column) \
                        and (res.last_col >= split.start + column):
                    break
            else:
                continue
            split = splits.pop(i)
            if split.start < res.first_col - column:
                splits.append(slice(split.start, res.first_col - column))
            if split.stop > res.last_col - column:
                splits.append(slice(res.last_col - column, split.stop))

        for split in splits:
            self.lcd.write(column + split.start, text[split])

    def clear(self):
        self._screen_reservations.clear()
        self.lcd.clear()
        self._screen_text = bytearray(b' ' * 128)

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

    def call_later(self, delay, func, *args):
        """Wrapper around asyncio.get_event_loop().call_later() for screens to use, that automatically cancels the call
        if the display switches screens before it would fire.
        """
        handle = self._loop.call_later(delay, func, *args)
        self._screen_local_handles.add(handle)
        return handle

    def show_popup(self, column, text: Union[str, bytes], duration: float, force_color=None):
        if self._screen is not None and self._screen.disallow_popups:
            return False
        new_res = ScreenReservation(column, column + len(text), duration, force_color)

        if isinstance(text, str):
            text = text.encode('ascii')

        i = 0
        while i < len(self._screen_reservations):
            res = self._screen_reservations[i]
            if res.first_col < new_res.last_col and res.last_col >= new_res.first_col:
                del self._screen_reservations[i]
                self.lcd.write(res.first_col, self._screen_text[res.first_col:res.last_col])
                continue
            else:
                i += 1

        self.lcd.write(column, text)
        self._screen_reservations.append(new_res)

    def switch_screen(self, new_screen: BaseScreen, *args):
        for handle in self._button_hold_handles:
            handle.cancel()
        self._button_hold_handles.clear()
        for handle in self._screen_local_handles:
            handle.cancel()
        self._screen_local_handles.clear()
        self._screen = new_screen
        self._schedule_if_coro(new_screen.on_switched_to, *args)

    def reset_rotary_encoder(self):
        self.rotary_encoder.reset()
        for event in self._screen.events.get('encoder', ()):
            event: EncoderTickWatcher
            event.on_reset()
