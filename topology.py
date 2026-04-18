"""
topology.py
===========
Custom Mininet Topology – Broadcast Traffic Control
Assignment: SDN Mininet Project (Orange Problem)
Student ID: PES1UG24AM373  |  Name: LIKITH KUMAR K M

Topology Description
--------------------
  h1 ──┐
  h2 ──┤
       s1 ── (Ryu Controller)
  h3 ──┤
  h4 ──┘

  • 1 OpenFlow switch (s1) connected to a remote Ryu controller
  • 4 hosts (h1–h4) in a star topology
  • All hosts share the same broadcast domain by default

Why this topology?
  - Simple star layout maximises broadcast impact (one sender floods all)
  - Easy to scale to more hosts if needed
  - Mirrors a typical LAN segment where broadcast storms occur

Usage
-----
  # Start the Ryu controller first (in terminal 1):
  ryu-manager broadcast_controller.py --verbose

  # Then launch this topology (in terminal 2, as root):
  sudo python3 topology.py

  # Or use it with mn directly:
  sudo mn --custom topology.py --topo BroadcastTopo \
          --controller remote,ip=127.0.0.1,port=6653 \
          --switch ovsk,protocols=OpenFlow13
"""

from mininet.topo import Topo
from mininet.net import Mininet
from mininet.node import RemoteController, OVSKernelSwitch
from mininet.cli import CLI
from mininet.log import setLogLevel, info
from mininet.link import TCLink


class BroadcastTopo(Topo):
    """
    Star topology: 4 hosts connected to a single switch.

    Optional bandwidth / delay parameters make iperf results more
    meaningful and simulate a realistic LAN.
    """

    def build(self, n_hosts=4, bw=100, delay='5ms'):
        """
        Parameters
        ----------
        n_hosts : int   – number of host nodes (default 4)
        bw      : int   – link bandwidth in Mbit/s  (default 100)
        delay   : str   – one-way link delay         (default '5ms')
        """
        # Create the switch
        switch = self.addSwitch('s1', protocols='OpenFlow13')

        # Create hosts and connect to switch
        for i in range(1, n_hosts + 1):
            host = self.addHost(
                f'h{i}',
                ip=f'10.0.0.{i}/24',
                mac=f'00:00:00:00:00:0{i}'
            )
            self.addLink(host, switch,
                         bw=bw, delay=delay,
                         cls=TCLink)


# ── topos dict lets `mn --custom topology.py --topo BroadcastTopo` work ──────
topos = {'BroadcastTopo': BroadcastTopo}


# ── Standalone runner ─────────────────────────────────────────────────────────

def run():
    """
    Launch the network with a remote Ryu controller and open the CLI.
    Run this script with `sudo python3 topology.py`.
    """
    setLogLevel('info')

    topo = BroadcastTopo(n_hosts=4, bw=100, delay='5ms')

    controller = RemoteController(
        'c0',
        ip='127.0.0.1',
        port=6653
    )

    net = Mininet(
        topo=topo,
        controller=controller,
        switch=OVSKernelSwitch,
        link=TCLink,
        autoSetMacs=False,   # we set MACs explicitly in BroadcastTopo
        autoStaticArp=False  # do NOT pre-populate ARP; let broadcasts happen
    )

    net.start()

    info('\n' + '='*60 + '\n')
    info('  Broadcast Traffic Control – Mininet Network Started\n')
    info('='*60 + '\n')
    info('  Hosts  : h1(10.0.0.1)  h2(10.0.0.2)\n')
    info('           h3(10.0.0.3)  h4(10.0.0.4)\n')
    info('  Switch : s1  (OpenFlow 1.3)\n')
    info('  Ctrl   : Ryu @ 127.0.0.1:6653\n')
    info('='*60 + '\n')
    info('Tip: run `test_scenarios.sh` in a separate terminal\n\n')

    # Verify switch is connected to controller
    info('Verifying OVS switch configuration...\n')
    net.get('s1').cmd('ovs-vsctl set bridge s1 protocols=OpenFlow13')

    CLI(net)        # interactive Mininet CLI

    net.stop()


if __name__ == '__main__':
    run()
