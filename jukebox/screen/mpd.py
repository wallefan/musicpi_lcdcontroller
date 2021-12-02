from . import Screen
from my_aiompd import Client

class NowPlaying(Screen):
    def __init__(self, display, next_screen):
        super().__init__(display, next_screen)
        self.mpdclient = Client()

    async def on_switched_to(self):
        status = await self.mpdclient.send_command('status')
