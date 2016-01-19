# +
# Copyright 2014 iXsystems, Inc.
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
from freenas.cli.namespace import (
    Namespace, EntityNamespace, Command, RpcBasedLoadMixin,
    IndexCommand, description, CommandException
)
from freenas.cli.utils import iterate_vdevs, post_save, correct_disk_path
from freenas.cli.output import ValueType, Table, output_msg
import inspect

t = gettext.translation('freenas-cli', fallback=True)
_ = t.gettext


@description("Manage boot environments")
class BootEnvironmentNamespace(RpcBasedLoadMixin, EntityNamespace):
    """
    The environment namespace provides commands for listing and
    managing boot environments.
    """
    def __init__(self, name, context):
        super(BootEnvironmentNamespace, self).__init__(name, context)
        self.query_call = 'boot.environment.query'
        self.primary_key_name = 'name'
        self.allow_edit = False
        self.required_props = ['name']

        self.localdoc['CreateEntityCommand'] = ("""\
            Usage: create name=<bootenv name>

            Example: create foo

            Creates a boot environment""")

        self.entity_localdoc['SetEntityCommand'] = ("""\
            Usage: set name=<newname>

            Example: set name=foo

            Set the name of the current boot environment""")
        self.localdoc['DeleteEntityCommand'] = ("""\
            Usage: delete <bootenv name>

            Example: delete foo

            Deletes a boot environment.""")
        self.localdoc['ListCommand'] = ("""\
            Usage: show

            Lists boot environments, optionally doing filtering and sorting.

            Examples:
                show
                show | search name == default
                show | search active == no
                show | search name~="FreeNAS" | sort name""")

        self.skeleton_entity = {
            'name': None,
            'realname': None
        }

        self.add_property(
            descr='Name',
            name='name',
            get='id',
            usage=_("""Editable value. This is the name of the entry which
            appears in the boot menu."""),
            set='id',
            list=True
            )

        self.add_property(
            descr='Active',
            name='active',
            get='active',
            usage=_("""
            Can be set to yes or no. Yes indicates which boot
            entry was used at last system boot. Only one entry
            can be set to yes."""),
            list=True,
            type=ValueType.BOOLEAN,
            set=None,
            )

        self.add_property(
            descr='Real Name',
            name='realname',
            get='realname',
            usage=_("""
            Read-only name issued when boot environment
            is created."""),
            list=True,
            set=None,
            )

        self.add_property(
            descr='On Reboot',
            name='onreboot',
            get='on_reboot',
            usage=_("""
            Can be set to yes or no. Yes indicates the default
            boot entry for the next system boot. Only one entry
            can be set to yes."""),
            list=True,
            type=ValueType.BOOLEAN,
            set=None,
            )

        self.add_property(
            descr='Mount point',
            name='mountpoint',
            get='mountpoint',
            list=False,
            set=None,
            )

        self.add_property(
            descr='Space used',
            name='space',
            get='space',
            list=True,
            set=None,
            )

        self.add_property(
            descr='Date created',
            name='created',
            get='created',
            list=True,
            set=None,
            )

        self.primary_key = self.get_mapping('name')

        self.entity_commands = lambda this: {
            'activate': ActivateBootEnvCommand(this),
            'rename': RenameBootEnvCommand(this),
        }

    def serialize(self):
        raise NotImplementedError()

    def get_one(self, name):
        return self.context.call_sync(
            self.query_call, [('id', '=', name)], {'single': True}
        )

    def delete(self, name, kwargs):
        self.context.submit_task('boot.environment.delete', [name])

    def save(self, this, new=False):
        if new:
            self.context.submit_task(
                'boot.environment.create',
                this.entity['id'],
                callback=lambda s: post_save(this, s),
                )
        else:
            return


