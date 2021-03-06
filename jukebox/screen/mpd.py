import asyncio
import posixpath
import pprint
import urllib.parse
from unidecode import unidecode_expect_ascii as unidecode

from . import Screen, on_button_pressed, on_button_held
from ..util import Buttons
from my_aiompd import Client
import time


CUSTOM_CHARACTERS = bytes((
    # Custom char 0 = Play symbol
    0b10000,
    0b11000,
    0b11100,
    0b11110,
    0b11110,
    0b11100,
    0b11000,
    0b10000,
    # Custom char 1 = Pause symbol
    0b00000,
    0b01010,
    0b01010,
    0b01010,
    0b01010,
    0b01010,
    0b01010,
    0b00000,
    # Custom char 3 = Stop symbol
    0b00000,
    0b11111,
    0b11111,
    0b11111,
    0b11111,
    0b11111,
    0b00000,
    0b00000,
    # # Custom char 2 = Playback progress (1/5)
    # 0b10000,
    # 0b10000,
    # 0b10000,
    # 0b11111,
    # 0b10000,
    # 0b10000,
    # 0b10000,
    # 0b10000,
    # # Custom char 3 = Playback progress (2/5)
    # 0b11000,
    # 0b11000,
    # 0b11000,
    # 0b11111,
    # 0b11000,
    # 0b11000,
    # 0b11000,
    # 0b11000,
    # # Custom char 4 = Playback progress (3/5)
    # 0b11100,
    # 0b11100,
    # 0b11100,
    # 0b11111,
    # 0b11100,
    # 0b11100,
    # 0b11100,
    # 0b11100,
    # # Custom char 5 = Playback progress (4/5)
    # 0b11110,
    # 0b11110,
    # 0b11110,
    # 0b11111,
    # 0b11110,
    # 0b11110,
    # 0b11110,
    # 0b11110,
    # # For 0/5 we just use the hyphen, and for 5/5 we use the full block (in the default charset at 0xff)
))

