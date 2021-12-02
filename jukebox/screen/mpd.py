import pprint

from . import Screen, on_button_pressed
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
    0b01010,
    0b01010,
    0b01010,
    0b01010,
    0b01010,
    0b01010,
    0b01010,
    0b01010,
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
        self._loop = display._loop
        self.mpdclient = Client('musicpi.local', loop=display._loop)
        self._playlist = []
        self._playlist_ver = None
        self._shuffle_state = False
        self._repeat_state = 0
        self._status = {'random':'0','repeat':'0','single':'0'}

    async def on_switched_to(self):
        self.display.lcd.upload_custom_chars(CUSTOM_CHARACTERS)
        self.display.lcd.clear()
        await self.on_status_change()
        while True:
            for subsys in await self.mpdclient.idle('player', 'playlist', 'options'):
                if subsys in ('player', 'options'):
                    await self.on_status_change()
                elif subsys == 'playlist':
                    await self.on_playlist_change()

    async def on_status_change(self):
        old_status = self._status
        status = self._status = dict(await self.mpdclient.send_command('status'))
        if status['state'] == 'play':
            duration = float(status['duration'])
            elapsed = float(status['elapsed'])
            self.display.write(0, '\x00 %2d:%02d / %d:%02d' % (elapsed // 60, int(elapsed % 60),
                                                               duration // 60, int(duration % 60)))
            # TODO show playback timer
        elif status['state'] == 'pause':
            duration = float(status['duration'])
            elapsed = float(status['elapsed'])
            self.display.write(0, '\x01 %2d:%02d / %d:%02d' % (elapsed // 60, int(elapsed % 60),
                                                               duration // 60, int(duration % 60)))
        elif status['state'] == 'stop':
            self.display.write(0, '\x02')

        shuffle_state = status['random'] == '1'
        repeat_state = 2 if status['single'] == '1' else 1 if status['repeat'] == '1' else 0
        if shuffle_state != self._shuffle_state:
            self.display.show_popup(3, 'Shuffle On' if shuffle_state else 'Shuffle Off', 2)
        if repeat_state != self._repeat_state:
            string = ('Repeat Off','Repeat All','Repeat One')[repeat_state]
            if shuffle_state != self._shuffle_state:
                # if both things change show the popups sequentially
                self._loop.call_later(1.9, self.display.show_popup, 3, string, 2)
            else:
                self.display.show_popup(3, string, 2)
        self._shuffle_state = shuffle_state
        self._repeat_state = repeat_state

        # if status['playlist'] != self._playlist_ver:
        #     await self.on_playlist_change()
        #     del self._playlist[status['playlistlength']:]
        #     self._playlist_ver = status['playlist']

    async def on_playlist_change(self):
        if self._playlist_ver is None:
            data = await self.mpdclient.send_command('playlistinfo')
        else:
            data = await self.mpdclient.send_command('plchanges', self._playlist_ver)
        pprint.pprint(data)


    @on_button_pressed(Buttons.PAUSE)
    async def play_pause(self):
        await self.mpdclient.send_command('pause')
        await self.on_status_change()

    @on_button_pressed(Buttons.SHUFFLE)
    async def toggle_shuffle(self):
        new_random = 0 if self._status['random'] == '1' else 1
        await self.mpdclient.send_command('random', str(new_random))
        await self.on_status_change()



