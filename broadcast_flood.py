#!/usr/bin/env python3
"""
broadcast_flood.py
==================
Broadcast Packet Generator – Testing Tool
Assignment: SDN Mininet Project (Orange Problem)

Run this INSIDE a Mininet host using:
    mininet> h1 python3 broadcast_flood.py --count 25 --interval 0.1

It sends crafted Ethernet broadcast frames so we can trigger the
rate-limiter in broadcast_controller.py and observe drops.

Dependencies: scapy  (pip install scapy)
"""

import argparse
import time
import sys

try:
    from scapy.all import Ether, ARP, sendp, conf
except ImportError:
    sys.exit("Error: scapy not installed. Run: pip install scapy")


def send_broadcasts(iface: str, count: int, interval: float):
    """
    Send `count` ARP broadcast packets on `iface` every `interval` seconds.

    ARP "who-has" messages are the most common real-world broadcast type.
    Sending 25 in 5 seconds will exceed the default rate limit of 10/5s.
    """
    print(f"[*] Sending {count} broadcast ARP packets on {iface} "
          f"(interval={interval}s)")
    print(f"[*] Expect drops after packet {10} (rate limit = 10/5s)\n")

    # Build a generic ARP who-has broadcast packet
    # dst MAC = ff:ff:ff:ff:ff:ff → broadcast
    pkt = (
        Ether(dst="ff:ff:ff:ff:ff:ff") /
        ARP(op="who-has", pdst="10.0.0.100")   # non-existent target
    )

    for i in range(1, count + 1):
        sendp(pkt, iface=iface, verbose=False)
        print(f"  Sent broadcast #{i:3d}")
        time.sleep(interval)

    print(f"\n[*] Done. Check Ryu controller logs for DROP entries.")


def main():
    parser = argparse.ArgumentParser(
        description="Send broadcast frames to test rate-limiting controller"
    )
    parser.add_argument(
        "--iface", default="h1-eth0",
        help="Network interface to send from (default: h1-eth0)"
    )
    parser.add_argument(
        "--count", type=int, default=25,
        help="Total broadcast packets to send (default: 25)"
    )
    parser.add_argument(
        "--interval", type=float, default=0.15,
        help="Seconds between packets (default: 0.15)"
    )
    args = parser.parse_args()

    send_broadcasts(args.iface, args.count, args.interval)


if __name__ == "__main__":
    main()