class NowPlaying(Screen):
    def __init__(self, display, next_screen):
        super().__init__(display, next_screen)
        self._playlist = []
        self._playlist_ver = None
        self._shuffle_state = False
        self._repeat_state = 0
        self._song_title = None
        self._song_scroll_callback = None
        self._playback_start_time = None   # what time.monotonic() was (computed) when the current song started playing
        self._update_timer_callback = None
        self._status = None
        self._config = {'text wrap gap': 5}

    async def on_switched_to(self):
        self.display.lcd.upload_custom_chars(CUSTOM_CHARACTERS)
        self.display.lcd.clear()
        # set all these to None so that when on_status_change() compares them to the previous values to see if they've
        # changed, they always show as changed.
        self._song_title = None
        self._shuffle_state = None
        self._repeat_state = None
        self._status = None
        await self.on_status_change()
        while True:
            for subsys in await self.display.mpd_client.idle('player', 'playlist', 'options'):
                if subsys in ('player', 'options'):
                    await self.on_status_change()
                elif subsys == 'playlist':
                    await self.on_playlist_change()

    async def on_status_change(self):
        status = self._status = dict(await self.display.mpd_client.send_command('status'))

        if self._update_timer_callback:
            self._update_timer_callback.cancel()
            self._update_timer_callback = None
        if status['state'] in ('play', 'pause'):
            duration = float(status['duration']) if 'duration' in status else None
            elapsed = float(status['elapsed'])
            self.display.write(0, '%s %2d:%02d / ' % ('\x00' if status['state'] == 'play' else '\x01',
                                                             elapsed // 60, int(elapsed % 60)) +
                               ('%d:%02d' % (duration // 60, int(duration % 60)) if duration else '??:??'))
            if status['state'] == 'play':
                self._playback_start_time = time.monotonic() - elapsed
                # arrange for update_timer to be called precisely at the start of the next integer second.
                # (and kind of just hope that asyncio's clock doesn't drift too terribly much...)
                self._update_timer_callback = self.display.call_later(1 - elapsed % 1, self._update_timer)
        elif status['state'] == 'stop':
            self.display.write(0, '\x02  Stopped      ')

        if status['playlist'] != self._playlist_ver:
            await self.on_playlist_change()
            del self._playlist[int(status['playlistlength']):]
            self._playlist_ver = status['playlist']
        if 'song' in status:
            entry: dict = self._playlist[int(status['song'])]
            if 'Title' in entry:
                if 'Artist' in entry:
                    title = f"{unidecode(entry['Artist']).strip()} - {unidecode(entry['Title']).strip()}"
                else:
                    title = unidecode(entry['Title']).strip()
            else:
                if '://' in entry['file']:
                    pos = entry['file'].find('#StreamName=')
                    if pos != -1:
                        title = urllib.parse.unquote(entry['file'][pos+12:])
                    else:
                        title = '[Web Stream]'
                else:
                    title = posixpath.splitext(posixpath.basename(entry['file']))[0]
                title = unidecode(title).strip()
        else:
            title = None
        if title != self._song_title:
            if self._song_scroll_callback is not None:
                self._song_scroll_callback.cancel()
            self._song_scroll_callback = None
            self._song_title = title
            if title is not None:
                self._song_scroll(0)
            else:
                self.display.write(64, ' '*16)

        shuffle_state = status['random'] == '1'
        repeat_state = 0 if status['repeat'] == '0' else 2 if status['single'] == '1' else 1
        if shuffle_state != self._shuffle_state:
            self.display.show_popup(3, 'Shuffle On' if shuffle_state else 'Shuffle Off', 2)
        if repeat_state != self._repeat_state:
            string = ('Repeat Off', 'Repeat All', 'Repeat One')[repeat_state]
            if shuffle_state != self._shuffle_state:
                # if both things change show the popups sequentially
                self.display.call_later(1.9, self.display.show_popup, 3, string, 2)
            else:
                self.display.show_popup(3, string, 2)
        self._shuffle_state = shuffle_state
        self._repeat_state = repeat_state

    async def on_playlist_change(self):
        if self._playlist_ver is None:
            data = await self.display.mpd_client.send_command('playlistinfo')
        else:
            data = await self.display.mpd_client.send_command('plchanges', self._playlist_ver)
        item = None
        for k,v in data:
            if k == 'file':
                # The first line of each new entry is always 'file:' so we can use it as a delimiter.
                if item is not None:
                    while len(self._playlist) <= item['Pos']:
                        # pad the playlist with Nones out until we have a slot we can put this item into, in case the
                        # server sent entries out of order (or in case we're extending the list)
                        # there shouldn't be any Nones left after we finish.
                        self._playlist.append(None)
                    self._playlist[item['Pos']] = item
                item = {'file':v}
            else:
                if k in ('Pos','Id'):
                    v = int(v)
                elif k in ('duration',):
                    v = float(v)
                item[k] = v
        # The last item in the list won't have had a file: after it, so the above code won't have put it into the array
        # item will only be None here if the playlist was empty
        if item is not None:
            while len(self._playlist) <= item['Pos']:
                # pad the playlist with Nones out until we have a slot we can put this item into, in case the
                # server sent entries out of order (or in case we're extending the list)
                # there shouldn't be any Nones left after we finish.
                self._playlist.append(None)
            self._playlist[item['Pos']] = item

        assert None not in self._playlist

    def _song_scroll(self, offset):
        gap = self._config['text wrap gap']
        if len(self._song_title) <= 16:
            self.display.write(64, self._song_title.center(16))
            return
        text = self._song_title[offset:offset+16]
        # there's probably a far more efficient way to do this but my brain is not big enough right now
        if len(text) < 16:
            more_text = ' '*gap + self._song_title[:16]
            start_idx = max(0, offset - len(self._song_title))
            text += more_text[start_idx:start_idx + (16-len(text))]
        self.display.write(64, text)
        # TODO make this scroll delay configurable
        self._song_scroll_callback = self.display.call_later(1.5 if offset == 0 else 0.5, self._song_scroll,
                                                             (offset + 1) % (len(self._song_title) + gap))

    def _update_timer(self):
        elapsed = time.monotonic() - self._playback_start_time
        self.display.write(2, '%2d:%02d' % (elapsed // 60, int(elapsed % 60)))
        # call time.monotonic() again because, when running remote, writing to the display
        # actually takes a significant amount of time lol
        self._update_timer_callback = self.display.call_later(1 - (time.monotonic() - self._playback_start_time) % 1,
                                                              self._update_timer)

    @on_button_pressed(Buttons.PAUSE)
    async def play_pause(self):
        await self.display.mpd_client.send_command('pause')
        await self.on_status_change()

    @on_button_pressed(Buttons.NEXT)
    async def next(self):
        await self.display.mpd_client.send_command('next')
        await self.on_status_change()

    # Important note here: this decorator does not modify the class namespace.
    # All this decorator does is flag the function as having an event attached to it, then when the metaclass __init__
    # runs, it scans the class namespace for functions that have an event flag and puts them in a dictionary.
    # This means that if two functions have the same name, one will overwrite the other, despite having a decorator
    # on it that one would expect to store it in some data structure somewhere.
    # Perhaps I should modify __prepare__() of the metaclass to prepopulate the namespace with events={}, then have the
    # decorator find the class namespace via sys._getframe().f_back.f_locals and modify that dictionary directly.
    # I could also have the metaclass __init__ scan the class's MRO for events to add.
    @on_button_pressed(Buttons.PREVIOUS)
    async def previous(self):
        await self.display.mpd_client.send_command('previous')
        await self.on_status_change()

    @on_button_pressed(Buttons.SHUFFLE)
    async def toggle_shuffle(self):
        new_random = 0 if self._status['random'] == '1' else 1
        await self.display.mpd_client.send_command('random', str(new_random))
        await self.on_status_change()

    @on_button_held(Buttons.SHUFFLE, 1)
    async def shuffle(self):
        await self.display.mpd_client.send_command('shuffle')
        self.display.show_popup(1, 'Plylst Shuffled', 2)

    @on_button_pressed(Buttons.REPEAT)
    async def toggle_repeat(self):
        new_repeat = (self._repeat_state + 1) % 3
        await self.display.mpd_client.send_command('repeat', '1' if new_repeat >= 1 else '0')
        await self.display.mpd_client.send_command('single', '1' if new_repeat == 2 else '0')
        await self.on_status_change()



