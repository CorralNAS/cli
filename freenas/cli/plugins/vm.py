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

import sys
import tty
import curses
import gettext
import termios
from freenas.cli.output import Sequence
from freenas.dispatcher.shell import VMConsoleClient
from freenas.cli.namespace import (
    EntityNamespace, Command, NestedObjectLoadMixin, NestedObjectSaveMixin, EntitySubscriberBasedLoadMixin,
    RpcBasedLoadMixin, TaskBasedSaveMixin, description, ListCommand, CommandException
)
from freenas.cli.output import ValueType
from freenas.cli.utils import post_save


t = gettext.translation('freenas-cli', fallback=True)
_ = t.gettext


class VMConsole(object):
    def __init__(self, context, id, name):
        self.context = context
        self.id = id
        self.name = name
        self.conn = None
        self.stdscr = None

    def on_data(self, data):
        sys.stdout.buffer.write(data)
        sys.stdout.buffer.flush()

    def connect(self):
        token = self.context.call_sync('containerd.management.request_console', self.id)
        self.conn = VMConsoleClient(self.context.hostname, token)
        self.conn.on_data(self.on_data)
        self.conn.open()

    def start(self):
        stdin_fd = sys.stdin.fileno()
        old_stdin_settings = termios.tcgetattr(stdin_fd)
        try:
            tty.setraw(stdin_fd)
            self.connect()
            while True:
                ch = sys.stdin.read(1)
                if ch == '\x1d':
                    self.conn.close()
                    break

                self.conn.write(ch)
        finally:
            termios.tcsetattr(stdin_fd, termios.TCSADRAIN, old_stdin_settings)
            curses.wrapper(lambda x: x)


class StartVMCommand(Command):
    def __init__(self, parent):
        self.parent = parent

    def run(self, context, args, kwargs, opargs):
        context.submit_task('container.start', self.parent.entity['id'])


class StopVMCommand(Command):
    def __init__(self, parent):
        self.parent = parent

    def run(self, context, args, kwargs, opargs):
        context.submit_task('container.stop', self.parent.entity['id'])


class KillVMCommand(Command):
    def __init__(self, parent):
        self.parent = parent

    def run(self, context, args, kwargs, opargs):
        context.submit_task('container.stop', self.parent.entity['id'], True)


class RebootVMCommand(Command):
    """
    Usage: reboot force=<force>

    Examples:
        reboot
        reboot force=yes

    Reboots container
    """
    def __init__(self, parent):
        self.parent = parent

    def run(self, context, args, kwargs, opargs):
        force = kwargs.get('force', False)
        context.submit_task('container.reboot', self.parent.entity['id'], force)


class ConsoleCommand(Command):
    """
    Usage: console

    Examples:
        console

    Connects to container serial console. ^] returns to CLI
    """
    def __init__(self, parent):
        self.parent = parent

    def run(self, context, args, kwargs, opargs):
        console = VMConsole(context, self.parent.entity['id'], self.parent.entity['name'])
        console.start()


@description("Import virtual machine from volume")
class ImportVMCommand(Command):
    """
    Usage: import <name> volume=<volume>

    Imports a VM.
    """
    def __init__(self, parent):
        self.parent = parent

    def run(self, context, args, kwargs, opargs):
        try:
            name = args[0]
        except IndexError:
            raise CommandException(_("Please specify the name of VM."))
        volume = kwargs.get('volume', None)
        if not volume:
            raise CommandException(_("Please specify which volume is containing a VM being imported."))
        context.submit_task('container.import', name, volume, callback=lambda s, t: post_save(self.parent, t))


