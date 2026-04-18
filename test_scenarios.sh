#!/bin/bash
# =============================================================================
# test_scenarios.sh
# Test Scenarios for Broadcast Traffic Control SDN Project
# Student: LIKITH KUMAR K M  |  PES1UG24AM373
#
# PREREQUISITES:
#   Terminal 1 → ryu-manager broadcast_controller.py --verbose
#   Terminal 2 → sudo python3 topology.py      (leave CLI open)
#   Terminal 3 → run this script:  bash test_scenarios.sh
# =============================================================================

set -e
SWITCH="s1"
CTR_LOG="ryu_controller.log"    # Ryu output file if redirected

separator() {
    echo ""
    echo "============================================================"
    echo "  $1"
    echo "============================================================"
}

pause() {
    echo "[*] Waiting $1 seconds..."
    sleep "$1"
}

# ── Helpers to run commands inside Mininet hosts via mn exec ─────────────────
# Usage: host_exec h1 "ping -c 3 10.0.0.2"
host_exec() {
    local HOST=$1
    shift
    echo "[${HOST}] $ $*"
    sudo mn -q --custom topology.py --topo BroadcastTopo 2>/dev/null &
    MN_PID=$!
    sleep 3
    mnexec -a "${HOST}" "$@" 2>&1 || true
    sudo kill "${MN_PID}" 2>/dev/null || true
}

# ── Preferred: use `mininet> h1 <cmd>` approach inside a running Mininet ────
# The tests below assume you already have Mininet running via topology.py.
# Run each block from the Mininet CLI prompt or from the test terminals.

echo ""
echo "  ╔══════════════════════════════════════════════════════╗"
echo "  ║   Broadcast Traffic Control – Test Scenarios         ║"
echo "  ╚══════════════════════════════════════════════════════╝"
echo ""
echo "  Run the commands below INSIDE the Mininet CLI."
echo "  (Open topology.py first, then copy-paste each section.)"
echo ""


# ─────────────────────────────────────────────────────────────────────────────
separator "SCENARIO 1 – Normal Connectivity (Baseline Ping)"
# ─────────────────────────────────────────────────────────────────────────────
cat <<'CMDS'
--- Mininet CLI commands ---

# Verify all hosts are reachable (learning switch + ARP broadcasts allowed)
mininet> h1 ping -c 4 10.0.0.2
mininet> h1 ping -c 4 10.0.0.3
mininet> h1 ping -c 4 10.0.0.4

# Expected output:
#   4 packets transmitted, 4 received, 0% packet loss
#   (First ping may show slightly higher RTT due to ARP broadcast)

# View learned MAC table on switch
mininet> s1 ovs-ofctl dump-flows s1 -O OpenFlow13

CMDS


# ─────────────────────────────────────────────────────────────────────────────
separator "SCENARIO 2 – Broadcast Rate Limit (Key Test)"
# ─────────────────────────────────────────────────────────────────────────────
cat <<'CMDS'
--- Mininet CLI commands ---

# Flood the network with 25 broadcast packets (triggers rate limiter)
# Default limit: 10 broadcasts per 5 seconds per source
mininet> h1 python3 broadcast_flood.py --iface h1-eth0 --count 25 --interval 0.1

# Expected in Ryu controller terminal:
#   [BROADCAST ALLOW] packets 1–10 → flooded
#   [BROADCAST DROP]  packet  11+  → drop rule installed
#   Installing DROP rule (idle_timeout=10s)

# Verify the drop rule exists in the flow table
mininet> s1 ovs-ofctl dump-flows s1 -O OpenFlow13

# Expected: a flow matching eth_src=00:00:00:00:00:01, eth_dst=ff:ff:ff:ff:ff:ff
#           with actions=drop and idle_timeout=10

CMDS


# ─────────────────────────────────────────────────────────────────────────────
separator "SCENARIO 3 – Unicast Rules (No More Flooding)"
# ─────────────────────────────────────────────────────────────────────────────
cat <<'CMDS'
--- Mininet CLI commands ---

# After h1 pings h2 once (ARP exchange), a unicast rule should be installed
mininet> h1 ping -c 1 10.0.0.2

# Inspect flow table – look for eth_dst=00:00:00:00:00:02 unicast rule
mininet> s1 ovs-ofctl dump-flows s1 -O OpenFlow13

