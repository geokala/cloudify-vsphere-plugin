########
# Copyright (c) 2014 GigaSpaces Technologies Ltd. All rights reserved
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
#    * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    * See the License for the specific language governing permissions and
#    * limitations under the License.

import atexit
import pyVmomi
import random
import time

from pyVim.connect import SmartConnect, Disconnect

from cosmo_tester.framework import handlers

vim = pyVmomi.vim
vmodl = pyVmomi.vmodl


class VsphereCleanupContext(handlers.BaseHandler.CleanupContext):
    vcenter_connection = None

    def __init__(self, context_name, env):
        super(VsphereCleanupContext, self).__init__(context_name, env)
        self.before_state = self.env.handler.get_state()

    def cleanup(self):
        """Cleans resources according to the resource pool they run under.
        """
        super(VsphereCleanupContext, self).cleanup()
        if self.skip_cleanup:
            self.logger.warn('[{0}] SKIPPING cleanup: of the resources.'
                             .format(self.context_name))
            return
        vms_to_delete = self.get_vms_to_delete()
        self.env.handler.delete_vms(vms_to_delete)
        if len(vms_to_delete) > 0:
            msg = 'found leaked vms: {0}.'.format(vms_to_delete)
            self.logger.warn(msg)
            # assert False, 'found leaked vms: {0}.'.format(leaked_vms)

    def get_vms_to_delete(self):
        current_state = self.env.handler.get_state()
        vms_to_delete = [instance_name for instance_name in current_state
                         if instance_name not in self.before_state]
        return vms_to_delete

    @classmethod
    def clean_all(cls, env):
        super(VsphereCleanupContext, cls).clean_all(env)
        env.handler.logger.info('performing environment cleanup')
        leaked_resources = env.handler.get_state()
        env.handler.delete_vms(leaked_resources)


class CloudifyVsphereInputsConfigReader(handlers.
                                        BaseCloudifyInputsConfigReader):

    def __init__(self, cloudify_config, manager_blueprint_path, **kwargs):
        super(CloudifyVsphereInputsConfigReader, self).__init__(
            cloudify_config, manager_blueprint_path=manager_blueprint_path,
            **kwargs)

    @property
    def management_server_name(self):
        return self.config['server_name']

    @property
    def agent_key_path(self):
        return self.config['agent_private_key_path']

    @property
    def management_user_name(self):
        return self.config['manager_server_user']

    @property
    def management_key_path(self):
        return self.config['manager_private_key_path']

    @property
    def vsphere_username(self):
        return self.config['vsphere_username']

    @property
    def vsphere_password(self):
        return self.config['vsphere_password']

    @property
    def vsphere_datacenter_name(self):
        return self.config['vsphere_datacenter_name']

    @property
    def vsphere_host(self):
        return self.config['vsphere_host']

    @property
    def management_network_name(self):
        return self.config['management_network_name']

    @property
    def external_network_name(self):
        return self.config['external_network_name']

    @property
    def resource_pool_name(self):
        return self.config['vsphere_resource_pool_name']


class VsphereHandler(handlers.BaseHandler):

    CleanupContext = VsphereCleanupContext
    CloudifyConfigReader = CloudifyVsphereInputsConfigReader
    _vsphere_client = None
    _vsphere_client_time = 0

    def __init__(self, env):
        super(VsphereHandler, self).__init__(env)
        self.env = env

    def client_creds(self):
        return {
            'host': self.env.vsphere_host,
            'user': self.env.vsphere_username,
            'pwd': self.env.vsphere_password,
        }

    @property
    def vsphere_client(self):
        if not self._vsphere_client or self._vsphere_client_time < time.time():
            creds = self.client_creds()
            self._vsphere_client = SmartConnect(**creds)
            atexit.register(Disconnect, self._vsphere_client)
            # 5 minutes valid
            self._vsphere_client_time = time.time() + 300
        return self._vsphere_client

    # returns list of machine names in env. Machine names are unique in vSphere
    def get_state(self):
        state = []
        results = self._get_resources_list([vim.VirtualMachine])
        for result in results:
            if result.resourcePool and \
                    result.resourcePool.name == self.env.resource_pool_name:
                state.append(result.name)
        return state

    def delete_vms(self, vms_to_delete):
        results = self._get_resources_list([vim.VirtualMachine])
        for result in results:
            if result.resourcePool and \
                    result.resourcePool.name == self.env.resource_pool_name:
                if result.name in vms_to_delete:
                    self.logger.info('DELETING: %s' % result.name)
                    result.Destroy()

    def _get_resources_list(self, vimtype):
        content = self.vsphere_client.RetrieveContent()
        container_view = content.viewManager.CreateContainerView(
            content.rootFolder, vimtype, True
        )
        objects = container_view.view
        container_view.Destroy()
        return objects

    def before_bootstrap(self):
        super(VsphereHandler, self).before_bootstrap()
        with self.update_cloudify_config() as patch:
            suffix = '-%06x' % random.randrange(16 ** 6)
            patch.append_value('server_name', suffix)


handler = VsphereHandler
has_manager_blueprint = True