@description("Configure and manage virtual machines")
class VMNamespace(TaskBasedSaveMixin, EntitySubscriberBasedLoadMixin, EntityNamespace):
    """
    The vm namespace provides commands for listing, importing,
    creating, and managing virtual machines.
    """
    def __init__(self, name, context):
        super(VMNamespace, self).__init__(name, context)
        self.entity_subscriber_name = 'container'
        self.create_task = 'container.create'
        self.update_task = 'container.update'
        self.delete_task = 'container.delete'
        self.required_props = ['name', 'volume']
        self.primary_key_name = 'name'

        def set_memsize(o, v):
            o['config.memsize'] = int(v / 1024 / 1024)

        self.skeleton_entity = {
            'type': 'VM',
            'devices': [],
            'config': {}
        }

        self.add_property(
            descr='VM Name',
            name='name',
            get='name',
            list=True
        )

        self.add_property(
            descr='Template name',
            name='template',
            get='template.name'
        )

        self.add_property(
            descr='State',
            name='state',
            get='status.state',
            set=None
        )

        self.add_property(
            descr='Volume',
            name='volume',
            get='target',
            createsetable=True,
            usersetable=False
        )

        self.add_property(
            descr='Description',
            name='description',
            get='description',
            list=False
        )

        self.add_property(
            descr='Memory size (MB)',
            name='memsize',
            get=lambda o: o['config.memsize'] * 1024 * 1024,
            set=set_memsize,
            list=True,
            type=ValueType.SIZE
        )

        self.add_property(
            descr='CPU cores',
            name='cores',
            get='config.ncpus',
            list=True,
            type=ValueType.NUMBER
        )

        self.add_property(
            descr='Boot device',
            name='boot_device',
            get='config.boot_device',
            list=False
        )

        self.add_property(
            descr='Boot partition (for GRUB)',
            name='boot_partition',
            get='config.boot_partition',
            list=False
        )

        self.add_property(
            descr='Bootloader type',
            name='bootloader',
            get='config.bootloader',
            list=False,
            enum=['BHYVELOAD', 'GRUB']
        )

        self.add_property(
            descr='Cloud-init data',
            name='cloud_init',
            get='config.cloud_init',
            list=False,
        )

        self.add_property(
            descr='Enabled',
            name='enabled',
            get='enabled',
            list=True,
            type=ValueType.BOOLEAN
        )

        self.add_property(
            descr='Immutable',
            name='immutable',
            get='immutable',
            list=False,
            usersetable=False,
            type=ValueType.BOOLEAN
        )

        self.add_property(
            descr='Readme',
            name='readme',
            get='template.readme',
            set='template.readme',
            list=False,
            type=ValueType.STRING_HEAD
        )

        self.primary_key = self.get_mapping('name')
        self.entity_namespaces = lambda this: [
            VMDisksNamespace('disks', self.context, this),
            VMNicsNamespace('nic', self.context, this),
            VMVolumesNamespace('volume', self.context, this)
        ]

        self.entity_commands = lambda this: {
            'start': StartVMCommand(this),
            'stop': StopVMCommand(this),
            'kill': KillVMCommand(this),
            'reboot': RebootVMCommand(this),
            'console': ConsoleCommand(this),
            'readme': ReadmeCommand(this)
        }

        self.extra_commands = {
            'import': ImportVMCommand(self)
        }

    def namespaces(self):
        yield TemplateNamespace('template', self.context)
        for namespace in super(VMNamespace, self).namespaces():
            yield namespace


class VMDisksNamespace(NestedObjectLoadMixin, NestedObjectSaveMixin, EntityNamespace):
    def __init__(self, name, context, parent):
        super(VMDisksNamespace, self).__init__(name, context)
        self.parent = parent
        self.primary_key_name = 'name'
        self.extra_query_params = [('type', 'in', ['DISK', 'CDROM'])]
        self.parent_path = 'devices'
        self.skeleton_entity = {
            'type': 'DISK',
            'properties': {}
        }

        self.add_property(
            descr='Disk name',
            name='name',
            get='name'
        )

        self.add_property(
            descr='Disk type',
            name='type',
            get='type',
            enum=['DISK', 'CDROM']
        )

        self.add_property(
            descr='Disk mode',
            name='mode',
            get='properties.mode',
            enum=['AHCI', 'VIRTIO']
        )

        self.add_property(
            descr='Disk size',
            name='size',
            get='properties.size',
            type=ValueType.STRING,
            condition=lambda e: e['type'] == 'DISK'
        )

        self.add_property(
            descr='Image path',
            name='path',
            get='properties.path',
            condition=lambda e: e['type'] == 'CDROM'
        )

        self.primary_key = self.get_mapping('name')


class VMNicsNamespace(NestedObjectLoadMixin, NestedObjectSaveMixin, EntityNamespace):
    def __init__(self, name, context, parent):
        super(VMNicsNamespace, self).__init__(name, context)
        self.parent = parent
        self.primary_key_name = 'name'
        self.extra_query_params = [('type', '=', 'NIC')]
        self.parent_path = 'devices'
        self.skeleton_entity = {
            'type': 'NIC',
            'properties': {}
        }

        self.add_property(
            descr='NIC name',
            name='name',
            get='name'
        )

        self.add_property(
            descr='NIC type',
            name='type',
            get='properties.type',
            enum=['NAT', 'BRIDGE', 'MANAGEMENT']
        )

        self.add_property(
            descr='Bridge with',
            name='bridge',
            get='properties.bridge'
        )

        self.add_property(
            descr='MAC address',
            name='macaddr',
            get='properties.link_address'
        )

        self.primary_key = self.get_mapping('name')


