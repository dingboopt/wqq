#
# Copyright (C) 2013 Red Hat, Inc.
#
#  Licensed under the Apache License, Version 2.0 (the "License"); you may
#  not use this file except in compliance with the License. You may obtain
#  a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#  WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#  License for the specific language governing permissions and limitations
#  under the License.
#

from oslo_config import cfg
from oslo_log import helpers as log_helpers
from oslo_log import log as logging

from neutron_lbaas.drivers import driver_base

from networking_odl.common import client as odl_client
from networking_odl.common import constants as odl_const

cfg.CONF.import_group('ml2_odl', 'networking_odl.common.config')
LOG = logging.getLogger(__name__)

LBAAS = "lbaas"


class OpenDaylightLbaasDriverV2(driver_base.LoadBalancerBaseDriver):

    @log_helpers.log_method_call
    def __init__(self, plugin):
        LOG.debug("Initializing OpenDaylight LBaaS driver")
        self.plugin = plugin
        self.client = odl_client.OpenDaylightRestClient.create_client()
        self.load_balancer = ODLLoadBalancerManager(self.client)
        self.listener = ODLListenerManager(self.client)
        self.pool = ODLPoolManager(self.client)
        self.member = ODLMemberManager(self.client)
        self.health_monitor = ODLHealthMonitorManager(self.client)


class OpenDaylightManager(object):

    out_of_sync = True
    url_path = ""
    obj_type = ""
    obj_name = ""

    """OpenDaylight LBaaS Driver for the V2 API

    This code is the backend implementation for the OpenDaylight
    LBaaS V2 driver for OpenStack Neutron.
    """

    @log_helpers.log_method_call
    def __init__(self, client, obj_type):
        self.client = client
        self.obj_type = obj_type
        self.url_path = LBAAS + '/' + obj_type
        self.obj_name = obj_type[:-1]

    @log_helpers.log_method_call
    def create(self, context, obj):
        self.client.sendjson(
            'post', self.url_path, {self.obj_name: obj.to_api_dict()})

    @log_helpers.log_method_call
    def update(self, context, obj):
        self.client.sendjson('put', self.url_path + '/' + obj.id,
                             {self.obj_name: obj.to_api_dict()})

    @log_helpers.log_method_call
    def delete(self, context, obj):
        self.client.sendjson('delete', self.url_path + '/' + obj.id, None)


class ODLLoadBalancerManager(OpenDaylightManager,
                             driver_base.BaseLoadBalancerManager):

    @log_helpers.log_method_call
    def __init__(self, client):
        super(ODLLoadBalancerManager, self).__init__(
            client, odl_const.ODL_LOADBALANCERS)

    @log_helpers.log_method_call
    def refresh(self, context, lb):
        pass

    @log_helpers.log_method_call
    def stats(self, context, lb):
        pass


class ODLListenerManager(OpenDaylightManager,
                         driver_base.BaseListenerManager):

    @log_helpers.log_method_call
    def __init__(self, client):
        super(ODLListenerManager, self).__init__(client,
                                                 odl_const.ODL_LISTENERS)


class ODLPoolManager(OpenDaylightManager,
                     driver_base.BasePoolManager):

    @log_helpers.log_method_call
    def __init__(self, client):
        super(ODLPoolManager, self).__init__(client, odl_const.ODL_POOLS)


class ODLMemberManager(OpenDaylightManager,
                       driver_base.BaseMemberManager):

    @log_helpers.log_method_call
    def __init__(self, client):
        super(ODLMemberManager, self).__init__(client, odl_const.ODL_MEMBERS)


class ODLHealthMonitorManager(OpenDaylightManager,
                              driver_base.BaseHealthMonitorManager):

    @log_helpers.log_method_call
    def __init__(self, client):
        super(ODLHealthMonitorManager, self).__init__(
            client, odl_const.ODL_HEALTHMONITORS)