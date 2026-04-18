# SDN Broadcast Traffic Control

**Student:** LIKITH KUMAR K M | **ID:** PES1UG24AM373  
**Course:** SDN Mininet Simulation Project (Orange Problem)  
**Problem #12:** Broadcast Traffic Control

---

## Problem Statement

Excessive broadcast traffic (ARP floods, unknown unicast flooding) degrades
network performance, wastes bandwidth on every host, and can cause broadcast
storms that halt a network entirely.

**Objective:** Build an SDN controller that:
1. **Detects** broadcast packets arriving at the switch
2. **Limits** flooding using a per-source rate-limiter
3. **Installs selective forwarding rules** (unicast) once MAC→port mappings are
   learned, eliminating unnecessary future broadcasts
4. **Evaluates** the improvement using latency (ping) and throughput (iperf)
   metrics

---

## Architecture

```
       h1 (10.0.0.1)
       h2 (10.0.0.2)
          │
       [ s1 ] ──── Ryu Controller (127.0.0.1:6653)
          │        broadcast_controller.py
       h3 (10.0.0.3)
       h4 (10.0.0.4)
```

- **Topology:** Single switch, 4 hosts (star layout)  
- **Controller:** Ryu + OpenFlow 1.3  
- **Switch:** Open vSwitch (OVS)  

---

## How the Controller Works

```
  packet_in
     │
     ├─ Learn src_mac → in_port  (MAC table)
     │
     ├─ dst == ff:ff:ff:ff:ff:ff ?  (broadcast?)
     │     ├─ YES → rate-limit check
     │     │           ├─ within limit  → FLOOD (all ports except in_port)
     │     │           └─ over  limit   → DROP  + install drop flow rule
     │     │
     │     └─ NO  → unicast
     │                 ├─ dst in MAC table? → install unicast rule + forward
     │                 └─ dst unknown?      → flood once
```

**Rate Limit Parameters (tunable in controller):**

| Parameter | Default | Effect |
|---|---|---|
| `BROADCAST_RATE_LIMIT` | 10 packets | Max broadcasts per source per window |
| `RATE_WINDOW_SECONDS` | 5 s | Sliding time window |
| `DROP_IDLE_TIMEOUT` | 10 s | How long the drop rule stays active |
| `UNICAST_PRIORITY` | 10 | Flow rule priority for learned unicast routes |

---

## Project Structure

```
broadcast_control/
├── broadcast_controller.py   # Ryu controller (main logic)
├── topology.py               # Mininet custom topology
├── broadcast_flood.py        # Broadcast packet generator (testing tool)
├── test_scenarios.sh         # Test commands & scenarios
└── README.md                 # This file
```

---

## Setup & Installation

### Requirements

```bash
# Ubuntu 20.04 / 22.04 recommended
sudo apt-get update
sudo apt-get install -y mininet openvswitch-switch python3-pip wireshark tcpdump iperf

# Ryu SDN framework
pip3 install ryu

# Scapy (for broadcast flood test tool)
pip3 install scapy
```

### Verify Ryu installation

```bash
ryu-manager --version
# Expected: ryu-manager X.X
```

---

## Execution Steps

### Step 1 – Start the Ryu Controller

Open **Terminal 1**:

```bash
cd broadcast_control/
ryu-manager broadcast_controller.py --verbose --observe-links
```

Expected output:
```
loading app broadcast_controller.py
=== Broadcast Traffic Controller Started ===
Config: rate_limit=10 pkts / 5s window, drop_timeout=10s
```

---

### Step 2 – Launch the Mininet Topology

Open **Terminal 2** (as root):

```bash
cd broadcast_control/
sudo python3 topology.py
```

Expected output:
```
============================================================
  Broadcast Traffic Control – Mininet Network Started
============================================================
  Hosts  : h1(10.0.0.1)  h2(10.0.0.2)
           h3(10.0.0.3)  h4(10.0.0.4)
  Switch : s1  (OpenFlow 1.3)
  Ctrl   : Ryu @ 127.0.0.1:6653
============================================================
mininet>
```

In the Ryu terminal you should immediately see:
```
[SWITCH] Datapath 1 connected
```

---

### Step 3 – Run Test Scenarios

