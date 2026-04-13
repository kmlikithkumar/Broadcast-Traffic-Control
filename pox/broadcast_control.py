"""
Project 12: Broadcast Traffic Control
POX SDN Controller Component
Controls excessive broadcast traffic using selective forwarding rules.
"""

from pox.core import core
from pox.lib.util import dpidToStr
import pox.openflow.libopenflow_01 as of
from pox.lib.packet.ethernet import ethernet, ETHER_BROADCAST
from pox.lib.packet.arp import arp
import time

log = core.getLogger()

# Global broadcast packet counter for statistics
broadcast_stats = {'total': 0, 'suppressed': 0, 'forwarded': 0}

# Max broadcasts allowed per host per second (rate limiting)
BROADCAST_RATE_LIMIT = 3
broadcast_timestamps = {}  # {(dpid, src_mac): [timestamps]}


class BroadcastController(object):

    def __init__(self):
        # mac_to_port[dpid][mac] = port
        self.mac_to_port = {}
        core.openflow.addListeners(self)
        log.info("Broadcast Traffic Controller started")

    def _handle_ConnectionUp(self, event):
        """Called when a switch connects to the controller."""
        dpid = dpidToStr(event.dpid)
        log.info("Switch %s connected", dpid)
        self.mac_to_port.setdefault(event.dpid, {})

        # Install a default table-miss rule: send all unknown packets to controller
        msg = of.ofp_flow_mod()
        msg.priority = 0
        msg.actions.append(of.ofp_action_output(port=of.OFPP_CONTROLLER))
        event.connection.send(msg)

    def _is_rate_limited(self, dpid, src_mac):
        """Check if this source is sending too many broadcasts."""
        key = (dpid, str(src_mac))
        now = time.time()
        timestamps = broadcast_timestamps.get(key, [])
        # Keep only timestamps within the last 1 second
        timestamps = [t for t in timestamps if now - t < 10.0]
        broadcast_timestamps[key] = timestamps

        if len(timestamps) >= BROADCAST_RATE_LIMIT:
            return True
        timestamps.append(now)
        broadcast_timestamps[key] = timestamps
        return False

    def _install_flow_rule(self, connection, in_port, dst_mac, out_port,
                           priority=10, idle_timeout=30):
        """Install a unicast forwarding rule on the switch."""
        msg = of.ofp_flow_mod()
        msg.priority = priority
        msg.idle_timeout = idle_timeout
        msg.hard_timeout = 0
        msg.match.in_port = in_port
        msg.match.dl_dst = dst_mac
        msg.actions.append(of.ofp_action_output(port=out_port))
        connection.send(msg)
        log.debug("Installed rule: in_port=%s dst=%s -> out_port=%s",
                  in_port, dst_mac, out_port)

    def _install_broadcast_drop_rule(self, connection, src_mac, priority=20,
                                     idle_timeout=10):
        """Install a rule to drop broadcasts from a rate-limited source."""
        msg = of.ofp_flow_mod()
        msg.priority = priority
        msg.idle_timeout = idle_timeout
        msg.match.dl_src = src_mac
        msg.match.dl_dst = ETHER_BROADCAST
        # No actions = drop
        connection.send(msg)
        log.info("DROP rule installed for over-broadcasting host: %s", src_mac)

    def _handle_PacketIn(self, event):
        """Main packet handler — called for every unknown packet."""
        packet = event.parsed
        if not packet.parsed:
            log.warning("Unparsed packet, ignoring")
            return

        dpid = event.dpid
        in_port = event.port
        src_mac = packet.src
        dst_mac = packet.dst

        # --- Step 1: MAC learning ---
        self.mac_to_port.setdefault(dpid, {})
        self.mac_to_port[dpid][src_mac] = in_port

        # --- Step 2: Detect broadcast or ARP ---
        is_broadcast = (dst_mac == ETHER_BROADCAST)
        is_arp = isinstance(packet.next, arp)

        if is_broadcast or is_arp:
            broadcast_stats['total'] += 1

            # --- Step 3: Rate limit check ---
            if self._is_rate_limited(dpid, src_mac):
                broadcast_stats['suppressed'] += 1
                log.warning("Rate limit hit for %s — suppressing broadcast", src_mac)
                # Install a temporary drop rule
                self._install_broadcast_drop_rule(event.connection, src_mac)
                return  # Drop this packet

            broadcast_stats['forwarded'] += 1
            log.info("Broadcast from %s on port %s (total=%d suppressed=%d)",
                     src_mac, in_port,
                     broadcast_stats['total'], broadcast_stats['suppressed'])

            # --- Step 4: Selective flood (exclude source port) ---
            # Only send to ports where we have NOT yet learned the host
            known_ports = set(self.mac_to_port[dpid].values())
            msg = of.ofp_packet_out()
            msg.data = event.ofp
            msg.in_port = in_port

            # Use FLOOD action — OpenFlow will exclude in_port automatically
            msg.actions.append(of.ofp_action_output(port=of.OFPP_FLOOD))
            event.connection.send(msg)
            return

        # --- Step 5: Unicast forwarding ---
        if dst_mac in self.mac_to_port[dpid]:
            out_port = self.mac_to_port[dpid][dst_mac]
            # Install flow rule so future packets don't come to controller
            self._install_flow_rule(
                event.connection, in_port, dst_mac, out_port
            )
            # Forward this packet
            msg = of.ofp_packet_out()
            msg.data = event.ofp
            msg.in_port = in_port
            msg.actions.append(of.ofp_action_output(port=out_port))
            event.connection.send(msg)
        else:
            # Destination unknown — flood
            msg = of.ofp_packet_out()
            msg.data = event.ofp
            msg.in_port = in_port
            msg.actions.append(of.ofp_action_output(port=of.OFPP_FLOOD))
            event.connection.send(msg)


def launch():
    """Entry point called by pox.py launcher."""
    core.registerNew(BroadcastController)
