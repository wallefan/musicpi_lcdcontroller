from .. import Display
from ..screen import BaseScreen, on_button_pressed
from ..util import Buttons
import time

class Directory(BaseScreen):
    def __init__(self, name: str, parent):
        super().__init__()
        self.name = name
        self.children = []
        if isinstance(parent, Directory):
            self.parent = parent
            self.display = parent.display
            parent.children.append((name, self))
        elif isinstance(parent, Display):
            self.display = parent
            self.parent = None
        else:
            raise TypeError
        self.cursor = 0

    @on_button_pressed(Buttons.PREVIOUS)
    def move_previous(self):
        self.cursor -= 1
        self.show()

    @on_button_pressed(Buttons.NEXT)
    def move_next(self):
        self.cursor += 1
        self.show()

    @on_button_pressed(Buttons.PAUSE)
    @on_button_pressed(Buttons.ENCODER)
    def enter(self):
        self.disallow_popups = True
        lcd = self.display.lcd
        if self.cursor == -1:
            lcd._lcd_write(bytes(0xD0, 0b10000), False) # set cursor to second line, column 16, set move direction to left
            for i in range(16):
                lcd._lcd_write(b'<'[0], True)
                time.sleep(0.025)
            lcd._lcd_write(0b10100, False) # restore cursor move direction to right
            self.disallow_popups = False
            self.screen.switch_screen(self.parent)
        else:
            lcd._lcd_write(0xC0, False)
            for i in range(16):
                lcd._lcd_write(b'>'[0], True)
                time.sleep(0.025)
            self.disallow_popups = False
            self.display.switch_screen(self.children[self.cursor][1])

    def on_switched_to(self):
        print('switched to menu', self.name)
        self.display.clear()
        time.sleep(0.5)
        print('asdf')
        self.display.write(0, b'  '+self.name.encode('ascii'))
        time.sleep(0.5)
        print('asdf')
        self.show()

    def show(self):
        if self.cursor >= len(self.children):
            self.cursor = len(self.children) - 1
        if self.cursor < -1:
            self.cursor = -1
        if self.cursor == -1 and self.parent is None:
            self.cursor = 0
        self.display.write(64, self.children[self.cursor][0].ljust(16).encode('ascii'))


