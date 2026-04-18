"""
broadcast_controller.py
=======================
Ryu SDN Controller – Broadcast Traffic Control
Assignment: SDN Mininet Project (Orange Problem)
Student ID: PES1UG24AM373  |  Name: LIKITH KUMAR K M

Problem: Control excessive broadcast traffic in the network.

Solution Strategy
-----------------
1. DETECT   – Identify broadcast frames (dst = ff:ff:ff:ff:ff:ff) via packet_in
2. LIMIT    – Rate-limit broadcasts per source MAC (sliding 5-second window)
3. SELECTIVE FORWARDING – Install unicast OpenFlow rules once src/dst MACs
                          are known, so future traffic never floods
4. EVALUATE – Log counters for allowed vs. dropped broadcasts per host
"""

from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet, ethernet, arp, ipv4
from ryu.lib import mac as mac_lib
import time
import logging

# ── Tunable parameters ────────────────────────────────────────────────────────
BROADCAST_RATE_LIMIT   = 10   # max broadcast packets per source per window
RATE_WINDOW_SECONDS    = 5    # sliding window size in seconds
DROP_IDLE_TIMEOUT      = 10   # seconds before a "drop" rule expires
FORWARD_IDLE_TIMEOUT   = 30   # seconds before a unicast rule expires
FORWARD_HARD_TIMEOUT   = 120  # hard cap for unicast rules
BROADCAST_PRIORITY     = 5    # priority for broadcast drop/flood rules
UNICAST_PRIORITY       = 10   # priority for unicast forwarding rules
TABLE_MISS_PRIORITY    = 0    # lowest priority – send to controller
# ─────────────────────────────────────────────────────────────────────────────


