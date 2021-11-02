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
        self.assertEqual(result, {'binary': b'abcdefghi'})

    def test_full_binary(self):
        def write(data):
            self.assertEqual(data, b'hello world\n')

            self.client.data_received(b'binary:5\nabcdi\nOK\n')
        self.transport.write = write
        result = self.loop.run_until_complete(self.client._send_command(b'hello world\n'))
        self.assertEqual(result, {'binary': b'abcdi'})

    def test_separate_binary(self):
        def write(data):
            self.assertEqual(data, b'hello world\n')

            self.client.data_received(b'binary:5\n')
            self.client.data_received(b'abcdi\nOK\n')
        self.transport.write = write
        result = self.loop.run_until_complete(self.client._send_command(b'hello world\n'))
        self.assertEqual(result, {'binary': b'abcdi'})

    def test_split_line(self):
        def write(data):
            self.assertEqual(data, b'hello world\n')

            self.client.data_received(b'bina')
            self.client.data_received(b'ry:5\n')
            self.client.data_received(b'abcdi\nOK\n')
        self.transport.write = write
        result = self.loop.run_until_complete(self.client._send_command(b'hello world\n'))
        self.assertEqual(result, {'binary': b'abcdi'})

    def test_idle_connection_lost(self):
        fut = self.loop.create_task(self.client.idle('message'))
        self.client.connection_lost(None)
        self.assertTrue(isinstance(fut.exception(), ConnectionResetError))

    def test_interrupted_idle(self):
        idle = self.loop.create_task(self.client.idle('message'))
        self.client._send_command('do_stuff')
        self.transport.wr

