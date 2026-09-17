"""Scan for Basler GigE cameras on ANY IP band and pull strays onto ours.

Nothing here is pinned to a subnet or a serial number. The operational band is
whatever network the camera link carries, and the camera link is recognized by
having no default route (the internet-facing NIC has one; a dedicated camera NIC
doesn't) -- so managed LANs are never touched. A stray camera gets a free host
address on that link's subnet, with the search started at an SN-derived offset so
the same camera lands on the same address every time it returns.

A camera whose band doesn't match ours never answers normal discovery (no unicast
route back), but it does answer a discovery whose flags allow a broadcast ack
(0x11) -- that's what this scanner sends raw over UDP 3956. pylon's own
enumeration misses those cameras, which is why this file exists (learned the hard
way with one of the line cameras, 2026-08-26). Two things must hold for the sweep to work:

- the Hyper-V firewall passes inbound UDP from remote port 3956 (any band) into
  WSL (rule GigEVision-GVCP-Adopt-WSL), or foreign acks die before we see them;
- the probe socket stays bound to 0.0.0.0 and is steered out the camera link via
  IP_PKTINFO. Both halves matter on Linux: bound to 0.0.0.0 without steering, the
  limited broadcast leaves via the default route and no camera hears it; bound to
  the link's own address, the kernel never delivers broadcast acks to the socket
  -- and a broadcast ack is exactly what a foreign-band camera sends back.
  (Windows delivers broadcasts to bound sockets, which is why the same probe
  worked from PowerShell and hid this.)

    python adopt_cameras.py            # scan, report, adopt strays once
    python adopt_cameras.py --dry-run  # scan and report only
    python adopt_cameras.py --watch 5  # keep scanning every 5 s

live_view.py imports adopt_foreign() and runs it inside its rescan loop, so a
spare plugged in mid-run gets adopted and then slot-bound with no extra step.

Adoption = BroadcastIpConfiguration (persistent IP written by MAC, no route or
control channel needed) + RestartIpConfiguration. ForceIp is only used first for
a camera that answered with no IP at all (0.0.0.0, still negotiating).
"""
import hashlib
import ipaddress
import json
import socket
import struct
import subprocess
import sys
import time

RETRY_S = 15.0                 # per-MAC cooldown between adoption attempts
IP_PKTINFO = getattr(socket, "IP_PKTINFO", 8)   # Linux value; unexported < py3.13

_last_try = {}
_tl = None


def _transport():
    global _tl
    if _tl is None:
        from pypylon import pylon
        _tl = pylon.TlFactory.GetInstance().CreateTl("BaslerGigE")
    return _tl


def _ip_json(*args):
    out = subprocess.run(["ip", "-j", "-4", *args], capture_output=True, text=True)
    return json.loads(out.stdout or "[]")


def camera_links():
    """IPv4 links that look like dedicated camera wires: up, not loopback, and
    carrying no default route. Returns [{dev, local, net}]."""
    routed = {r.get("dev") for r in _ip_json("route", "show", "default")}
    links = []
    for iface in _ip_json("addr", "show"):
        if iface.get("ifname") == "lo" or iface.get("ifname") in routed:
            continue
        for a in iface.get("addr_info", []):
            if a.get("family") != "inet" or a["prefixlen"] >= 31:
                continue
            net = ipaddress.ip_network(f"{a['local']}/{a['prefixlen']}", strict=False)
            links.append({"dev": iface["ifname"], "ifindex": iface["ifindex"],
                          "local": a["local"], "net": net})
    return links