class VMVolumesNamespace(NestedObjectLoadMixin, NestedObjectSaveMixin, EntityNamespace):
    def __init__(self, name, context, parent):
        super(VMVolumesNamespace, self).__init__(name, context)
        self.parent = parent
        self.primary_key_name = 'name'
        self.extra_query_params = [('type', '=', 'VOLUME')]
        self.parent_path = 'devices'
        self.skeleton_entity = {
            'type': 'VOLUME',
            'properties': {}
        }

        self.add_property(
            descr='Volume name',
            name='name',
            get='name'
        )

        self.add_property(
            descr='Volume type',
            name='type',
            get='properties.type',
            enum=['VT9P']
        )

        self.add_property(
            descr='Destination path',
            name='destination',
            get='properties.destination'
        )

        self.add_property(
            descr='Automatically create storage',
            name='auto',
            get='properties.auto',
            type=ValueType.BOOLEAN
        )

        self.primary_key = self.get_mapping('name')


@description("Container templates operations")
class TemplateNamespace(RpcBasedLoadMixin, EntityNamespace):
    def __init__(self, name, context):
        super(TemplateNamespace, self).__init__(name, context)
        self.query_call = 'container.template.query'
        self.primary_key_name = 'template.name'
        self.allow_create = False

        self.skeleton_entity = {
            'type': 'VM',
            'devices': [],
            'config': {}
        }

        self.add_property(
            descr='Name',
            name='name',
            get='template.name',
            usersetable=False,
            list=True
        )

        self.add_property(
            descr='Description',
            name='description',
            get='template.description',
            usersetable=False,
            list=True
        )

        self.add_property(
            descr='Created at',
            name='created_at',
            get='template.created_at',
            usersetable=False,
            list=False,
            type=ValueType.TIME
        )

        self.add_property(
            descr='Updated at',
            name='updated_at',
            get='template.updated_at',
            usersetable=False,
            list=True,
            type=ValueType.TIME
        )

        self.add_property(
            descr='Author',
            name='author',
            get='template.author',
            usersetable=False,
            list=False
        )

        self.add_property(
            descr='Memory size (MB)',
            name='memsize',
            get='config.memsize',
            usersetable=False,
            list=False,
            type=ValueType.NUMBER
        )

        self.add_property(
            descr='CPU cores',
            name='cores',
            get='config.ncpus',
            usersetable=False,
            list=False,
            type=ValueType.NUMBER
        )

        self.add_property(
            descr='Boot device',
            name='boot_device',
            get='config.boot_device',
            usersetable=False,
            list=False
        )

        self.add_property(
            descr='Bootloader type',
            name='bootloader',
            get='config.bootloader',
            list=False,
            usersetable=False,
            enum=['BHYVELOAD', 'GRUB']
        )

        self.add_property(
            descr='Template images cached',
            name='cached',
            get='template.cached',
            usersetable=False,
            list=False,
            type=ValueType.BOOLEAN
        )

        self.primary_key = self.get_mapping('name')
        self.extra_commands = {
            'show': FetchShowCommand(self)
        }
        self.entity_commands = self.get_entity_commands

    def get_entity_commands(self, this):
        this.load()
        commands = {
            'download': DownloadImagesCommand(this),
            'readme': ReadmeCommand(this)
        }

        if this.entity is not None:
            template = this.entity.get('template')
            if template:
                if template.get('cached', False):
                    commands['delete'] = DeleteImagesCommand(this)

        return commands


@description("Downloads templates from git")
class FetchShowCommand(ListCommand):
    """
    Usage: show

    Example: show

    Refreshes local cache of VM templates and then shows them.
    """
    def __init__(self, parent):
        self.parent = parent

    def run(self, context, args, kwargs, opargs, filtering=None):
        context.call_task_sync('container.template.fetch')
        return super(FetchShowCommand, self).run(context, args, kwargs, opargs, filtering)


@description("Downloads container images to the local cache")
class DownloadImagesCommand(Command):
    """
    Usage: download

    Example: download

    Downloads container template images to the local cache.
    """
    def __init__(self, parent):
        self.parent = parent

    def run(self, context, args, kwargs, opargs, filtering=None):
        context.submit_task('container.cache.update', self.parent.entity['template']['name'])


@description("Shows readme entry of selected VM template")
class ReadmeCommand(Command):
    """
    Usage: readme

    Example: readme

    Shows readme entry of selected VM
    """
    def __init__(self, parent):
        self.parent = parent

    def run(self, context, args, kwargs, opargs, filtering=None):
        if self.parent.entity['template'].get('readme'):
            return Sequence(self.parent.entity['template']['readme'])
        else:
            return Sequence("Selected template does not have readme entry")


@description("Deletes container images from the local cache")
class DeleteImagesCommand(Command):
    """
    Usage: delete

    Example: delete

    Deletes container template images from the local cache.
    """
    def __init__(self, parent):
        self.parent = parent

    def run(self, context, args, kwargs, opargs, filtering=None):
        context.submit_task('container.cache.delete', self.parent.entity['template']['name'])


def _init(context):
    context.attach_namespace('/', VMNamespace('vm', context))
