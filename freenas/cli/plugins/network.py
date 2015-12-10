#+
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


import re
import gettext
from freenas.cli.namespace import (
    Namespace, EntityNamespace, ConfigNamespace, Command,
    RpcBasedLoadMixin, TaskBasedSaveMixin, description, CommandException
)
from freenas.cli.output import ValueType
from freenas.cli.utils import post_save


t = gettext.translation('freenas-cli', fallback=True)
_ = t.gettext


def set_netmask(entity, netmask):
    nm = None
    if re.match("^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", netmask):
        nm = 0
        for octet in netmask.split('.'):
            nm += bin(int(octet)).count("1")
    elif netmask.isdigit():
        nm = int(netmask)

    if nm is None:
        raise CommandException(_("Invalid netmask: {0}".format(netmask)))

    entity['netmask'] = nm


class InterfaceCreateCommand(Command):
    def run(self, context, args, kwargs, opargs):
        pass


@description("Enables or disables a network interface")
class InterfaceManageCommand(Command):
    """
    Usage: up, down

    Enables or disables a network interface.
    """
    def __init__(self, parent, up):
        self.parent = parent
        self.up = up

    @property
    def description(self):
        if self.up:
            return _("Starts an interface")
        else:
            return _("Shutdowns an interface")

    def run(self, context, args, kwargs, opargs):
        if self.up:
            context.submit_task(
                'network.interface.up',
                self.parent.primary_key,
                callback=lambda s: post_save(self.parent, s)
            )
        else:
            context.submit_task(
                'network.interface.down',
                self.parent.primary_key,
                callback=lambda s: post_save(self.parent, s)
            )


@description("Renews IP lease for network interface")
class InterfaceRenewCommand(Command):
    """
    Usage: renew

    Renews IP lease for network interface
    """
    def __init__(self, parent):
        self.parent = parent

    def run(self, context, args, kwargs, opargs):
        context.submit_task(
            'network.interface.renew',
            self.parent.primary_key,
            callback=lambda s: post_save(self.parent, s)
        )


