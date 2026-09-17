"""GVCP unicast reachability check (no pylon needed).

Sends a GigE Vision DISCOVERY_CMD directly to each camera IP and waits for
the ack. Works even when broadcast discovery is unavailable (e.g. WSL2 NAT).
"""
import os
import socket

targets = os.environ.get("CAMERA_IPS", "192.168.0.1,192.168.0.2,192.168.0.3").split(",")
pkt = bytes([0x42, 0x01, 0x00, 0x02, 0x00, 0x00, 0x00, 0x01])  # DISCOVERY_CMD, unicast ack

for ip in targets:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(2.0)
    try:
        s.sendto(pkt, (ip, 3956))
        data, addr = s.recvfrom(1024)
        print(f"{ip}: REPLY {len(data)} bytes from {addr[0]} -> reachable")
    except socket.timeout:
        print(f"{ip}: TIMEOUT -> not reachable")
    except OSError as e:
        print(f"{ip}: ERROR {e}")
    finally:
        s.close()
