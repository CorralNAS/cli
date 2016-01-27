#
# Copyright 2015 iXsystems, Inc.
# All rights reserved
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted providing that the following conditions
# are met:
# 1. Redistributions of source code must retain the above copyright
#    notice, this list of conditions and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright
#    notice, this list of conditions and the following disclaimer in the
#    documentation and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE AUTHOR ``AS IS'' AND ANY EXPRESS OR
# IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED.  IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR ANY
# DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
# DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS
# OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION)
# HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT,
# STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING
# IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.
#
#####################################################################

import gettext
from freenas.cli.namespace import Namespace, EntityNamespace, Command, RpcBasedLoadMixin, TaskBasedSaveMixin, description
from freenas.cli.output import ValueType, output_msg_locked
from freenas.cli.utils import post_save


t = gettext.translation('freenas-cli', fallback=True)
_ = t.gettext


@description("Tools for simulating disks")
class DisksNamespace(RpcBasedLoadMixin, TaskBasedSaveMixin, EntityNamespace):
    def __init__(self, name, context):
        super(DisksNamespace, self).__init__(name, context)

        self.query_call = 'simulator.disk.query'
        self.create_task = 'simulator.disk.create'
        self.update_task = 'simulator.disk.update'
        self.delete_task = 'simulator.disk.delete'

        self.add_property(
            descr='Disk name',
            name='name',
            get='id',
            list=True
        )

        self.add_property(
            descr='Disk path',
            name='path',
            get='path',
            list=True
        )

        self.add_property(
            descr='Online',
            name='online',
            get='online',
            list=True,
            type=ValueType.BOOLEAN
        )

        self.add_property(
            descr='Size',
            name='mediasize',
            get='mediasize',
            list=True,
            type=ValueType.SIZE
        )

        self.add_property(
            descr='Serial number',
            name='serial',
            get='serial',
            list=False
        )

        self.add_property(
            descr='Vendor name',
            name='vendor',
            get='vendor',
            list=True
        )

        self.add_property(
            descr='Model name',
            name='model',
            get='model',
            list=True
        )

        self.add_property(
            descr='RPM',
            name='rpm',
            get='rpm',
            list=False,
            enum=['UNKNOWN', 'SSD', '5400', '7200', '10000', '15000']
        )

        self.primary_key = self.get_mapping('name')

    def save(self, this, new=False):
        if new:
            self.context.submit_task(
                self.create_task,
                this.entity,
                callback=lambda s: self.post_save(this, s, new))
            return

        self.context.submit_task(
            self.update_task,
            this.orig_entity[self.save_key_name],
            this.get_diff(),
            callback=lambda s: self.post_save(this, s, new))

    def post_save(self, this, status, new):
        service_name = 'simulator'
        if status == 'FINISHED':
            service = self.context.call_sync('service.query', [('name', '=', service_name)], {'single': True})
            if service['state'] != 'RUNNING':
                if new:
                    action = "created"
                else:
                    action = "updated"
                output_msg_locked(_("Disk '{0}' has been {1} but the service '{2}' is not currently running, please enable the service with '/ service {2} config set enable=yes'".format(this.entity['id'], action, service_name)))
        post_save(this, status)


@description("Tools for simulating aspects of a NAS")
class SimulatorNamespace(Namespace):
    def __init__(self, name, context):
        super(SimulatorNamespace, self).__init__(name)
        self.context = context

    def namespaces(self):
        return [
            DisksNamespace('disk', self.context)
        ]


def _init(context):
    context.attach_namespace('/', SimulatorNamespace('simulator', context))