@description("Network interfaces configuration")
class InterfacesNamespace(RpcBasedLoadMixin, TaskBasedSaveMixin, EntityNamespace):
    def __init__(self, name, context):
        super(InterfacesNamespace, self).__init__(name, context)

        self.query_call = 'network.interfaces.query'
        self.create_task = 'network.interface.create'
        self.delete_task = 'network.interface.delete'
        self.update_task = 'network.interface.configure'
        self.required_props = ['type']
        self.localdoc['CreateEntityCommand'] = ("""\
            Usage: create type=<type>

            Examples:
                create type=LAGG
                create type=VLAN
                create type=BRIDGE

            Creates a logical interface. You must create an interface before setting any properties for it.""")
        self.entity_localdoc['SetEntityCommand'] = ("""\
            Usage: set <property>=<value> ...

            Examples: set dhcp=true
                      set ipv6_disable=true 
                      set enabled=false

            Sets a network interface property. For a list of properties, see 'help properties'.""")

        self.link_states = {
            'LINK_STATE_UP': _("up"),
            'LINK_STATE_DOWN': _("down"),
            'LINK_STATE_UNKNOWN': _("unknown")
        }

        self.link_types = {
            'ETHER': _("Ethernet")
        }

        self.createable = lambda entity: entity['type'] != 'ETHER'

        self.add_property(
            descr='Name',
            name='name',
            get='id',
            set=None,
            list=True
        )

        self.add_property(
            descr='Type',
            name='type',
            get='type',
            set='type',
            enum_set=['VLAN', 'BRIDGE', 'LAGG'],
            usersetable=False,
            list=True
        )

        self.add_property(
            descr='Enabled',
            name='enabled',
            get='enabled',
            type=ValueType.BOOLEAN,
            createsetable=False,
            list=True
        )

        self.add_property(
            descr='DHCP',
            name='dhcp',
            get='dhcp',
            type=ValueType.BOOLEAN,
            createsetable=False,
            list=True
        )

        self.add_property(
            descr='IPv6 autoconfiguration',
            name='ipv6_autoconf',
            get='rtadv',
            type=ValueType.BOOLEAN,
            createsetable=False,
            list=False
        )

        self.add_property(
            descr='Disable IPv6',
            name='ipv6_disable',
            get='noipv6',
            type=ValueType.BOOLEAN,
            createsetable=False,
            list=False
        )

        self.add_property(
            descr='Link address',
            name='link_address',
            get='status.link_address',
            createsetable=False,
            list=True
        )

        self.add_property(
            descr='IP configuration',
            name='ip_config',
            get=self.get_ip_config,
            set=None,
            list=True,
            type=ValueType.SET
        )

        self.add_property(
            descr='Link state',
            name='link_state',
            get=self.get_link_state,
            set=None,
            list=True
        )

        self.add_property(
            descr='State',
            name='state',
            get=self.get_iface_state,
            set=None,
            list=True
        )

        self.add_property(
            descr='Parent interface',
            name='vlan_parent',
            get='vlan.parent',
            list=False,
            createsetable=False,
            type=ValueType.STRING,
            condition=lambda e: e['type'] == 'VLAN'
        )

        self.add_property(
            descr='VLAN tag',
            name='vlan-tag',
            get='vlan.tag',
            list=False,
            createsetable=False,
            type=ValueType.NUMBER,
            condition=lambda e: e['type'] == 'VLAN'
        )

        self.add_property(
            descr='Aggregation protocol',
            name='protocol',
            get='lagg.protocol',
            list=False,
            createsetable=False,
            type=ValueType.STRING,
            condition=lambda e: e['type'] == 'LAGG'
        )

        self.add_property(
            descr='Member interfaces',
            name='ports',
            get='lagg.ports',
            list=False,
            createsetable=False,
            type=ValueType.SET,
            condition=lambda e: e['type'] == 'LAGG'
        )

        self.add_property(
            descr='Member interfaces',
            name='members',
            get='bridge.members',
            list=False,
            createsetable=False,
            type=ValueType.SET,
            condition=lambda e: e['type'] == 'BRIDGE'
        )

        self.primary_key = self.get_mapping('name')
        self.entity_commands = lambda this: {
            'up': InterfaceManageCommand(this, True),
            'down': InterfaceManageCommand(this, False),
            'renew': InterfaceRenewCommand(this)
        }

        self.leaf_entity_namespace = lambda this: AliasesNamespace('aliases', self.context, this)
        self.leaf_harborer = True

    def get_link_state(self, entity):
        return self.link_states[entity['status.link_state']]

    def get_iface_state(self, entity):
        return _("up") if 'UP' in entity['status.flags'] else _("down")

    def get_ip_config(self, entity):
        for i in entity['status']['aliases']:
            if i['type'] not in ('INET', 'INET6'):
                continue

            yield '{0}/{1}'.format(i['address'], i['netmask'])

    def save(self, this, new=False, callback=None):
        if callback is None:
            callback = lambda s: post_save(this, s)
        if new:
            self.context.submit_task(
                'network.interface.create',
                this.entity['type'],
                callback=callback
            )
            this.modified = False
            return

        self.context.submit_task(
            'network.interface.configure',
            this.entity['id'], this.get_diff(),
            callback=callback
        )
        this.modified = False


