"""Unit tests for verification_tools — test the parser, no Docker needed."""

from agentic_chaos.tools.verification_tools import _parse_ping_rtt


class TestParsePingRtt:
    def test_standard_linux_ping(self):
        output = (
            "PING 172.22.0.20 (172.22.0.20) 56(84) bytes of data.\n"
            "64 bytes from 172.22.0.20: icmp_seq=1 ttl=64 time=0.719 ms\n"
            "\n"
            "--- 172.22.0.20 ping statistics ---\n"
            "1 packets transmitted, 1 received, 0% packet loss, time 0ms\n"
            "rtt min/avg/max/mdev = 0.719/0.719/0.719/0.000 ms"
        )
        assert _parse_ping_rtt(output) == 0.719

    def test_high_latency(self):
        output = "64 bytes from 172.22.0.20: icmp_seq=1 ttl=64 time=523.4 ms"
        assert _parse_ping_rtt(output) == 523.4

    def test_sub_millisecond(self):
        output = "64 bytes from 172.22.0.2: icmp_seq=1 ttl=64 time=0.045 ms"
        assert _parse_ping_rtt(output) == 0.045

    def test_time_less_than_format(self):
        """Some systems show 'time<1 ms' for very fast pings."""
        output = "64 bytes from 172.22.0.2: icmp_seq=1 ttl=64 time<1 ms"
        # Our regex matches 'time<1' → 1.0
        assert _parse_ping_rtt(output) == 1.0

    def test_no_response(self):
        output = "From 172.22.0.1 icmp_seq=1 Destination Host Unreachable"
        assert _parse_ping_rtt(output) is None

    def test_empty_output(self):
        assert _parse_ping_rtt("") is None

    def test_timeout(self):
        output = (
            "PING 172.22.0.99 (172.22.0.99) 56(84) bytes of data.\n"
            "\n"
            "--- 172.22.0.99 ping statistics ---\n"
            "1 packets transmitted, 0 received, 100% packet loss, time 0ms"
        )
        assert _parse_ping_rtt(output) is None
