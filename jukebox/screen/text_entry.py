from .. import main
from jukebox.util import Buttons
from . import BaseScreen, on_button_pressed

CHARACTERS = b' abcdefghijklmnopqrstuvwxyz'

class TextInputScreen(BaseScreen):
    disallow_popups = True
    def __init__(self, display: main.Display, legal_characters=b' abcdefghijklmnopqrstuvwxyz'):
        self.display = display
        self.entered_text = b''
        self.current_character = b'a'[0]

    @on_button_pressed(Buttons.NEXT)
    def scroll_forward(self):
        self.scroll(1)

    @on_button_pressed(Buttons.PREVIOUS)
    def scroll_left(self):
        self.scroll(-1)

    def scroll(self, n):
        pass



