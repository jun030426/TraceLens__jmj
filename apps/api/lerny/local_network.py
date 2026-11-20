"""Loopback-only network policy for the paused local application."""

import ipaddress
import socket


def guard_loopback():
    lookup, connect, connect_ex = (
        socket.getaddrinfo,
        socket.socket.connect,
        socket.socket.connect_ex,
    )

    def local(host):
        if isinstance(host, bytes):
            host = host.decode("ascii")
        if host == "localhost":
            return True
        try:
            return ipaddress.ip_address(host).is_loopback
        except ValueError:
            return False

    def guarded_lookup(host, *args, **kwargs):
        if not local(host):
            raise PermissionError("Private workspace blocks non-loopback DNS")
        return lookup(host, *args, **kwargs)

    def guarded_connect(client, address):
        if client.family in (socket.AF_INET, socket.AF_INET6) and not local(address[0]):
            raise PermissionError("Private workspace blocks non-loopback connections")
        return connect(client, address)

    def guarded_connect_ex(client, address):
        if client.family in (socket.AF_INET, socket.AF_INET6) and not local(address[0]):
            raise PermissionError("Private workspace blocks non-loopback connections")
        return connect_ex(client, address)

    socket.getaddrinfo = guarded_lookup
    socket.socket.connect = guarded_connect
    socket.socket.connect_ex = guarded_connect_ex