class BroadcastController(app_manager.RyuApp):
    """
    OpenFlow 1.3 controller that:
      • Learns MAC→port mappings (learning switch core)
      • Rate-limits broadcast packets per source
      • Installs unicast flow rules to suppress future flooding
      • Logs broadcast statistics for evaluation
    """

    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super(BroadcastController, self).__init__(*args, **kwargs)

        # mac_table[dpid][src_mac] = out_port
        self.mac_table = {}

        # broadcast_log[dpid][src_mac] = [timestamp, timestamp, ...]
        # Tracks timestamps of recent broadcast packets from each source.
        self.broadcast_log = {}

        # Stats counters for evaluation
        self.stats = {
            "broadcasts_allowed": 0,
            "broadcasts_dropped": 0,
            "unicast_rules_installed": 0,
        }

        self.logger.setLevel(logging.INFO)
        self.logger.info("=== Broadcast Traffic Controller Started ===")
        self.logger.info(
            "Config: rate_limit=%d pkts / %ds window, drop_timeout=%ds",
            BROADCAST_RATE_LIMIT, RATE_WINDOW_SECONDS, DROP_IDLE_TIMEOUT
        )

    # ── Switch handshake ──────────────────────────────────────────────────────

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        """
        Called once when a switch connects.
        Installs a table-miss flow: unmatched packets → controller (packet_in).
        """
        datapath = ev.msg.datapath
        ofproto  = datapath.ofproto
        parser   = datapath.ofproto_parser

        self.logger.info("[SWITCH] Datapath %s connected", datapath.id)

        # Initialize per-switch data structures
        self.mac_table[datapath.id]       = {}
        self.broadcast_log[datapath.id]   = {}

        # Table-miss entry: match everything, lowest priority → send to ctrl
        match   = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER,
                                          ofproto.OFPCML_NO_BUFFER)]
        self._install_flow(datapath, TABLE_MISS_PRIORITY, match, actions,
                           idle_timeout=0, hard_timeout=0)

    # ── Core packet_in handler ────────────────────────────────────────────────

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev):
        """
        Called for every packet that hits the table-miss rule.
        Dispatches to broadcast or unicast handling logic.
        """
        msg      = ev.msg
        datapath = msg.datapath
        ofproto  = datapath.ofproto
        parser   = datapath.ofproto_parser
        in_port  = msg.match['in_port']
        dpid     = datapath.id

        pkt     = packet.Packet(msg.data)
        eth_pkt = pkt.get_protocol(ethernet.ethernet)
        if eth_pkt is None:
            return  # not Ethernet, ignore

        dst_mac = eth_pkt.dst
        src_mac = eth_pkt.src

        # ── 1. Learn src MAC → in_port ────────────────────────────────────────
        self._learn_mac(dpid, src_mac, in_port)

        # ── 2. Route: broadcast vs unicast ───────────────────────────────────
        if dst_mac == mac_lib.BROADCAST_STR:
            self._handle_broadcast(datapath, msg, pkt, eth_pkt,
                                   src_mac, in_port)
        else:
            self._handle_unicast(datapath, msg, eth_pkt,
                                 src_mac, dst_mac, in_port)

    # ── Broadcast handling ────────────────────────────────────────────────────

    def _handle_broadcast(self, datapath, msg, pkt, eth_pkt, src_mac, in_port):
        """
        Decide whether to flood or drop a broadcast packet.

        Algorithm:
          - Maintain a sliding-window list of timestamps for (dpid, src_mac).
          - Prune timestamps older than RATE_WINDOW_SECONDS.
          - If count < BROADCAST_RATE_LIMIT  → flood and add timestamp.
          - If count >= BROADCAST_RATE_LIMIT → drop and install a short-lived
            OpenFlow drop rule for this src_mac so the switch handles it
            locally without hitting the controller again.
        """
        ofproto = datapath.ofproto
        parser  = datapath.ofproto_parser
        dpid    = datapath.id
        now     = time.time()

        # Build / prune the sliding window
        log = self.broadcast_log[dpid]
        if src_mac not in log:
            log[src_mac] = []

        # Remove timestamps outside the window
        log[src_mac] = [t for t in log[src_mac]
                        if now - t < RATE_WINDOW_SECONDS]

        broadcast_count = len(log[src_mac])

        if broadcast_count >= BROADCAST_RATE_LIMIT:
            # ── RATE LIMIT EXCEEDED: drop ─────────────────────────────────
            self.stats["broadcasts_dropped"] += 1
            self.logger.warning(
                "[BROADCAST DROP] dpid=%s src=%s  count=%d >= limit=%d  "
                "Installing DROP rule (idle_timeout=%ds)",
                dpid, src_mac, broadcast_count, BROADCAST_RATE_LIMIT,
                DROP_IDLE_TIMEOUT
            )

            # Install a drop rule: match src_mac broadcasting → drop
            match = parser.OFPMatch(
                in_port=in_port,
                eth_src=src_mac,
                eth_dst=mac_lib.BROADCAST_STR
            )
            # Empty actions list = DROP
            self._install_flow(datapath, BROADCAST_PRIORITY, match, [],
                               idle_timeout=DROP_IDLE_TIMEOUT,
                               hard_timeout=DROP_IDLE_TIMEOUT * 2)

            # Drop the current packet (do not output it)
            return

        else:
            # ── WITHIN LIMIT: selective flood ─────────────────────────────
            log[src_mac].append(now)
            self.stats["broadcasts_allowed"] += 1

            self.logger.info(
                "[BROADCAST ALLOW] dpid=%s src=%s  count=%d/%d  "
                "Flooding to all ports except in_port=%d",
                dpid, src_mac, broadcast_count + 1,
                BROADCAST_RATE_LIMIT, in_port
            )

            # Output to ALL ports except the ingress port (selective flood)
            actions = [parser.OFPActionOutput(ofproto.OFPP_FLOOD)]
            self._send_packet(datapath, msg, actions)

    # ── Unicast handling ──────────────────────────────────────────────────────

    def _handle_unicast(self, datapath, msg, eth_pkt,
                        src_mac, dst_mac, in_port):
        """
        Standard learning-switch unicast forwarding.
        If destination port is known, install a flow rule and forward.
        If unknown, flood (and wait for the reply to learn the port).
        """
        ofproto = datapath.ofproto
        parser  = datapath.ofproto_parser
        dpid    = datapath.id

        out_port = self.mac_table[dpid].get(dst_mac)

        if out_port is not None:
            # ── Known destination: install rule ───────────────────────────
            self.stats["unicast_rules_installed"] += 1
            self.logger.info(
                "[UNICAST RULE] dpid=%s  %s→%s  in_port=%d out_port=%d",
                dpid, src_mac, dst_mac, in_port, out_port
            )

            match = parser.OFPMatch(
                in_port=in_port,
                eth_dst=dst_mac,
                eth_src=src_mac
            )
            actions = [parser.OFPActionOutput(out_port)]
            self._install_flow(datapath, UNICAST_PRIORITY, match, actions,
                               idle_timeout=FORWARD_IDLE_TIMEOUT,
                               hard_timeout=FORWARD_HARD_TIMEOUT)

            # Also send the current packet immediately (it's buffered/raw)
            self._send_packet(datapath, msg, actions)

        else:
            # ── Unknown destination: flood once ───────────────────────────
            self.logger.debug(
                "[UNICAST FLOOD] dpid=%s dst=%s unknown, flooding",
                dpid, dst_mac
            )
            actions = [parser.OFPActionOutput(ofproto.OFPP_FLOOD)]
            self._send_packet(datapath, msg, actions)

    # ── Helper: learn MAC→port ────────────────────────────────────────────────

    def _learn_mac(self, dpid, src_mac, in_port):
        """Update MAC table. Log only on new/changed entries."""
        table = self.mac_table[dpid]
        if table.get(src_mac) != in_port:
            table[src_mac] = in_port
            self.logger.info(
                "[LEARN] dpid=%s  MAC %s → port %d", dpid, src_mac, in_port
            )

    # ── Helper: install OpenFlow flow rule ───────────────────────────────────

    def _install_flow(self, datapath, priority, match, actions,
                      idle_timeout=0, hard_timeout=0):
        """
        Send an OFPFlowMod to install a flow rule on the given datapath.

        Parameters
        ----------
        priority      : rule priority (higher = matched first)
        match         : OFPMatch object
        actions       : list of OFPAction objects (empty = DROP)
        idle_timeout  : remove rule after N seconds of inactivity (0=never)
        hard_timeout  : remove rule after N seconds regardless  (0=never)
        """
        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto

        inst = [parser.OFPInstructionActions(
                    ofproto.OFPIT_APPLY_ACTIONS, actions)]

        mod = parser.OFPFlowMod(
            datapath=datapath,
            priority=priority,
            match=match,
            instructions=inst,
            idle_timeout=idle_timeout,
            hard_timeout=hard_timeout,
        )
        datapath.send_msg(mod)

    # ── Helper: send packet out ───────────────────────────────────────────────

    def _send_packet(self, datapath, msg, actions):
        """
        Emit a packet-out message.
        Uses the buffer_id if the switch buffered the packet; otherwise
        re-sends the raw data.
        """
        ofproto = datapath.ofproto
        parser  = datapath.ofproto_parser

        if msg.buffer_id != ofproto.OFP_NO_BUFFER:
            out = parser.OFPPacketOut(
                datapath=datapath,
                buffer_id=msg.buffer_id,
                in_port=msg.match['in_port'],
                actions=actions,
                data=None
            )
        else:
            out = parser.OFPPacketOut(
                datapath=datapath,
                buffer_id=ofproto.OFP_NO_BUFFER,
                in_port=msg.match['in_port'],
                actions=actions,
                data=msg.data
            )
        datapath.send_msg(out)

    # ── Periodic stats dump (called from test_scenarios.sh via ryu-manager) ──

    def _print_stats(self):
        """Print broadcast control statistics to console."""
        self.logger.info("=== BROADCAST CONTROL STATISTICS ===")
        self.logger.info("  Broadcasts Allowed  : %d",
                         self.stats["broadcasts_allowed"])
        self.logger.info("  Broadcasts Dropped  : %d",
                         self.stats["broadcasts_dropped"])
        self.logger.info("  Unicast Rules Installed: %d",
                         self.stats["unicast_rules_installed"])
        total = (self.stats["broadcasts_allowed"] +
                 self.stats["broadcasts_dropped"])
        if total:
            pct = 100.0 * self.stats["broadcasts_dropped"] / total
            self.logger.info("  Broadcast Drop Rate : %.1f%%", pct)
        self.logger.info("=====================================")
