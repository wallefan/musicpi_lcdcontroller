import asyncio
from unittest import TestCase
from unittest.mock import Mock
from my_aiompd import Client


class Test(TestCase):
    def setUp(self) -> None:
        self.loop = asyncio.get_event_loop()
        self.client = Client()
        self.data = b''
        def write(data):
            self.data += data
        self.transport = Mock('transport')
        self.transport.write = write
        self.client.connection_made(self.transport)
        self.client.data_received(b'OK Testsuite 0.0\n')

    def test_split_binary(self):
        def write(data):
            self.assertEqual(data, b'hello world\n')

            self.client.data_received(b'binary:9\nabcd')
            self.client.data_received(b'efgh')
            self.client.data_received(b'i\nOK\n')
        self.transport.write = write
        result = self.loop.run_until_complete(self.client._send_command(b'hello world\n'))
        self.assertEqual(result, [('binary', b'abcdefghi')])

    def test_full_binary(self):
        def write(data):
            self.assertEqual(data, b'hello world\n')

            self.client.data_received(b'binary:5\nabcdi\nOK\n')
        self.transport.write = write
        result = self.loop.run_until_complete(self.client._send_command(b'hello world\n'))
        self.assertEqual(result, [('binary', b'abcdi')])

    def test_separate_binary(self):
        def write(data):
            self.assertEqual(data, b'hello world\n')

            self.client.data_received(b'binary:5\n')
            self.client.data_received(b'abcdi\nOK\n')
        self.transport.write = write
        result = self.loop.run_until_complete(self.client._send_command(b'hello world\n'))
        self.assertEqual(result, [('binary', b'abcdi')])

    def test_split_line(self):
        def write(data):
            self.assertEqual(data, b'hello world\n')

            self.client.data_received(b'bina')
            self.client.data_received(b'ry:5\n')
            self.client.data_received(b'abcdi\nOK\n')
        self.transport.write = write
        result = self.loop.run_until_complete(self.client._send_command(b'hello world\n'))
        self.assertEqual(result, [('binary', b'abcdi')])

    def test_idle(self):
        def write(data):
            self.assertEqual(data, b'idle player\n')
            self.loop.call_soon(self.client.data_received, b'changed: player\nOK\n')
        self.transport.write = write
        self.assertEqual(self.loop.run_until_complete(self.client.idle('player')), ['player'])


    def test_idle_connection_lost(self):
        fut = self.loop.create_task(self.client.idle('message'))
        self.loop.call_soon(self.client.connection_lost, None)
        # the idle should return an empty list if the connection was terminated.
        self.assertEqual(self.loop.run_until_complete(fut), [])

    def test_interrupted_idle(self):
        def write(data):
            self.data += data
            if data == b'noidle\n':
                self.loop.call_soon(self.client.data_received, b'OK\n')
            elif data == b'do_stuff\n':
                self.loop.call_soon(self.client.data_received, b'a:b\nOK\n')
        self.transport.write = write

        idle = self.loop.create_task(self.client.idle('message'))
        command = self.loop.create_task(self.client.send_command('do_stuff'))
        self.loop.run_until_complete(asyncio.gather(idle, command))

        self.assertEqual(self.data, b'idle message\nnoidle\ndo_stuff\n')

    def test_idle_lock(self):
        """Will fail if one coroutine repeatedly calling idle() will cause another coroutine not to be able to run.
        """
        def write(data):
            if data == b'do_stuff\n':
                self.loop.call_soon(self.client.data_received, b'OK\n')
            elif data == b'idle player\n':
                self.loop.call_soon(self.client.data_received, b'changed: player\nOK\n')
        self.transport.write = write

        async def spin_loop():
            while True:
                await self.client.idle('player')

        self.loop.create_task(spin_loop())
        self.loop.run_until_complete(self.client.send_command('do_stuff'))

    def test_multiple_requests(self):
        def write(data):
            if data == b'do_stuff 1\n':
                self.loop.call_soon(self.client.data_received, b'thing: 1\nOK\n')
            elif data == b'do_stuff 2\n':
                self.loop.call_soon(self.client.data_received, b'thing: 2\nOK\n')
        self.transport.write = write

        task1 = self.loop.create_task(self.client.send_command('do_stuff', '1'))
        task2 = self.loop.create_task(self.client.send_command('do_stuff', '2'))
        results = self.loop.run_until_complete(asyncio.gather(task1, task2))
        self.assertEqual(results[0], [('thing', '1')])
        self.assertEqual(results[1], [('thing', '2')])


