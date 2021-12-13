import urllib.parse

from . import Screen, on_button_pressed, on_encoder_tick
from .text_entry import TextInputScreen
import yt_dlp
from yt_dlp.extractor.youtube import YoutubeSearchIE
import itertools
from unidecode import unidecode_expect_ascii as unidecode

from .. import Buttons


class YTSearch(Screen):
    def __init__(self, display, previous_screen, next_screen):
        super().__init__(display, previous_screen)
        self.ytdl = yt_dlp.YoutubeDL({'format': 'bestaudio'})
        self.iterator = None
        self.list = None
        self.pos = 0
        self._scroll_callback = None
        # perhaps confusingly, the parent class (Screen) stores the previous screen in self.next_screen,
        # because I had written it with the intention of having a main cycle that you could loop through by pressing
        # Mode, and various menus that you could descend into from there.  I may redo it to be that at some point,
        # but right now, next_screen almost always refers to the parent screen.  Maybe I should change the variable
        # name instead of just punting it down the road like this.  Ah, well.
        self.success_screen = next_screen

    def on_switched_to(self, query=None):
        if query is None:
            self.display.clear()
            self.display.write(0, 'Search query:')
            self.display.switch_screen(TextInputScreen(self.display, self, self.next_screen))
            return
        self.iterator = YoutubeSearchIE(self.ytdl)._search_results(query.decode('ascii'))
        self.list = []
        self.pos = 0
        self.seek(0)

    @on_encoder_tick(4)
    def seek(self, n):
        self.pos += n
        if self.pos >= len(self.list):
            if self._scroll_callback is not None:
                self._scroll_callback.cancel()
            self.display.clear()
            self.display.write(0, 'Searching...')
            self.list.extend(itertools.islice(self.iterator, self.pos-len(self.list)+1))
        entry = self.list[self.pos]
        self.display.write(0, unidecode(entry['uploader']).ljust(16))
        if self._scroll_callback is not None:
            self._scroll_callback.cancel()
        self._scroll_text(unidecode(entry['title']), 0)

    @on_button_pressed(Buttons.NEXT)
    def next(self):
        self.seek(1)

    @on_button_pressed(Buttons.PREVIOUS)
    def prev(self):
        self.seek(-1)

    @on_button_pressed(Buttons.PAUSE)
    @on_button_pressed(Buttons.ENCODER)
    async def select(self):
        if self._scroll_callback is not None:
            self._scroll_callback.cancel()
        self.display.clear()
        self.display.write(0, 'Loading...')
        info = self.ytdl.extract_info(self.list[self.pos]['url'], download=False)
        url = info['url']
        if 'title' in info:
            url += '#StreamName='+urllib.parse.quote(info['title'])
        id_ = dict(await self.display.mpd_client.send_command('addid', url))['Id']
        await self.display.mpd_client.send_command('playid', id_)
        self.display.switch_screen(self.success_screen)

    def _scroll_text(self, text, offset):
        if len(text) <= 16:
            self.display.write(64, text.ljust(16))
            return
        text_to_show = text[offset:offset+16]
        gap = self.display.config['text scroll gap']
        if len(text_to_show) < 16:
            more_text = ' ' * gap + text[:16]
            start_idx = max(0, offset - len(text_to_show))
            text += more_text[start_idx:start_idx + (16 - len(text_to_show))]
        self.display.write(64, text_to_show)
        self._scroll_callback = self.display.call_later(self.display.config['text scroll first time'] if offset == 0
                                                        else self.display.config['text scroll time'],
                                                        self._scroll_text, text, (offset+1) % (len(text) + gap))