def discover(link, timeout=1.5):
    """Raw GVCP DISCOVERY_CMD with 'broadcast ack allowed' (flags 0x11) out of one
    link; returns [{mac, sn, ip, vendor}] for every camera heard, any band.
    Bound to 0.0.0.0 so broadcast acks are delivered (Linux drops them on a
    specifically-bound socket); IP_PKTINFO steers the probe out the right NIC."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    s.bind(("0.0.0.0", 0))
    s.settimeout(0.3)
    pktinfo = struct.pack("=i4s4s", link["ifindex"],
                          socket.inet_aton(link["local"]), b"\x00" * 4)
    s.sendmsg([bytes([0x42, 0x11, 0x00, 0x02, 0x00, 0x00, 0x00, 0x01])],
              [(socket.IPPROTO_IP, IP_PKTINFO, pktinfo)],
              0, ("255.255.255.255", 3956))
    found, t_end = {}, time.monotonic() + timeout
    while time.monotonic() < t_end:
        try:
            data, _ = s.recvfrom(1024)
        except socket.timeout:
            continue
        if len(data) < 64 or data[2:4] != b"\x00\x03":   # DISCOVERY_ACK only
            continue
        mac = data[18:24].hex().upper()
        ip = str(ipaddress.ip_address(data[44:48]))
        text = data[8:].decode("ascii", errors="replace")
        vendor = text[72:104].strip("\x00 ")             # manufacturer field
        sn = text[216:232].strip("\x00 ")                # serial number field
        found[mac] = {"mac": mac, "sn": sn, "ip": ip, "vendor": vendor}
    s.close()
    return list(found.values())


def _free_addr(sn, net, taken):
    """First free host address, probing from an SN-derived start so a returning
    camera reclaims the same spot instead of drifting."""
    count = net.num_addresses - 2
    start = (int(sn) if sn.isdigit()
             else int.from_bytes(hashlib.sha1(sn.encode()).digest()[:4], "big"))
    for i in range(count):
        addr = str(net.network_address + 1 + (start + i) % count)
        if addr not in taken:
            return addr
    return None


def adopt_foreign(timeout=1.5):
    """One sweep over every camera link: rewrite each out-of-band Basler onto that
    link's subnet. Returns human-readable event strings (empty = nothing to do)."""
    events = []
    for link in camera_links():
        devs = discover(link, timeout)
        taken = {link["local"]} | {d["ip"] for d in devs
                                   if ipaddress.ip_address(d["ip"]) in link["net"]}
        for dev in devs:
            if ipaddress.ip_address(dev["ip"]) in link["net"]:
                continue
            if "Basler" not in dev["vendor"]:
                events.append(f"skip non-Basler {dev['vendor']!r} @ {dev['ip']}")
                continue
            now = time.monotonic()
            if now - _last_try.get(dev["mac"], -RETRY_S) < RETRY_S:
                continue
            _last_try[dev["mac"]] = now
            target = _free_addr(dev["sn"], link["net"], taken)
            if target is None:
                events.append(f"SN {dev['sn']}: no free address on {link['net']}")
                continue
            tl = _transport()
            netmask = str(link["net"].netmask)
            if dev["ip"] == "0.0.0.0":                   # still negotiating: pin it first
                tl.ForceIp(dev["mac"], target, netmask, "0.0.0.0")
            ok = tl.BroadcastIpConfiguration(dev["mac"], True, False,
                                             target, netmask, "0.0.0.0", "")
            tl.RestartIpConfiguration(dev["mac"])
            taken.add(target)
            events.append(f"SN {dev['sn']} ({dev['ip']}) -> {target} on {link['dev']} "
                          f"persist={'ok' if ok else 'UNCONFIRMED'}")
    return events


def main():
    dry = "--dry-run" in sys.argv
    watch = float(sys.argv[sys.argv.index("--watch") + 1]) if "--watch" in sys.argv else None
    while True:
        for link in camera_links():
            print(f"link {link['dev']} {link['net']} (host {link['local']})", flush=True)
            for d in discover(link):
                side = "in-band" if ipaddress.ip_address(d["ip"]) in link["net"] else "FOREIGN"
                print(f"  {side:8s} SN {d['sn']} @ {d['ip']} MAC {d['mac']}", flush=True)
        if not dry:
            for ev in adopt_foreign():
                print("adopt:", ev, flush=True)
        if watch is None:
            break
        time.sleep(watch)


if __name__ == "__main__":
    main()
