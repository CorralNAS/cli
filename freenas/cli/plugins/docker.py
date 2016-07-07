#
# Copyright 2016 iXsystems, Inc.
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

from freenas.dispatcher.shell import VMConsoleClient
from freenas.cli.namespace import (
    Namespace, EntityNamespace, Command, NestedObjectLoadMixin, NestedObjectSaveMixin, EntitySubscriberBasedLoadMixin,
    RpcBasedLoadMixin, TaskBasedSaveMixin, description, ListCommand, CommandException
)
from freenas.cli.output import ValueType
from freenas.cli.utils import post_save
from freenas.utils import first_or_default


class DockerHostNamespace(EntitySubscriberBasedLoadMixin, EntityNamespace):
    def __init__(self, name, context):
        super(DockerHostNamespace, self).__init__(name, context)
        self.entity_subscriber_name = 'docker.host'
        self.primary_key_name = 'name'

        self.add_property(
            descr='VM name',
            name='name',
            get='name',
            set=None,
            list=True
        )

        self.add_property(
            descr='State',
            name='state',
            get='state',
            set=None,
            list=True
        )

        self.add_property(
            descr='Operating system',
            name='os',
            get='status.os',
            set=None,
            list=False
        )

        self.add_property(
            descr='Docker unique ID',
            name='docker_unique_id',
            get='status.unique_id',
            set=None,
            list=False
        )

        self.primary_key = self.get_mapping('name')


class DockerContainerNamespace(EntitySubscriberBasedLoadMixin, TaskBasedSaveMixin, EntityNamespace):
    def __init__(self, name, context):
        super(DockerContainerNamespace, self).__init__(name, context)
        self.entity_subscriber_name = 'docker.container'
        self.create_task = 'docker.container.create'
        self.delete_task = 'docker.container.delete'
        self.primary_key_name = 'names.0'

        def get_host(o):
            h = context.entity_subscribers['docker.host'].query(('id', '=', o['host']), single=True)
            return h['name'] if h else None

        def set_host(o, v):
            h = context.entity_subscribers['docker.host'].query(('name', '=', v), single=True)
            if h:
                o['host'] = h['id']

        self.add_property(
            descr='Name',
            name='name',
            get='names.0',
            list=True
        )

        self.add_property(
            descr='Image name',
            name='image',
            get='image',
            list=True
        )

        self.add_property(
            descr='Command',
            name='command',
            get='command',
            list=True
        )

        self.add_property(
            descr='Status',
            name='status',
            get='status',
            set=None,
            list=True
        )

        self.add_property(
            descr='Host',
            name='host',
            get=get_host,
            set=set_host,
            list=True
        )

        self.primary_key = self.get_mapping('name')
        self.entity_commands = lambda this: {
            'start': DockerContainerStartStopCommand(this, 'start'),
            'stop': DockerContainerStartStopCommand(this, 'stop')
        }


class DockerImageNamespace(EntitySubscriberBasedLoadMixin, EntityNamespace):
    def __init__(self, name, context):
        super(DockerImageNamespace, self).__init__(name, context)
        self.entity_subscriber_name = 'docker.image'
        self.primary_key_name = 'id'

        self.add_property(
            descr='Name',
            name='name',
            get='names.0',
            set=None,
            list=True
        )

        self.add_property(
            descr='Size',
            name='size',
            get='size',
            set=None,
            list=True,
            type=ValueType.SIZE
        )

        self.add_property(
            descr='Created at',
            name='created_at',
            get='created_at',
            set=None,
            list=True
        )

        self.add_property(
            descr='Host',
            name='host',
            get='host',
            set=None,
            list=True
        )

        self.primary_key = self.get_mapping('name')
        self.extra_commands = {
            'pull': DockerImagePullCommand()
        }


class DockerImagePullCommand(Command):
    def run(self, context, args, kwargs, opargs):
        if len(args) != 2:
            raise CommandException("Please specify image name and docker host name")

        hostid = context.entity_subscribers['docker.host'].query(('name', '=', args[1]), single=True)
        if not hostid:
            raise CommandException("Docker host {0} not found".format(args[1]))

        context.submit_task('docker.image.pull', args[0], hostid['id'])


class DockerContainerStartStopCommand(Command):
    def __init__(self, parent, action):
        self.action = action
        self.parent = parent

    def run(self, context, args, kwargs, opargs):
        context.submit_task('docker.container.{0}'.format(self.action), self.parent.entity['id'])


class DockerNamespace(Namespace):
    def __init__(self, name, context):
        super(DockerNamespace, self).__init__(name)
        self.context = context

    def namespaces(self):
        return [
            DockerHostNamespace('host', self.context),
            DockerContainerNamespace('container', self.context),
            DockerImageNamespace('image', self.context)
        ]


def _init(context):
    context.attach_namespace('/', DockerNamespace('docker', context))