#### 3a. Basic Connectivity

```
mininet> pingall
```
Expected: `0% dropped` (ARP broadcasts learn MACs, then unicast rules installed)

#### 3b. Trigger Rate Limiter (Key Demo)

```
mininet> h1 python3 broadcast_flood.py --count 25 --interval 0.1
```

Watch Ryu terminal – you will see:
```
[BROADCAST ALLOW] dpid=1 src=00:00:00:00:00:01  count=1/10  Flooding...
...
[BROADCAST ALLOW] dpid=1 src=00:00:00:00:00:01  count=10/10 Flooding...
[BROADCAST DROP]  dpid=1 src=00:00:00:00:00:01  count=10 >= limit=10
                  Installing DROP rule (idle_timeout=10s)
```

#### 3c. Inspect Flow Table

```bash
# From Terminal 3 (separate shell):
sudo ovs-ofctl dump-flows s1 -O OpenFlow13
```

You will see:
- Priority 0 → table-miss (→ controller)
- Priority 10 → unicast forwarding rules per MAC pair
- Priority 5 → broadcast **DROP** rule for h1 (after rate limit exceeded)

#### 3d. Throughput Test

```
mininet> h2 iperf -s &
mininet> h1 iperf -c 10.0.0.2 -t 10
```

Expected:
```
[  3]  0.0-10.0 sec   114 MBytes  95.6 Mbits/sec
```

---

## Expected Output / Screenshots to Capture

| Evidence | What to Show |
|---|---|
| `ovs-ofctl dump-flows` | Drop rule + unicast rules installed |
| Ryu terminal logs | ALLOW / DROP messages with counts |
| `pingall` output | 0% packet loss |
| `iperf` result | Throughput (Mbit/s) |
| `tcpdump` on h3 | Zero/few broadcasts reaching non-target host |
| Wireshark capture | ARP storm → then silence after drop rule |

---

## Test Scenarios Summary

### Scenario 1 – Normal Connectivity (Baseline)
- **Action:** `pingall`
- **Expected:** All hosts reachable; Ryu logs show MAC learning + unicast rules

### Scenario 2 – Broadcast Rate Limiting
- **Action:** Send 25 broadcast packets in 2.5 seconds from h1
- **Expected:** First 10 allowed (flooded), packets 11–25 dropped; drop rule installed in flow table

### Scenario 3 – Unicast Selective Forwarding
- **Action:** `h1 ping h2` twice
- **Expected:** Second ping uses installed unicast rule (no controller involvement, no flooding)

### Scenario 4 – Broadcast Noise on Non-Targets
- **Without controller:** `tcpdump` on h3 shows all ARP broadcasts from h1→h2
- **With controller:** After unicast rule installed, h3 receives zero broadcast frames

### Scenario 5 – Throughput Under Broadcast Storm
- **Action:** Run iperf h1→h3 while h2 floods broadcasts
- **Expected:** Stable throughput (rate limiter kills the storm quickly)

---

## Performance Observations

| Metric | Without SDN Control | With SDN Control |
|---|---|---|
| Broadcast packets delivered to all hosts | Every ARP = flood | Capped at 10/5s per src |
| Ping RTT (avg) | ~5 ms + jitter | ~5 ms stable |
| iperf throughput | Degrades under storm | ~95 Mbit/s stable |
| Flow table entries | 1 (table-miss only) | 1 + N unicast + 1 drop rule |
| Packets hitting controller | Every unknown packet | Reduces to near-zero after learning |

---

## References

1. Ryu SDN Framework Documentation – https://ryu.readthedocs.io/
2. OpenFlow 1.3 Specification – https://opennetworking.org/wp-content/uploads/2014/10/openflow-spec-v1.3.0.pdf
3. Mininet Documentation – http://mininet.org/walkthrough/
4. Open vSwitch Documentation – https://docs.openvswitch.org/
5. Stallings, W. (2016). *Foundations of Modern Networking: SDN, NFV, QoS, IoT, and Cloud*. Pearson.
6. Feamster, N., Rexford, J., & Zegura, E. (2014). The road to SDN. *ACM Queue*, 11(12).

---

## License

Academic project – PES University. Not for commercial use.
