from jukebox.util import Buttons
from . import BaseScreen, on_button_pressed, on_encoder_tick
from .. import Display

CHARACTERS = b' abcdefghijklmnopqrstuvwxyz'

class TextInputScreen(BaseScreen):
    disallow_popups = True
    def __init__(self, display: Display, next_screen, cancel_screen, charsets=(b' abcdefghijklmnopqrstuvwxyz',)):
        super().__init__()
        self.display = display
        self.next_screen = self
        self.cancel_screen = cancel_screen
        self.entered_text = bytearray()
        self.display_offset = 0
        self.absolute_offset = 0
        self.charsets = charsets
        self.selected_charset = 0
        self.current_character = 0
        self.last_encoder_position = 0

    def on_switched_to(self):
        self.display.reset_rotary_encoder()
        self.scroll(0, True)

    @on_encoder_tick(2)
    def on_encoder_tick(self, n):
        if not self.display.encoder_pressed:
            self.cycle(n)

    @on_button_pressed(Buttons.NEXT)
    def scroll_forward(self):
        self.scroll(1)

    @on_button_pressed(Buttons.PREVIOUS)
    def scroll_left(self):
        self.scroll(-1)

    @on_button_pressed(Buttons.REPEAT)
    def switch_charsets(self):
        self.selected_charset = (self.selected_charset + 1) % len(self.charsets)
        self.cycle(0)

    def cycle(self, n):
        charset = self.charsets[self.selected_charset]
        charidx = (self.current_character + n) % len(charset)
        if n != 0:
            # don't bother writing back the result of the modulus if we're just cycling through charsets,
            # which may be different lengths, i.e. if we have three charsets, A-Z, a-z, and 0-9, and the user stops
            # on Q and cycles through them, we want to still be on Q after they cycle through 0-9 back around to A-Z
            # even though 0-9 only has 10 elements.
            self.current_character = charidx
        character = self.entered_text[self.absolute_offset] = charset[charidx]
        print(self.entered_text.decode('ascii'), '!')
        offset = self.absolute_offset - self.display_offset
        self.display.lcd.write(offset+64, bytes([character]))
        self.display.lcd._lcd_write(0xC0 | offset, False)

    def scroll(self, n, force_redraw=False):
        offset = self.absolute_offset = self.absolute_offset + n
        if len(self.entered_text) <= self.absolute_offset:
            charset = self.charsets[self.selected_charset]
            character = charset[self.current_character%len(charset)]
            self.entered_text.extend(character for _ in range(self.absolute_offset - len(self.entered_text) + 1))
            force_redraw = True
        screen_cursor_pos = self.absolute_offset - self.display_offset
        if screen_cursor_pos < 3 and offset > 3:
            self.display_offset -= 1
            screen_cursor_pos = 3
            force_redraw = True
        elif screen_cursor_pos > 13 and offset < len(self.entered_text) - 3:
            self.display_offset += 1
            screen_cursor_pos = 13
        elif not force_redraw:
            # set cursor position to the second line at the given offset.
            self.display.lcd._lcd_write(0xC0 | screen_cursor_pos, False)
            return
        # TODO turn cursor blink off during text update, then back on after.
        self.display.lcd._lcd_write(0b1000,False)
        self.display.lcd.write(64, self.entered_text[self.display_offset:self.display_offset+16].ljust(16))
        self.display.lcd._lcd_write(0xC0 | screen_cursor_pos, False)
        self.display.lcd._lcd_write(0b1111,False)