@description("Interface addresses")
class AliasesNamespace(EntityNamespace):
    def __init__(self, name, context, parent):
        super(AliasesNamespace, self).__init__(name, context)
        self.parent = parent
        self.allow_edit = False
        self.required_props = ['address', 'netmask']
        self.localdoc['CreateEntityCommand'] = ("""\
            Usage: create <address> netmask=<netmask> type=<type> <property>=<value> ...

            Examples: create 192.168.1.1 netmask=255.255.0.0
                      create fda8:06c3:ce53:a890:0000:0000:0000:0005 netmask=64 type=INET6
                      create 10.10.0.1 netmask=16 broadcast=10.10.0.0

            Available properties: type=[INET, INET6], address, netmask, broadcast

            Creates a network interface alias. Aliases cannot be edited after creation so if you need to change an alias you must delete it then recreate it.""")

        self.add_property(
            descr='Address family',
            name='type',
            get='type',
            list=True,
            enum=['INET', 'INET6']
        )

        self.add_property(
            descr='IP address',
            name='address',
            get='address',
            list=True
        )

        self.add_property(
            descr='Netmask',
            name='netmask',
            get='netmask',
            set=set_netmask,
            list=True
        )

        self.add_property(
            descr='Broadcast address',
            name='broadcast',
            get='broadcast',
            list=True
        )

        self.primary_key = self.get_mapping('address')

    def get_one(self, name):
        f = [a for a in self.parent.entity['aliases'] if a['address'] == name]
        return f[0] if f else None

    def query(self, params, options):
        return self.parent.entity.get('aliases', [])

    def my_post_save(self, this, status):
        if status == 'FINISHED':
            this.saved = True
        if status in ['FINISHED', 'FAILED', 'ABORTED', 'CANCELLED']:
            this.modified = False
            self.parent.load()

    def my_post_delete(self, status):
        if status in ['FINISHED', 'FAILED', 'ABORTED', 'CANCELLED']:
            self.parent.load()

    def save(self, this, new=False):
        if 'aliases' not in self.parent.entity:
            self.parent.entity['aliases'] = []

        self.parent.entity['aliases'].append(this.entity)
        self.parent.parent.save(
            self.parent,
            callback=lambda s: self.my_post_save(this, s)
        )

    def delete(self, address, kwargs):
        self.parent.entity['aliases'] = [a for a in self.parent.entity['aliases'] if a['address'] != address]
        self.parent.parent.save(
            self.parent,
            callback=lambda s: self.my_post_delete(s)
        )


class MembersNamespace(EntityNamespace):
    def __init__(self, name, context, parent):
        pass


@description("Static host names database")
class HostsNamespace(RpcBasedLoadMixin, TaskBasedSaveMixin, EntityNamespace):
    def __init__(self, name, context):
        super(HostsNamespace, self).__init__(name, context)

        self.query_call = 'network.hosts.query'
        self.create_task = 'network.hosts.create'
        self.update_task = 'network.hosts.update'
        self.delete_task = 'network.hosts.delete'
        self.required_props = ['name', 'address']

        self.add_property(
            descr='IP address',
            name='address',
            get='address',
            list=True
        )

        self.add_property(
            descr='Hostname',
            name='name',
            get='id',
            list=True
        )

        self.primary_key = self.get_mapping('name')


@description("Global network configuration")
class GlobalConfigNamespace(ConfigNamespace):
    def __init__(self, name, context):
        super(GlobalConfigNamespace, self).__init__(name, context)
        self.config_call = "network.config.get_global_config"

        self.add_property(
            descr='IPv4 gateway',
            name='ipv4_gateway',
            get='gateway.ipv4',
            list=True
        )

        self.add_property(
            descr='IPv6 gateway',
            name='ipv6_gateway',
            get='gateway.ipv6',
            list=True
        )

        self.add_property(
            descr='DNS servers',
            name='dns_servers',
            get='dns.addresses',
            list=True,
            type=ValueType.SET
        )

        self.add_property(
            descr='DNS search domains',
            name='dns_search',
            get='dns.search',
            list=True,
            type=ValueType.SET
        )

        self.add_property(
            descr='DHCP will assign default gateway',
            name='dhcp_gateway',
            get='dhcp.assign_gateway',
            list=True,
            type=ValueType.BOOLEAN
        )

        self.add_property(
            descr='DHCP will assign DNS servers addresses',
            name='dhcp_dns',
            get='dhcp.assign_dns',
            list=True,
            type=ValueType.BOOLEAN
        )

    # def load(self):
    #    self.entity = self.context.call_sync('')
    #    self.orig_entity = copy.deepcopy(self.entity)

    def save(self):
        return self.context.submit_task(
            'network.configure',
            self.get_diff(),
            callback=lambda s: post_save(self, s)
        )


