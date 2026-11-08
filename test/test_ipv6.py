import unittest
from unittest.mock import patch
import socket

from self_healing_whois.whois import NICClient


class TestNICClientIPv6(unittest.TestCase):

    def setUp(self):
        self.ipv4_info = (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('1.2.3.4', 43))
        self.ipv6_info = (socket.AF_INET6, socket.SOCK_STREAM, 6, '', ('2001:db8::1', 43, 0, 0))
        self.mock_addr_info = [self.ipv4_info, self.ipv6_info]

    @patch('socket.getaddrinfo')
    @patch('socket.socket')
    def test_connect_prioritizes_ipv6(self, mock_socket, mock_getaddrinfo):
        mock_getaddrinfo.return_value = self.mock_addr_info

        client = NICClient(prefer_ipv6=True)
        try:
            client._connect("example.com", timeout=10)
        except Exception:
            pass

        first_call_args = mock_socket.call_args_list[0][0]
        # Make sure we used IPv6 when creating socket
        self.assertEqual(first_call_args[0], socket.AF_INET6)

    @patch('socket.getaddrinfo')
    @patch('socket.socket')
    def test_connect_keeps_default_order(self, mock_socket, mock_getaddrinfo):
        mock_getaddrinfo.return_value = self.mock_addr_info

        client = NICClient(prefer_ipv6=False)
        try:
            client._connect("example.com", timeout=10)
        except Exception:
            pass

        first_call_args = mock_socket.call_args_list[0][0]
        # Make sure we used IPv4 when creating socket, which is the first appearing in our mock.
        self.assertEqual(first_call_args[0], socket.AF_INET)
