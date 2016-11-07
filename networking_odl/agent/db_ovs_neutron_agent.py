# Copyright 2011 VMware, Inc.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import base64
import collections
import functools
import hashlib
import signal
import sys
import time

import netaddr
from oslo_config import cfg
from oslo_log import log as logging
import oslo_messaging
from oslo_service import loopingcall
from oslo_service import systemd
import six
from six import moves

from neutron._i18n import _, _LE, _LI, _LW
from neutron.agent.common import ip_lib
from neutron.agent.common import ovs_lib
from neutron.agent.common import polling
from neutron.agent.common import utils
from neutron.agent.l2.extensions import manager as ext_manager
from neutron.agent import rpc as agent_rpc
from neutron.agent import securitygroups_rpc as sg_rpc
from neutron.api.rpc.callbacks import resources
from neutron.api.rpc.handlers import dvr_rpc
from neutron.common import config
from neutron.common import constants as n_const
from neutron.common import ipv6_utils as ipv6
from neutron.common import topics
from neutron.common import utils as n_utils
from neutron import context
from neutron.extensions import portbindings
from neutron.plugins.common import constants as p_const
from neutron.plugins.common import utils as p_utils
from neutron.plugins.ml2.drivers.l2pop.rpc_manager import l2population_rpc
from neutron.plugins.ml2.drivers.openvswitch.agent.common \
    import constants
from neutron.plugins.ml2.drivers.openvswitch.agent \
    import ovs_agent_extension_api as ovs_ext_api
from neutron.plugins.ml2.drivers.openvswitch.agent \
    import ovs_dvr_neutron_agent
from neutron.plugins.ml2.drivers.openvswitch.agent \
    import ovs_neutron_agent


LOG = logging.getLogger(__name__)
cfg.CONF.import_group('AGENT', 'neutron.plugins.ml2.drivers.openvswitch.'
                      'agent.common.config')
cfg.CONF.import_group('OVS', 'neutron.plugins.ml2.drivers.openvswitch.agent.'
                      'common.config')


class DBOVSNeutronAgent(ovs_neutron_agent.OVSNeutronAgent):
    '''Implements OVS-based tunneling, VLANs and flat networks.

    Two local bridges are created: an integration bridge (defaults to
    'br-int') and a tunneling bridge (defaults to 'br-tun'). An
    additional bridge is created for each physical network interface
    used for VLANs and/or flat networks.

    All VM VIFs are plugged into the integration bridge. VM VIFs on a
    given virtual network share a common "local" VLAN (i.e. not
    propagated externally). The VLAN id of this local VLAN is mapped
    to the physical networking details realizing that virtual network.

    For virtual networks realized as GRE tunnels, a Logical Switch
    (LS) identifier is used to differentiate tenant traffic on
    inter-HV tunnels. A mesh of tunnels is created to other
    Hypervisors in the cloud. These tunnels originate and terminate on
    the tunneling bridge of each hypervisor. Port patching is done to
    connect local VLANs on the integration bridge to inter-hypervisor
    tunnels on the tunnel bridge.

    For each virtual network realized as a VLAN or flat network, a
    veth or a pair of patch ports is used to connect the local VLAN on
    the integration bridge with the physical network bridge, with flow
    rules adding, modifying, or stripping VLAN tags as necessary.
    '''

    # history
    #   1.0 Initial version
    #   1.1 Support Security Group RPC
    #   1.2 Support DVR (Distributed Virtual Router) RPC
    #   1.3 Added param devices_to_update to security_groups_provider_updated
    #   1.4 Added support for network_update
    target = oslo_messaging.Target(version='1.4')

    def __init__(self, bridge_classes, conf=None):
        '''Constructor.

        :param bridge_classes: a dict for bridge classes.
        :param conf: an instance of ConfigOpts
        '''
        super(DBOVSNeutronAgent, self).__init__(bridge_classes, conf)


def validate_local_ip(local_ip):
    """Verify if the ip exists on the agent's host."""
    if not ip_lib.IPWrapper().get_device_by_ip(local_ip):
        LOG.error(_LE("Tunneling can't be enabled with invalid local_ip '%s'."
                      " IP couldn't be found on this host's interfaces."),
                  local_ip)
        raise SystemExit(1)


def validate_tunnel_config(tunnel_types, local_ip):
    """Verify local ip and tunnel config if tunneling is enabled."""
    if not tunnel_types:
        return

    validate_local_ip(local_ip)
    for tun in tunnel_types:
        if tun not in constants.TUNNEL_NETWORK_TYPES:
            LOG.error(_LE('Invalid tunnel type specified: %s'), tun)
            raise SystemExit(1)


def prepare_xen_compute():
    is_xen_compute_host = 'rootwrap-xen-dom0' in cfg.CONF.AGENT.root_helper
    if is_xen_compute_host:
        # Force ip_lib to always use the root helper to ensure that ip
        # commands target xen dom0 rather than domU.
        cfg.CONF.register_opts(ip_lib.OPTS)
        cfg.CONF.set_default('ip_lib_force_root', True)


def main(bridge_classes):
    prepare_xen_compute()
    validate_tunnel_config(cfg.CONF.AGENT.tunnel_types, cfg.CONF.OVS.local_ip)

    try:
        agent = OVSNeutronAgent(bridge_classes, cfg.CONF)
    except (RuntimeError, ValueError) as e:
        LOG.error(_LE("%s Agent terminated!"), e)
        sys.exit(1)
    agent.daemon_loop()
