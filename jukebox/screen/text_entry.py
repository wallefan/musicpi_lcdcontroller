from jukebox.util import Buttons
from . import BaseScreen, on_button_pressed, on_encoder_tick
from .. import Display

CHARACTERS = b' abcdefghijklmnopqrstuvwxyz'

# NOTE: throughout this file, I use the term "charsets" to refer to "subsets of ASCII which the user can cycle through".
# Examples of charsets might be "uppercase letters", "lowercase letters", and "numbers/special symbols".
# I'm not referring to "charsets" as in ANSI codepages.  HD44780 displays don't support those anyway.

# If the user wanted to enter the string "I'm 5", for example, they would switch to the uppercase charset, select I,
# switch to the symbols charset, select apostrophe, switch to the lowercase charset, select M, then switch to the
# numbers charset and select 5.

# Currently, if you go off the end of a charset, you go back to its beginning rather than the beginning of the next
# charset, so charsets are effectively each their own self-contained loops rather than being contigouous.
# I can (and probably should) make this a config option.

class TextInputScreen(BaseScreen):
    disallow_popups = True
    def __init__(self, display: Display, next_screen, cancel_screen, charsets=(b' abcdefghijklmnopqrstuvwxyz',)):
        super().__init__()
        self.display = display
        self.next_screen = next_screen
        self.cancel_screen = cancel_screen
        self.entered_text = bytearray()
        self.display_offset = 0
        self.absolute_offset = 0
        self.charsets = charsets
        # selected_charset: the last charset the user cycled to by pressing the repeat button, which no code except
        #                   the user input handler changes
        # detected_charset: the charset containing the character under the cursor, which is ephemeral and changes
        #                   every time the cursor moves
        self.selected_charset = self.detected_charset = 0
        self.current_character = 0
        self.last_encoder_position = 0

    def on_switched_to(self):
        self.display.reset_rotary_encoder()
        self.scroll(0, True)

    @on_encoder_tick(4)
    def on_encoder_tick(self, n):
        if self.display.encoder_pressed:
            self.scroll(n)
        else:
            self.cycle(n)

    @on_button_pressed(Buttons.ENCODER)
    @on_button_pressed(Buttons.NEXT)
    def scroll_right(self):
        self.scroll(1)

    @on_button_pressed(Buttons.PREVIOUS)
    def scroll_left(self):
        self.scroll(-1)

    @on_button_pressed(Buttons.REPEAT)
    def switch_charsets(self):
        # cycle through starting on the current charset being used (the detected charset)
        self.selected_charset = self.detected_charset = (self.detected_charset + 1) % len(self.charsets)
        self.cycle(0)

    def cycle(self, n):
        charset = self.charsets[self.detected_charset]
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
        offset = self.absolute_offset = max(0, self.absolute_offset + n)
        if len(self.entered_text) <= self.absolute_offset:
            charset = self.charsets[self.selected_charset]
            character = charset[self.current_character % len(charset)]
            self.entered_text.extend(character for _ in range(self.absolute_offset - len(self.entered_text) + 1))
            force_redraw = True
            # we're moving into a brand new cell, use the last selected charset.
            # self.detected_charset = self.selected_charset
        else:
            pos = self.charsets[self.selected_charset].find(self.entered_text[self.absolute_offset])
            if pos != -1:
                self.detected_charset = self.selected_charset
                self.current_character = pos
            else:
                # XXX what should be the behavior here?
                # the situation here is that the user has moved the cursor from a position with one charset to
                # a position with another, i.e., after editing a lowercase letter, moved the cursor to a position
                # that already contained an uppercase one.
                # What I've opted to do is maintain two state variables: selected_charset and detected_charset.
                # selected_charset is the last charset the user actually selected by pressing Repeat to cycle through
                # them, which is the first one searched when moving to a new cell (important if multiple charsets
                # contain the same character, such as space), and which is automatically switched to when
                # moving to a new cell.  This second behavior may be confusing, and I may remove it depending on
                # how it feels to use.
                # The second state variable, detected_charset, is the one turning the rotary encoder actually picks
                # characters from, which is automatically switched out based on which character is under the cursor.
                character = self.entered_text[self.absolute_offset]
                for i, charset in enumerate(self.charsets):
                    pos = charset.find(character)
                    if pos != -1:
                        self.detected_charset = i
                        self.current_character = pos
                        break
                else:
                    # If we get here, a character not in any of our charsets got into self.entered_text somehow.
                    # Since the user can only select characters from one of the charsets, the only way that can happen
                    # is if another screen put it there.
                    # What should be the behavior here?  I don't want to crash.
                    # I guess I'll just leave the state variables where they are.
                    pass
        screen_cursor_pos = self.absolute_offset - self.display_offset
        # first check absolute bounds
        if screen_cursor_pos <= 0:
            screen_cursor_pos = 0
        elif screen_cursor_pos >= 16:
            screen_cursor_pos = 15
        # then do some nice scrolling effects when the cursor gets near the edge of the screen
        elif screen_cursor_pos < 3 and offset >= 3:
            screen_cursor_pos = 3
        elif screen_cursor_pos > 13 and offset < len(self.entered_text) - 3:
            screen_cursor_pos = 13
        # if we don't have to scroll, and we weren't forced to redraw...
        elif not force_redraw:
            # set cursor position to the second line at the given offset.
            self.display.lcd._lcd_write(0xC0 | screen_cursor_pos, False)
            return
        # recompute the display offset
        self.display_offset = self.absolute_offset - screen_cursor_pos
        # display off, cursor off, cursor blink on
        self.display.lcd._lcd_write(0b1100,False)
        self.display.lcd.write(64, self.entered_text[self.display_offset:self.display_offset+16].ljust(16))
        self.display.lcd._lcd_write(0xC0 | screen_cursor_pos, False)
        # display on, cursor on, cursor blink on
        self.display.lcd._lcd_write(0b1110,False)



