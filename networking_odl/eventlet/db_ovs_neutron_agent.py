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

# Copyright (C) 2014,2015 VA Linux Systems Japan K.K.
# Copyright (C) 2014 Fumihiko Kakuma <kakuma at valinux co jp>
# Copyright (C) 2014,2015 YAMAMOTO Takashi <yamamoto at valinux co jp>
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

import sys

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import importutils

from neutron.common import config as common_config
from neutron.common import utils as n_utils

<<<<<<< HEAD
from neutron.plugins.ml2.drivers.openvswitch.agent.openflow.ovs_ofctl \
    import br_int
from neutron.plugins.ml2.drivers.openvswitch.agent.openflow.ovs_ofctl \
    import br_phys
from neutron.plugins.ml2.drivers.openvswitch.agent.openflow.ovs_ofctl \
    import br_tun
from neutron.plugins.ml2.drivers.openvswitch.agent import ovs_neutron_agent

=======
>>>>>>> branch 'master' of https://github.com/dingboopt/wqq.git

LOG = logging.getLogger(__name__)
cfg.CONF.import_group('OVS', 'neutron.plugins.ml2.drivers.openvswitch.agent.'
                      'common.config')


_main_modules = {
    'ovs-ofctl': 'neutron.plugins.ml2.drivers.openvswitch.agent.openflow.'
                 'ovs_ofctl.main',
    'native': 'neutron.plugins.ml2.drivers.openvswitch.agent.openflow.'
                 'native.main',
}


def main():
    common_config.init(sys.argv[1:])
#     driver_name = cfg.CONF.OVS.of_interface
#     mod_name = _main_modules[driver_name]
#     mod = importutils.import_module(mod_name)
#     mod.init_config()
    common_config.setup_logging()
    n_utils.log_opt_values(LOG)
#     mod.main()
    bridge_classes = {
        'br_int': br_int.OVSIntegrationBridge,
        'br_phys': br_phys.OVSPhysicalBridge,
        'br_tun': br_tun.OVSTunnelBridge,
    }
    ovs_neutron_agent.main(bridge_classes)