@description("Rename a boot environment")
class RenameBootEnvCommand(Command):
    """
    Usage: rename

    Renames the current boot environment.
    """
    def __init__(self, parent):
        self.parent = parent

    def run(self, context, args, kwargs, opargs):
        try:
            new_be_name = args.pop(0)
        except IndexError:
            raise CommandException('Please provide a target name for the renaming')
        entity = self.parent.entity
        name_property = self.parent.get_mapping('name')
        old_be = entity['id']
        name_property.do_set(entity, new_be_name)
        self.parent.modified = True
        context.submit_task(
            'boot.environment.rename',
            old_be,
            new_be_name,
            callback=lambda s: post_save(self.parent, s)
        )


@description("Activate a boot environment")
class ActivateBootEnvCommand(Command):
    """
    Usage: activate

    Activates the current boot environment
    """
    def __init__(self, parent):
        self.parent = parent

    def run(self, context, args, kwargs, opargs):
        context.submit_task(
            'boot.environment.activate',
            self.parent.entity['id'],
            callback=lambda s: post_save(self.parent, s))


@description("Manage devices in boot pool")
class BootPoolNamespace(Namespace):
    """
    The pool namespace provides commands for listing and managing the devices
    in the boot pool.
    """
    def __init__(self, name, context):
        super(BootPoolNamespace, self).__init__(name)

    def commands(self):
        return {
            '?': IndexCommand(self),
            'show_disks': BootPoolShowDisksCommand(),
            'attach_disk': BootPoolAttachDiskCommand(),
            'detach_disk': BootPoolDetachDiskCommand(),
        }


@description("List the devices in the boot pool")
class BootPoolShowDisksCommand(Command):
    """
    Usage: show_disks

    List the device\(s\) in the boot pool and display
    the status of the boot pool.
    """

    def run(self, context, args, kwargs, opargs):
        volume = context.call_sync('zfs.pool.get_boot_pool')
        result = list(iterate_vdevs(volume['groups']))
        return Table(result, [
            Table.Column('Name', 'path'),
            Table.Column('Status', 'status')
        ])


@description("Attach a device to the boot pool")
class BootPoolAttachDiskCommand(Command):
    """
    Usage: attach_disk <disk>

    Example: attach_disk ada1

    Attaches the specified device\(s\) to the boot pool,
    creating an N-way mirror where N is the total number
    of devices in the pool. The command will fail if a
    device is smaller than the smallest device already in
    the pool.
    """
    def run(self, context, args, kwargs, opargs):
        if not args:
            output_msg("attach_disk requires more arguments.\n{0}".format(inspect.getdoc(self)))
            return
        disk = args.pop(0)
        # The all_disks below is a temporary fix, use this after "select" is working
        # all_disks = context.call_sync('disk.query', [], {"select":"path"})
        all_disks = [d["path"] for d in context.call_sync("disk.query")]
        available_disks = context.call_sync('volume.get_available_disks')
        disk = correct_disk_path(disk)
        if disk not in all_disks:
            output_msg("Disk " + disk + " does not exist.")
            return
        if disk not in available_disks:
            output_msg("Disk " + disk + " is not usable.")
            return
        volume = context.call_sync('zfs.pool.get_boot_pool')
        context.submit_task('boot.attach_disk', volume['groups']['data'][0]['guid'], disk)
        return


@description("Detach a device from the boot pool")
class BootPoolDetachDiskCommand(Command):
    """
    Usage: detach_disk <disk>

    Example: detach_disk ada1

    Detaches the specified device\(s\) from the boot pool,
    reducing the number of devices in the N-way mirror. If
    only one device remains, it has no redundancy. At least
    one device must remain in the pool.
    """
    def run(self, context, args, kwargs, opargs):
        disk = args.pop(0)
        disk = correct_disk_path(disk)
        context.submit_task('boot.detach_disk', disk)
        return


@description("Boot management")
class BootNamespace(Namespace):
    """
    The boot namespace provides commands for listing and managing
    boot environments and the devices in the boot pool.
    """
    def __init__(self, name, context):
        super(BootNamespace, self).__init__(name)
        self.context = context

    def commands(self):
        return {
            '?': IndexCommand(self)
        }

    def namespaces(self):
        return [
            BootPoolNamespace('pool', self.context),
            BootEnvironmentNamespace('environment', self.context)
        ]


def _init(context):
    context.attach_namespace('/', BootNamespace('boot', context))