# Now run iperf to show sustained unicast (no flood, direct forwarding)
mininet> h2 iperf -s &
mininet> h1 iperf -c 10.0.0.2 -t 10

# Expected: ~95 Mbit/s (no broadcast overhead)
# Compare with Scenario 4 (without the controller) for improvement metrics

CMDS


# ─────────────────────────────────────────────────────────────────────────────
separator "SCENARIO 4 – Comparison: With vs. Without Broadcast Control"
# ─────────────────────────────────────────────────────────────────────────────
cat <<'CMDS'
--- Terminal: run this BEFORE starting Ryu (uses default flooding) ---

# Step A – Baseline WITHOUT controller (hub mode)
sudo mn --topo single,4 --controller none --mac
mininet> h1 ping -c 5 10.0.0.2
# Observe: every ping triggers an ARP broadcast visible on all hosts

# Step B – Capture broadcast traffic with tcpdump (on h3, a non-target host)
mininet> h3 tcpdump -i h3-eth0 broadcast -c 20 &
mininet> h1 ping -c 10 10.0.0.2
# Without controller: h3 sees every ARP broadcast → noise

# Exit and restart WITH controller:
# ryu-manager broadcast_controller.py --verbose
# sudo python3 topology.py
mininet> h3 tcpdump -i h3-eth0 broadcast -c 20 &
mininet> h1 ping -c 10 10.0.0.2
# WITH controller (after unicast rules installed): h3 sees 0 broadcasts!

CMDS


# ─────────────────────────────────────────────────────────────────────────────
separator "SCENARIO 5 – Performance Measurement (iperf)"
# ─────────────────────────────────────────────────────────────────────────────
cat <<'CMDS'
--- Mininet CLI commands ---

# Test 1: UDP bandwidth with broadcast flood (stress test)
mininet> h4 iperf -s -u &
mininet> h1 python3 broadcast_flood.py --count 100 --interval 0.05 &
mininet> h2 iperf -c 10.0.0.4 -u -b 50M -t 15

# Test 2: TCP throughput between h1 and h3 (check no broadcast interference)
mininet> h3 iperf -s &
mininet> h1 iperf -c 10.0.0.3 -t 20

# Expected: stable throughput (~90-100 Mbit/s) even during broadcast storm
# because broadcasts are rate-limited at the switch after 10 packets.

CMDS


# ─────────────────────────────────────────────────────────────────────────────
separator "FLOW TABLE INSPECTION COMMANDS"
# ─────────────────────────────────────────────────────────────────────────────
cat <<'CMDS'
# Full flow table dump (run from any terminal as root)
sudo ovs-ofctl dump-flows s1 -O OpenFlow13

# Statistics per flow (packet/byte counts)
sudo ovs-ofctl dump-flows s1 -O OpenFlow13 --stats

# Port statistics (tx/rx packets per port)
sudo ovs-ofctl dump-ports s1 -O OpenFlow13

# Watch flow table in real time (updates every 2 seconds)
watch -n 2 "sudo ovs-ofctl dump-flows s1 -O OpenFlow13"

CMDS


# ─────────────────────────────────────────────────────────────────────────────
separator "WIRESHARK / TCPDUMP CAPTURE COMMANDS"
# ─────────────────────────────────────────────────────────────────────────────
cat <<'CMDS'
# Capture on switch interface (all traffic)
sudo tcpdump -i s1-eth1 -n

# Capture ONLY broadcast frames
sudo tcpdump -i s1-eth1 ether broadcast -n

# Save to pcap for Wireshark
sudo tcpdump -i s1-eth1 -w broadcast_capture.pcap

# Count broadcasts per second
sudo tcpdump -i s1-eth1 ether broadcast -n 2>/dev/null | \
     awk 'BEGIN{c=0; t=systime()} {c++; if(systime()-t>=1){print c" bcast/s"; c=0; t=systime()}}'

CMDS


separator "DONE – Review Ryu controller terminal for statistics"
echo ""
echo "  Key metrics to report:"
echo "    • broadcasts_allowed  (from Ryu INFO logs)"
echo "    • broadcasts_dropped  (from Ryu WARNING logs)"
echo "    • unicast_rules_installed"
echo "    • iperf throughput (Mbit/s) before vs after broadcast control"
echo "    • ping RTT (ms) with broadcast noise vs without"
echo ""
