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
            # 114 = 128 - 16 + 2
            self.display.write(114, self.children[self.cursor][0])
            for i in range(16):
                lcd._lcd_write(0b11100, False)
                time.sleep(0.1)
            self.disallow_popups = False
            self.display.switch_screen(self.parent)
        else:
            self.display.write(18, self.children[self.cursor][0])
            for i in range(16):
                lcd._lcd_write(0b11000, False)
                time.sleep(0.1)
            self.disallow_popups = False
            self.display.switch_screen(self.children[self.cursor][1])

    def on_switched_to(self):
        self.display.clear()
        self.display.write(0, b'  '+self.name.encode('ascii'))
        self.cursor = 0
        self.show()

    def show(self):
        if self.cursor >= len(self.children):
            self.cursor = len(self.children) - 1
        if self.cursor < -1:
            self.cursor = -1
        if self.cursor == -1 and self.parent is None:
            self.cursor = 0
        self.display.write(64,
                           (self.children[self.cursor][0] if self.cursor >= 0 else 'Back').ljust(16).encode('ascii'))



