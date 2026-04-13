# Project 12 — Broadcast Traffic Control

## Problem Statement
Excessive broadcast traffic in SDN networks causes unnecessary flooding,
wasting bandwidth and degrading performance. This project implements a
POX SDN controller that detects broadcast storms, applies rate limiting,
and installs OpenFlow DROP rules to suppress over-broadcasting hosts.

## Tools Used
- Mininet (network emulator)
- POX controller (OpenFlow)
- iperf (bandwidth measurement)
- ovs-ofctl (flow table inspection)

## Setup / Execution Steps

1. Clone POX controller:
   git clone https://github.com/noxrepo/pox.git ~/pox

2. Copy controller component:
   cp pox/broadcast_control.py ~/pox/pox/misc/

3. Start POX (Terminal 1):
   cd ~/pox
   python3 pox.py log.level --DEBUG misc.broadcast_control

4. Start Mininet (Terminal 2):
   sudo python3 topo.py

5. Test connectivity:
   mininet> pingall

6. Simulate broadcast storm:
   mininet> h1 bash -c "ip neigh flush all; ping -c 1 10.0.0.2; ip neigh flush all; ping -c 1 10.0.0.3; ip neigh flush all; ping -c 1 10.0.0.4; ip neigh flush all; ping -c 1 10.0.0.2; ip neigh flush all; ping -c 1 10.0.0.3"

7. Check flow table:
   mininet> sh ovs-ofctl dump-flows s1

## Expected Output
- pingall: 0% packet loss
- POX log: WARNING rate limit hit + DROP rule installed
- Flow table: priority=20 actions=drop rule for over-broadcasting host
- iperf: Baseline throughput in Gbits/sec

## References
[1] POX Wiki - https://noxrepo.github.io/pox-doc/html/
[2] Mininet docs - http://mininet.org/walkthrough/
[3] OpenFlow 1.0 spec - https://opennetworking.org/wp-content/uploads/2013/04/openflow-spec-v1.0.0.pdf
