import asyncio
from typing import Optional
import re
import collections
__all__ = ['Client', 'MPDError']


class Client(asyncio.Protocol):
    def __init__(self, host='localhost', port=6600, loop=None):
        self._transport: Optional[asyncio.Transport] = None
        self._response_fut: Optional[asyncio.Future] = None
        self._incoming_response = []
        self._data_pending = b''
        self._binary_length = None
        self._binary = b''
        self._version = None
        self._idling = False
        self._queue = collections.deque()
        self._lock = asyncio.Lock()
        # TODO implement this
        # self._idling_on: Optional[set] = None  # list of subsystems monitored by the currently running idle command
        self._host = host
        self._port = port
        self._loop = loop or asyncio.get_event_loop()

    # async def _process_queue(self):
    #     while True:
    #         command, fut = await self._command_queue.get()
    #         if command is None:
    #             return
    #         await self._response_queue.put(fut)
    #         self._transport.write(command)

    async def send_command(self, command, *args, forcequote=False, idle=False):
        cmdline = command.encode('ascii') if isinstance(command, str) else command
        if args:
            cmdline += b' ' + b' '.join(
                (b'"' + arg.replace(b'\\', b'\\\\').replace(b'"', b'\\"') + b'"'
                 if forcequote or b' ' in arg or b'"' in arg or b'\\' in arg or b"'" in arg
                 else arg)
                for uarg in args
                for arg in (uarg.encode('ascii') if isinstance(uarg, str) else uarg,)
            )
        return await self._send_command(cmdline+b'\n', idle=idle)

    async def _send_command(self, command, *, idle=False):
        async with self._lock:
            if self._transport is None:
                await self.reconnect()
            elif self._idling:
                await self._cancel_idle()
            # should be covered by the lock.
            # if self._response_fut is not None:
            #     # there's another command running, we have to wait in line
            #     fut = self._loop.create_future()
            #     self._queue.append(fut)
            #     await fut
            assert self._response_fut is None or self._response_fut.cancelled(), self._response_fut.command
            self._response_fut = response = self._loop.create_future()
            response.command = command  # for debugging purposes
            self._transport.write(command)

            if not idle:
                return await response
            else:
                # The only method hat ever sets wait_for_completion to False is idle(), and in that particular case,
                # all it needs to do is make sure no one is trying to run a command other than idle() before it starts.
                # This can be done by acquiring and immediately releasing the lock.
                # However, we need to signal to other code that, even though the lock is not held, a command is still
                # running, and must be cancelled before anything else can happen.  We do this by setting self._idling
                # to True.  data_received will set it back to False when the future completes.

                # idle is the only command that can be cancelled by any means other than closing and reopening the
                # connection.
                # It's also the only one that doesn't (ideally) complete immediately.
                self._idling = True
                return None

    async def idle(self, *subsystems):
        # if someone is trying to cancel an idle command, ensure that this method cannot start until it finishes
        # whatever it is trying to do.

        await self.send_command('idle', *subsystems, idle=True)
        response_fut = self._response_fut
        response_fut.add_done_callback(self._cancel_idle_on_future_cancelled)
        return [x[1] for x in (await response_fut) if x[0] == 'changed']

    def _cancel_idle_on_future_cancelled(self, fut: asyncio.Future):
        if fut.cancelled():
            self._transport.write(b'noidle\n')

    async def _cancel_idle(self):
        assert self._idling
        fut = self._response_fut
        self._transport.write(b'noidle\n')
        # for some reason Python does funny things if the future you're waiting on gets set to None before you wake up
        # so we have to do this
        try:
            await fut
        finally:
            self._idling = False


    async def reconnect(self):
        if '/' in self._host:
            await self._loop.create_unix_connection(lambda: self, self._host)
        else:
            await self._loop.create_connection(lambda: self, self._host, self._port)

    def connection_made(self, transport: asyncio.Transport) -> None:
        self._transport = transport
        self._version = None

    def connection_lost(self, exc: Optional[Exception]) -> None:
        self._transport = None
        self._lines = []
        if self._idling:
            # The server isn't supposed to drop connection during an idle command, but on the off-chance it does,
            # we should treat it as though the idle was simply aborted and let the code that requested the idle
            # reconnect.
            self._response_fut.set_result([])
            self._idling = False
        elif self._response_fut:
            # if a command was running, cancel it
            self._response_fut.set_exception(exc or ConnectionResetError)
        self._response_fut = None

    def data_received(self, data: bytes) -> None:
        if self._binary_length is not None:
            assert not self._data_pending, 'should never have pending data while reading a binary dump'
            binary = data[:self._binary_length]
            data = data[self._binary_length:]
            self._binary += binary
            self._binary_length -= len(binary)
            if self._binary_length == 0:
                assert self._binary[-1:] == b'\n'
                self._incoming_response.append(('binary', self._binary[:-1]))
                self._binary_length = None
        elif self._data_pending:
            data = self._data_pending + data

        line, sep, data = data.partition(b'\n')
        while sep:
            if self._version is None:
                assert line.startswith(b'OK ')
                self._version = line[3:].strip().decode('ascii')
            elif line == b'OK':
                assert self._response_fut is not None, 'no future waiting'
                self._response_fut.set_result(self._incoming_response)
                self._response_fut = None
                self._idling = False
                if self._queue:
                    self._queue.popleft().set_result(None)
                assert not data
                self._incoming_response = []
                self._data_pending = b''
                return
            elif line.startswith(b'ACK'):
                assert self._response_fut is not None, 'no future waiting'
                self._response_fut.set_exception(MPDError(line.decode('utf8')))
                self._response_fut = None
                self._idling = False
                if self._queue:
                    self._queue.popleft().set_result(None)
                assert not data
                self._incoming_response = []
                self._data_pending = b''
                return
            else:
                key, value = line.split(b':', 1)
                key = key.decode('ascii').strip()
                value = value.decode('utf8').strip()
                if key == 'binary':
                    # XXX Having this code be replicated seems bad to me, but I don't really want to recurse.
                    assert self._binary_length is None, self._binary_length
                    binary_length = int(value) + 1  # add one byte for the newline at the end.
                    self._binary = data[:binary_length]
                    if binary_length > len(data):
                        self._binary_length = binary_length-len(data)
                    else:
                        assert self._binary[-1:] == b'\n'
                        self._incoming_response.append(('binary', self._binary[:-1]))
                    data = data[binary_length:]
                else:
                    self._incoming_response.append((key, value))
            line, sep, data = data.partition(b'\n')
        self._data_pending = line


class MPDError(RuntimeError):
    # This code stolen, with slight modifications, from aiompd by TODO NAME THE AUTHOR OF AIOMPD
    RE = re.compile(r'^ACK \[(\d+)@(\d+)\] \{(.+)\} (.+)$')

    def __init__(self, line: str) -> None:
        super().__init__(line)

        parsed = self.RE.match(line)
        if parsed:
            self.code = int(parsed.group(1))
            self.lineno = int(parsed.group(2))
            self.command = parsed.group(3)
            self.message = parsed.group(4)
        else:
            self.code = None
            self.lineno = None
            self.command = None
            self.message = None