@description("Routing configuration")
class RoutesNamespace(RpcBasedLoadMixin, TaskBasedSaveMixin, EntityNamespace):
    def __init__(self, name, context):
        super(RoutesNamespace, self).__init__(name, context)
        self.context = context

        self.query_call = 'network.routes.query'
        self.create_task = 'network.routes.create'
        self.update_task = 'network.routes.update'
        self.delete_task = 'network.routes.delete'
        self.required_props = ['name', 'gateway', 'network', 'netmask']
        self.localdoc['CreateEntityCommand'] = ("""\
            Usage: create name=<name> gateway=<gateway> network=<network> netmask=<netmask>

            Examples: create name=default gateway=10.0.0.1 network=10.0.0.0 netmask=255.255.255.0
                      create name=foo gateway=192.168.0.1 network=192.168.0.0 netmask=16 
                      create name=ipvsix gateway=fda8:06c3:ce53:a890:0000:0000:0000:0001 network=fda8:06c3:ce53:a890:0000:0000:0000:0000 netmask=64 type=INET6

            Creates a network route. For a list of properties, see 'help properties'.""")
        self.entity_localdoc['SetEntityCommand'] = ("""\
            Usage: set <property>=<value> ...

            Examples: set name=newname
                      set gateway=172.16.0.1
                      set netmask=16

            Sets a network route property. For a list of properties, see 'help properties'.""")

        self.skeleton_entity = {
            'type': 'INET'
        }

        self.add_property(
            descr='Name',
            name='name',
            get='id',
            list=True
        )

        self.add_property(
            descr='Address family',
            name='type',
            get='type',
            list=True,
            enum=['INET', 'INET6']
        )

        self.add_property(
            descr='Gateway',
            name='gateway',
            get='gateway',
            list=True
        )

        self.add_property(
            descr='Network',
            name='network',
            get='network',
            list=True
        )

        self.add_property(
            descr='Subnet prefix',
            name='netmask',
            get='netmask',
            set=set_netmask,
        )

        self.primary_key = self.get_mapping('name')


@description("IPMI configuration")
class IPMINamespace(EntityNamespace):
    def __init__(self, name, context):
        super(IPMINamespace, self).__init__(name, context)
        self.context = context

        self.add_property(
            descr='Channel',
            name='channel',
            get='channel',
            set=None,
            list=True
        )

        self.add_property(
            descr='DHCP',
            name='dhcp',
            get='dhcp',
            list=True,
            type=ValueType.BOOLEAN
        )

        self.add_property(
            descr='IP Address',
            name='address',
            get='address',
            list=True
        )

        self.add_property(
            descr='Netmask',
            name='netmask',
            get='netmask',
            set=set_netmask,
            list=True
        )

        self.add_property(
            descr='Gateway',
            name='gateway',
            get='gateway',
            list=False
        )

        self.add_property(
            descr='VLAN ID',
            name='vlan_id',
            get='vlan_id',
            list=False
        )

        self.add_property(
            descr='Password',
            name='password',
            get=None,
            set='password',
            list=False
        )

        self.primary_key = self.get_mapping('channel')

    def query(self, params, options):
        result = []
        for chan in self.context.call_sync('ipmi.channels'):
            result.append(self.context.call_sync('ipmi.get_config', chan))

        return result

    def get_one(self, chan):
        return self.context.call_sync('ipmi.get_config', chan)

    def save(self, this, new=False):
        assert not new

        self.context.submit_task(
            'ipmi.configure',
            this.entity['channel'],
            this.get_diff(),
            callback=lambda s: post_save(this, s)
        )


@description("Network configuration")
class NetworkNamespace(Namespace):
    def __init__(self, name, context):
        super(NetworkNamespace, self).__init__(name)
        self.context = context

    def namespaces(self):
        ret = [
            InterfacesNamespace('interface', self.context),
            RoutesNamespace('route', self.context),
            HostsNamespace('host', self.context),
            GlobalConfigNamespace('config', self.context)
        ]

        if self.context.call_sync('ipmi.is_ipmi_loaded'):
            ret.append(IPMINamespace('ipmi', self.context))

        return ret


def _init(context):
    context.attach_namespace('/', NetworkNamespace('network', context))
