# Copyright (c) 2015 OpenStack Foundation.
#
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
from neutron.common import eventlet_utils

eventlet_utils.monkey_patch()

import eventlet
import datetime
import sys
import time
from neutron import service as neutron_service
from neutron import context as n_context
from neutron import manager
from neutron.agent.common import config
from neutron.common import config as common_config
from neutron.db import api as neutron_db_api
from neutron._i18n import _, _LE, _LI, _LW
from networking_controller.db import models
from oslo_config import cfg
from oslo_log import log as logging
from oslo_service import periodic_task
from oslo_service import service
from six.moves import queue as Queue
from sqlalchemy import and_
from sqlalchemy import func


LOG = logging.getLogger(__name__)


class Proxy(manager.Manager):
    """Manager for controller proxy

        API version history:
        1.0 initial Version
    """

    def __init__(self, host, conf=None):
        if conf:
            self.conf = conf
        else:
            self.conf = cfg.CONF

        self._check_config_params()

        #self.csd_client = clients.CascadeNeutronClient(clients.CASCADED)

        self.context = n_context.get_admin_context_without_session()

        self._queue = Queue.Queue()
        self.res_seq = 0
        self.binding_cache = {}
        self.binding_change = {}
        self._invalid_bindings = []
        #expired in 60s
        self.expire_time = datetime.timedelta(0, 2, 0)

        self.represent_controller = self.conf.represent_controller
        self.local_ip = self.conf.local_ip

        session = neutron_db_api.get_session()

        proxy_sequence = session.query(models.ProxySequence).\
                            filter_by(host=self.represent_controller).first()
        if proxy_sequence is None:
            self.proxy_seq = 0
            proxy_sequence = models.ProxySequence(host=self.represent_controller
                                                  , sequence=self.proxy_seq,
                                                  local_ip=self.local_ip)
            session.add(proxy_sequence)
            session.flush()
        # l2 gw ip has changed, should do some configuration changes.
        elif proxy_sequence.local_ip != self.local_ip:
            # update local ip
            pass
        else:
            self.proxy_seq = proxy_sequence.sequence

        super(Proxy, self).__init__(host=self.conf.host)

        #fetch all bindings
        bindings = session.query(models.TenantHostBinding).\
        filter(models.TenantHostBinding.host==self.represent_controller).all()
        self.init_binding_cache(bindings)

    def _make_binding_dict(self,binding):
        binding_dict = {}
        binding_dict['count'] = binding.count
        binding_dict['status'] = binding.status
        binding_dict['timestamp'] = binding.timestamp
        return binding_dict

    def init_binding_cache(self, bindings):
        for binding in bindings:
            self.binding_cache[binding.tenant_id] = self.\
                                                    _make_binding_dict(binding)

            if binding.status == 'invalid':
                self._invalid_bindings.put(binding.tenant_id)
                if len(self._invalid_bindings) > 1:
                    LOG.error("error: more than one invalid entry!")

    def construct_task(self, resources):
        for res in resources:
            if res.tenant_id not in self.binding_cache.keys():
                #don't care
                if res.host != self.conf.represent_controller:
                    continue
                elif res.tenant_id not in self.binding_change.keys():
                    self.binding_change[res.tenant_id] = {'count':0, 'tasks':None}
            elif res.tenant_id not in self.binding_change.keys():
                self.binding_change[res.tenant_id] = {'count':0, 'tasks':[]}
            if res.host == self.represent_controller \
                    and res.object_type == 'port':
                if res.status != 'delete':
                    self.binding_change[res.tenant_id]['count'] += 1
                else:
                    self.binding_change[res.tenant_id]['count'] -= 1
            # not new binding, need to append res, otherwise let the worker
            # get all the resources from the beginning
            if self.binding_change[res.tenant_id]['tasks'] != None:
                self.binding_change[res.tenant_id]['tasks'].append(res)
        #We must assign res res before worker get tasks!
        self.res_seq = res.sequence
        for tenant in self.binding_change.keys():
            self._queue.put(tenant)

    def start_transaction(self, session, new_binding, update_binding):
        with session.begin(subtransactions=True):
            for tenant in new_binding:
                new_binding = models.TenantHostBinding(
                         count=self.binding_cache[tenant]['count'],
                         host=self.represent_controller,
                         status='new',
                         tenant_id=tenant,
                         timestamp=self.binding_cache[tenant]['timestamp'])
                session.add(new_binding)
                continue

            for tenant in update_binding:
                binding = session.query(models.TenantHostBinding).filter_by(
                                            host=self.represent_controller,
                                            tenant_id=tenant).first()
                binding.count = self.binding_cache[tenant]['count']
                binding.timestamp = self.binding_cache[tenant]['timestamp']

            proxy_sequence = session.query(models.ProxySequence).\
                            filter_by(host=self.represent_controller).first()
            proxy_sequence.sequence = self.res_seq        

    def write_back_to_db(self, session, new_binding, update_binding):
        while True:
            try:
                self.start_transaction(session, new_binding, update_binding)
            except Exception as e:
                LOG.error(_LE("transaction exception: %s") %e)
                time.sleep(4)
                continue
            break

    def write_back(self, session):
        now = datetime.datetime.utcnow()
        new_binding = set()
        update_binding = set()
        for tenant in self.binding_change.keys():
            #new binding
            if tenant not in self.binding_cache.keys():
                self.binding_cache[tenant] = {}
                self.binding_cache[tenant]['count'] = \
                                    self.binding_change[tenant]['count']
                self.binding_cache[tenant]['status'] = 'new'
                self.binding_cache[tenant]['host'] = \
                                                self.represent_controller
                if self.binding_cache[tenant]['count'] != 0:
                    self.binding_cache[tenant]['timestamp'] = None
                else:
                    self.binding_cache[tenant]['timestamp'] = now
                new_binding.add(tenant)
                continue

            self.binding_cache[tenant]['count'] += \
                self.binding_change[tenant]['count']
            if self.binding_cache[tenant]['count'] == 0:
                self.binding_cache[tenant]['timestamp'] = now
            update_binding.add(tenant)

        self.write_back_to_db(session, new_binding, update_binding)
        self.proxy_seq = self.res_seq
        # clear all cache since it has been flushed into db
        self.binding_change = {}

    def clear_cascaded_resource(self, invalid_tenant):
        LOG.info(_LI("Worker: start to clear tenant:%s") %invalid_tenant)
        return 0

    def find_oldest_binding(self):
        invalid_tenant = None
        now = datetime.datetime.utcnow()
        oldest_binding = now - self.expire_time
        for tenant in self.binding_cache.keys():
            timestamp = self.binding_cache[tenant]['timestamp']
            if timestamp is not None and timestamp <= oldest_binding:
                invalid_tenant = tenant
                oldest_binding = timestamp

        return invalid_tenant

    def clear_invalid_tenant(self, session):
        if len(self._invalid_bindings) > 0:
            invalid_tenant = self._invalid_bindings.pop()
        else:
            invalid_tenant = self.find_oldest_binding()
        if invalid_tenant is not None:
            binding = session.query(models.TenantHostBinding).filter_by(
                                            host=self.represent_controller,
                                            tenant_id=invalid_tenant).first()
            binding.status = 'invalid'
            # a flush may need
            session.flush()
            result = self.clear_cascaded_resource(invalid_tenant)
            if result == 0:
                session.delete(binding)
                del self.binding_cache[invalid_tenant]
            else:
                binding.status = 'error'
                self.binding_cache[invalid_tenant]['status'] = 'error'
            session.flush()

    # NOTE(kevinbenton): this is set to 1 second because the actual interval
    # is controlled by a FixedIntervalLoopingCall in neutron/service.py that
    # is responsible for task execution.
    @periodic_task.periodic_task(spacing=1, run_immediately=True)
    def periodic_sync_resources_task(self, context):
        self._queue.join()

        LOG.info(_LI("start write back or clear," 
                     "binding cache: %s\n, binding change: %s \n "
                     "invalid_bindings : %s") 
            %(self.binding_cache, self.binding_change, self._invalid_bindings))
        session = neutron_db_api.get_session()
        if self.res_seq > self.proxy_seq:
            self.write_back(session)
        # no need to refresh proxy seq or a restart
        else:
            self.clear_invalid_tenant(session)

        LOG.info(_LI("start periodic sync resources task," 
                     "binding cache: %s\n, binding change: %s \n "
                     "invalid_bindings : %s") 
            %(self.binding_cache, self.binding_change, self._invalid_bindings))
        resources = session.query(models.ResourceSequence).\
            filter(models.ResourceSequence.sequence > self.proxy_seq).\
            order_by(models.ResourceSequence.sequence).limit(1000).all()
        if len(resources) > 0:
            self.construct_task(resources)

    def _check_config_params(self):
        """Check items in configuration files.

        Check for required and invalid configuration items.
        The actual values are not verified for correctness.
        """
        pass

    def install_cascaded_resource(self, tenant, res):
        LOG.info(_LI("Worker starts: tenant:%s res:%s")%(tenant, res))
        pass

    def do_task(self, tenant):
        #new binding
        LOG.info(_LI("Worker starts: tenant:%s")%(tenant))
        if self.binding_change[tenant]['tasks'] == None:
            session = neutron_db_api.get_session()
            resources = session.query(models.ResourceSequence).\
            filter(and_(models.ResourceSequence.tenant_id==tenant,
                        models.ResourceSequence.sequence<=self.res_seq)).\
                        order_by(models.ResourceSequence.sequence).all()
        else:
            resources = self.binding_change[tenant]['tasks']
        for res in resources:
            self.install_cascaded_resource(tenant, res)

    def _process_resource(self):
        while True:
            LOG.info(_LI("start process resources task"))
            tenant = self._queue.get()
            self.do_task(tenant)
            LOG.info(_LI("resources task done"))
            self._queue.task_done()

    def _process_resource_loop(self):
        LOG.debug("Starting _process_routers_loop")
        pool = eventlet.GreenPool(size=8)
        while True:
            pool.spawn_n(self._process_resource)

    def after_start(self):
        eventlet.spawn_n(self._process_resource_loop)
        LOG.info(_LI("proxy started"))

OPTS = [
    cfg.IntOpt('proxy_periodic_interval',
               default=1,
               help=_("periodic task interval ")),
    cfg.StrOpt('represent_controller', default='',
               help=_("represents cascaded openstack instance")),
    cfg.IPOpt('local_ip', version=4,
              help=_("l2 gateway ip of cascaded openstack instance.")),
]

def register_opts(conf):
    conf.register_opts(OPTS)

def main(manager='networking_controller.proxy.controller_proxy.Proxy'):
    register_opts(cfg.CONF)
    common_config.init(sys.argv[1:])
    config.setup_logging()
    server = neutron_service.Service.create(
        binary='controller-proxy',
        report_interval=1,
        periodic_interval=cfg.CONF.proxy_periodic_interval,
        manager=manager)
    service.launch(cfg.CONF, server).wait()


