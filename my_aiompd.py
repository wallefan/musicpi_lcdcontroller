import asyncio
from typing import *
import re


class Client(asyncio.Protocol):
    def __init__(self, host='localhost', port=6600, loop=None):
        self._transport: Optional[asyncio.Transport] = None
        self._response_fut: Optional[asyncio.Future] = None
        self._incoming_response = {}
        self._data_pending = b''
        self._binary_length = None
        self._version = None
        self._idle_fut: Optional[asyncio.Future] = None
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

    async def send_command(self, command, *args, forcequote=False):
        cmdline = command.encode('ascii') if isinstance(command, str) else command
        if args:
            cmdline += b' ' + b' '.join(
                (b'"' + arg.replace(b'\\', b'\\\\').replace(b'"', b'\\"') + b'"'
                 if forcequote or b' ' in arg or b'"' in arg or b'\\' in arg or b"'" in arg
                 else arg)
                for uarg in args
                for arg in (uarg.encode('ascii') if isinstance(uarg, str) else uarg,)
            )
        return await self._send_command(cmdline+b'\n')

    async def _send_command(self, command):
        if self._transport is None:
            await self.reconnect()
        elif self._idle_fut:
            await self._cancel_idle()
        assert self._response_fut is None
        self._response_fut = response = self._loop.create_future()
        self._transport.write(command)
        return await response

    async def _cancel_idle(self):
        assert self._response_fut is None
        self._response_fut = fut = self._loop.create_future()
        self._transport.write(b'noidle\n')
        try:
            self._idle_fut.set_result(await fut)
        except:
            # idfk what to do
            pass

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
        if self._idle_fut:
            # The server isn't supposed to drop connection during an idle command, but on the off-chance it does,
            # we should treat it as though the idle was simply aborted and let the code that requested the idle
            # reconnect.
            self._idle_fut.set_result([])
        self._idle_fut = None
        # commands launch before
        if self._response_fut:
            self._response_fut.set_exception(exc or ConnectionResetError)
        self._response_fut = None

    def data_received(self, data: bytes) -> None:
        if self._binary_length is not None:
            assert not self._data_pending, 'should never have pending data while reading a binary dump'
            binary = data[:self._binary_length]
            data = data[self._binary_length:]
            self._incoming_response['binary']+=binary
            self._binary_length -= len(binary)
            if self._binary_length == 0:
                assert self._incoming_response['binary'][-1:] == b'\n'
                self._incoming_response['binary'] = self._incoming_response['binary'][:-1]
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
                assert not data
                self._incoming_response = {}
                self._data_pending = b''
                return
            elif line.startswith(b'ACK'):
                assert self._response_fut is not None, 'no future waiting'
                self._response_fut.set_exception(MPDError(line.decode('utf8')))
                self._response_fut = None
                assert not data
                self._incoming_response = {}
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
                    self._incoming_response['binary'] = data[:binary_length]
                    if binary_length > len(data):
                        self._binary_length = binary_length-len(data)
                    else:
                        assert self._incoming_response['binary'][-1:] == b'\n'
                        self._incoming_response['binary'] = self._incoming_response['binary'][:-1]
                    data = data[binary_length:]
                else:
                    self._incoming_response[key] = value
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