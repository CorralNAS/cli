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

import gettext
from freenas.cli.namespace import (
    Namespace, EntityNamespace, ConfigNamespace, Command, NestedObjectLoadMixin, NestedObjectSaveMixin,
    RpcBasedLoadMixin, EntitySubscriberBasedLoadMixin, TaskBasedSaveMixin, description, CommandException
)
from freenas.cli.output import ValueType
from freenas.cli.utils import TaskPromise, post_save, netmask_to_cidr
from freenas.utils.query import get


t = gettext.translation('freenas-cli', fallback=True)
_ = t.gettext


def set_netmask(entity, netmask):
    try:
        netmask_to_cidr(entity, netmask)
    except ValueError as error:
        raise CommandException(error)


class InterfaceCreateCommand(Command):
    def run(self, context, args, kwargs, opargs):
        pass


@description("Enable or disable network interface")
class InterfaceManageCommand(Command):
    """
    Usage: up
           down

    Examples: up
              down

    Enable or disable this network interface.
    """
    def __init__(self, parent, up):
        self.parent = parent
        self.up = up

    @property
    def description(self):
        if self.up:
            return _("Interface set to up")
        else:
            return _("Interface set to down")

    def run(self, context, args, kwargs, opargs):
        if self.up:
            tid = context.submit_task(
                'network.interface.up',
                self.parent.primary_key,
                callback=lambda s, t: post_save(self.parent, s, t)
            )
        else:
            tid = context.submit_task(
                'network.interface.down',
                self.parent.primary_key,
                callback=lambda s, t: post_save(self.parent, s, t)
            )

        return TaskPromise(context, tid)


@description("Renew IP lease")
class InterfaceRenewCommand(Command):
    """
    Usage: renew

    Examples: renew

    Renew IP lease for this network interface.
    """
    def __init__(self, parent):
        self.parent = parent

    def run(self, context, args, kwargs, opargs):
        tid = context.submit_task(
            'network.interface.renew',
            self.parent.primary_key,
            callback=lambda s, t: post_save(self.parent, s, t)
        )

        return TaskPromise(context, tid)


@description("Configure virtual interfaces")
class InterfacesNamespace(EntitySubscriberBasedLoadMixin, TaskBasedSaveMixin, EntityNamespace):
    def __init__(self, name, context):
        super(InterfacesNamespace, self).__init__(name, context)

        self.entity_subscriber_name = 'network.interface'
        self.create_task = 'network.interface.create'
        self.delete_task = 'network.interface.delete'
        self.update_task = 'network.interface.update'
        self.required_props = ['type']
        self.localdoc['CreateEntityCommand'] = ("""\
            Usage: create type=<type>

            Examples:
                create type=LAGG
                create type=VLAN
                create type=BRIDGE

            Creates a virtual interface of specified type. Use LAGG
            for link aggregation or failover, VLAN for 802.1q tagging,
            and BRIDGE for Layer 2 bridging. Once the virtual interface
            is created, type 'help properties' to determine which
            properties can be set.""")
        self.entity_localdoc['SetEntityCommand'] = ("""\
            Usage: set <property>=<value> ...

            Examples: set dhcp=true
                      set ipv6_disable=true
                      set enabled=false
                      set lagg_ports=igb0,igb1
                      set lagg_ports=none

            Sets a network interface property. For a list of properties, see 'help properties'.""")
        self.entity_localdoc['DeleteEntityCommand'] = ("""\
            Usage: delete

            Examples: delete

            Deletes an interface.""")
        self.entity_localdoc['GetEntityCommand'] = ("""\
            Usage: get <field>

            Examples:
                get name
                get link_address
                get dhcp_server_address

            Display value of specified field.""")
        self.localdoc['ListCommand'] = ("""\
            Usage: show

            Lists all routes. Optionally, filter or sort by property.
            Use 'help properties' to list available properties.

            Examples:
                show
                show | search name == em0""")
        self.entity_localdoc['ShowEntityCommand'] = ("""\
            Usage: show

            Examples: show

            Display the property values for the current interface.""")

        self.link_states = {
            'LINK_STATE_UP': _("up"),
            'LINK_STATE_DOWN': _("down"),
            'LINK_STATE_UNKNOWN': _("unknown")
        }

        self.link_types = {
            'ETHER': _("Ethernet")
        }

        self.skeleton_entity = {
            'type': None,
            'aliases': []
        }

        self.createable = lambda entity: entity['type'] != 'ETHER'

        self.add_property(
            descr='Name',
            name='name',
            get='id',
            usage=_("""\
            Name of network interface. Read-only value is
            assigned by operating system."""),
            set=None,
            list=True
        )

        self.add_property(
            descr='Type',
            name='type',
            get='type',
            set='type',
            usage=_("""\
            Can only be specified when using the 'create'
            command. Allowable values are VLAN,
            BRIDGE, or LAGG."""),
            enum=['VLAN', 'BRIDGE', 'LAGG'],
            usersetable=False,
            list=True
        )

        self.add_property(
            descr='Description',
            name='description',
            get='name',
            list=True,
            usage=_("""\
                    A description for the network interface""")
        )

        self.add_property(
            descr='Enabled',
            name='enabled',
            get='enabled',
            usage=_("""\
            Indicates whether or not the interface is
            active or disabled. Can be set to yes or no."""),
            type=ValueType.BOOLEAN,
            list=True
        )

        self.add_property(
            descr='DHCP enabled',
            name='dhcp',
            get='dhcp',
            usage=_("""\
            Indicates whether or not the interface uses
            DHCP to obtain its IP configuration. Can be
            set to yes or no, however, only ONE interface
            on the system can be set to yes."""),
            type=ValueType.BOOLEAN,
            list=True
        )

        self.add_property(
            descr='MTU',
            name='mtu',
            get='mtu',
            type=ValueType.NUMBER,
            list=False,
            usage=_("The maximum transport unit, defaults to 1500 bytes.")
        )

        self.add_property(
            descr='DHCP state',
            name='dhcp_state',
            get='status.dhcp.state',
            set=None,
            list=False,
            condition=lambda e: e['dhcp'],
            usage=_("The current status of the DHCP connection.")
        )

        self.add_property(
            descr='DHCP server address',
            name='dhcp_server_address',
            get='status.dhcp.server_address',
            set=None,
            list=False,
            condition=lambda e: e['dhcp'],
            usage=_("The IP address of the DHCP server.")
        )

        self.add_property(
            descr='DHCP lease start time',
            name='dhcp_lease_start',
            get='status.dhcp.lease_starts_at',
            set=None,
            list=False,
            type=ValueType.TIME,
            condition=lambda e: e['dhcp'],
            usage=_("The starting time of the current DHCP lease.")
        )

        self.add_property(
            descr='DHCP lease end time',
            name='dhcp_lease_end',
            get='status.dhcp.lease_ends_at',
            set=None,
            list=False,
            type=ValueType.TIME,
            condition=lambda e: e['dhcp'],
            usage=_("The ending time of the current DHCP lease.")
        )

        self.add_property(
            descr='DHCP error message',
            name='dhcp_error',
            get='status.dhcp.error',
            set=None,
            list=False,
            condition=lambda e: get(e, 'status.dhcp.error'),
            usage=_("The DHCP connection error message, if any.")
        )

        self.add_property(
            descr='IPv6 autoconfiguration',
            name='ipv6_autoconf',
            get='rtadv',
            usage=_("""\
            Indicates whether or not the interface uses
            rtsold to obtain its IPv6 configuration. Can be
            set to yes or no."""),
            type=ValueType.BOOLEAN,
            list=False
        )

        self.add_property(
            descr='Disable IPv6',
            name='ipv6_disable',
            get='noipv6',
            usage=_("""\
            Indicates whether or not the interface will
            accept an IPv6 configuration. Can be set to yes
            or no."""),
            type=ValueType.BOOLEAN,
            list=False
        )

        self.add_property(
            descr='Link address',
            name='link_address',
            get='status.link_address',
            usage=_("""\
            MAC address of interface. This is a read-only
            property."""),
            set=None,
            list=False
        )

        self.add_property(
            descr='IP configuration',
            name='ip_config',
            get=self.get_ip_config,
            usage=_("""\
            Lists all configured IP and IPv6 addresses
            with their CIDR masks for the interface. This
            is a read-only property."""),
            set=None,
            list=True,
            type=ValueType.SET
        )

        self.add_property(
            descr='Link state',
            name='link_state',
            usage=_("""\
            Indicates whether the interface detects a
            network link. If it displays down, check the
            physical connection to the network. This is a
            read-only property."""),
            get=self.get_link_state,
            set=None,
            list=True
        )

        self.add_property(
            descr='Active media type',
            name='active_media_type',
            get=self.get_media_type,
            set=None,
            list=False
        )

        self.add_property(
            descr='Selected media type',
            name='media_type',
            get='media',
            enum=lambda o: get(o, 'status.supported_media'),
            list=False
        )

        self.add_property(
            descr='State',
            name='state',
            get=self.get_iface_state,
            usage=_("""\
            Indicates whether the interface has been
            configured to be up or down. If it displays
            as down, the enabled property can be used to
            set it to yes."""),
            set=None,
            list=True
        )

        self.add_property(
            descr='Capabilities',
            name='capabilities',
            get='status.capabilities',
            set=None,
            list=False,
            usage="Shows capabilities NIC supported by the NIC",
            type=ValueType.SET
        )

        self.add_property(
            descr='VLAN parent interface',
            name='vlan_parent',
            get='vlan.parent',
            usage=_("""\
            This property only applies to VLAN interfaces.
            It should be set to the physical interface that
            is attached to the VLAN switch port."""),
            list=False,
            type=ValueType.STRING,
            condition=lambda e: e['type'] == 'VLAN'
        )

        self.add_property(
            descr='VLAN tag',
            name='vlan_tag',
            get='vlan.tag',
            usage=_("""\
            This property only applies to VLAN interfaces and
            is mandatory when setting the vlan_parent.
            Must be a valid tag number between 1 and 4095."""),
            list=False,
            type=ValueType.NUMBER,
            condition=lambda e: e['type'] == 'VLAN'
        )

        self.add_property(
            descr='Aggregation protocol',
            name='lagg_protocol',
            get='lagg.protocol',
            usage=_("""\
            This property only applies to LAGG interfaces and
            indicates the type of aggregation protocol to
            use. Allowable values are NONE, ROUNDROBIN,
            FAILOVER, LOADBALANCE, LACP, or ETHERCHANNEL."""),
            list=False,
            type=ValueType.STRING,
            condition=lambda e: e['type'] == 'LAGG',
            enum=['NONE', 'ROUNDROBIN', 'FAILOVER', 'LOADBALANCE', 'LACP', 'ETHERCHANNEL']
        )

        self.add_property(
            descr='Member interfaces',
            name='lagg_ports',
            get='lagg.ports',
            usage=_("""\
            This property only applies to LAGG interfaces and
            indicates which physical interfaces are members
            of the lagg. When specifying multiple interfaces,
            place each interface name within double quotes
            and a comma with space between each interface
            name.  To empty this list, set it to 'none'"""),
            list=False,
            type=ValueType.SET,
            condition=lambda e: e['type'] == 'LAGG'
        )

        self.add_property(
            descr='Member interfaces',
            name='bridge_members',
            get='bridge.members',
            usage=_("""\
            This property only applies to BRIDGE interfaces and
            indicates which physical interfaces are members of
            the bridge. When specifying multiple interfaces, place
            each interface name within double quotes and a comma
            with space between each interface name."""),
            list=False,
            type=ValueType.SET,
            condition=lambda e: e['type'] == 'BRIDGE'
        )

        self.primary_key = self.get_mapping('name')
        self.entity_commands = lambda this: {
            'up': InterfaceManageCommand(this, True),
            'down': InterfaceManageCommand(this, False),
            'renew': InterfaceRenewCommand(this)
        }

        self.entity_namespaces = lambda this: [
            AliasesNamespace('alias', self.context, this)
        ]

    def get_link_state(self, entity):
        return self.link_states[get(entity, 'status.link_state')]

    def get_media_type(self, entity):
        return '{0} {1}'.format(
            get(entity, 'status.active_media_type'),
            get(entity, 'status.active_media_subtype')
        )

    def get_iface_state(self, entity):
        return _("up") if 'UP' in get(entity, 'status.flags') else _("down")

    def get_ip_config(self, entity):
        for i in entity['status']['aliases']:
            if i['type'] not in ('INET', 'INET6'):
                continue

            yield '{0}/{1}'.format(i['address'], i['netmask'])


@description("Interface addresses")
class AliasesNamespace(NestedObjectLoadMixin, NestedObjectSaveMixin, EntityNamespace):
    def __init__(self, name, context, parent):
        super(AliasesNamespace, self).__init__(name, context)
        self.parent = parent
        self.allow_edit = False
        self.parent_path = 'aliases'
        self.required_props = ['address', 'netmask']
        self.primary_key_name = 'address'
        self.localdoc['CreateEntityCommand'] = ("""\
            Usage: create <address> netmask=<netmask> type=<type> <property>=<value> ...

            Examples: create 192.168.1.1 netmask=255.255.0.0
                      create fda8:06c3:ce53:a890:0000:0000:0000:0005 netmask=64 type=INET6
                      create 10.10.0.1 netmask=16 broadcast=10.10.0.0

            Available properties: type=[INET, INET6], address, netmask, broadcast

            Creates a network interface alias. Aliases cannot be edited after creation so if you need to change an alias you must delete it then recreate it.""")
        self.entity_localdoc['DeleteEntityCommand'] = ("""\
            Usage: delete

            Examples: delete

            Deletes an alias.""")
        self.entity_localdoc['GetEntityCommand'] = ("""\
            Usage: get <field>

            Examples:
                get address
                get netmask

            Display value of specified field.""")
        self.entity_localdoc['ShowEntityCommand'] = ("""\
            Usage: show

            Examples: show

            Display the property values for the current alias.""")
        self.entity_localdoc['SetEntityCommand'] = ("""\
            Usage: set <property>=<value> ...

            Examples: set address=192.168.1.1
                      set netmask=24

            Sets an alias property. For a list of properties, see 'help properties'.""")
        self.entity_localdoc['ShowEntityCommand'] = ("""\
            Usage: show

            Examples: show

            Display the property values for the current alias.""")

        self.add_property(
            descr='Address family',
            name='type',
            get='type',
            list=True,
            enum=['INET', 'INET6'],
            usage=_("Address type, acceepts INET or INET6.")
        )

        self.add_property(
            descr='IP address',
            name='address',
            get='address',
            list=True,
            usage=_("The IP address of the alias.")
        )

        self.add_property(
            descr='Netmask',
            name='netmask',
            get='netmask',
            set=set_netmask,
            list=True,
            usage=_("The subnet mask of the alias.")
        )

        self.add_property(
            descr='Broadcast address',
            name='broadcast',
            get='broadcast',
            list=True,
            usage=_("The broadcast address of the alias.")
        )

        self.primary_key = self.get_mapping('address')


@description("Configure hosts entries")
class HostsNamespace(EntitySubscriberBasedLoadMixin, TaskBasedSaveMixin, EntityNamespace):
    """
    The host namespace provides commands for listing and managing the entries in the
    system hosts file. To edit an existing entry, type its name.
    """
    def __init__(self, name, context):
        super(HostsNamespace, self).__init__(name, context)

        self.entity_subscriber_name = 'network.host'
        self.create_task = 'network.host.create'
        self.update_task = 'network.host.update'
        self.delete_task = 'network.host.delete'
        self.required_props = ['name', 'addresses']
        self.localdoc['CreateEntityCommand'] = ("""\
            Usage: create <hostname> addresses=<IP address>,<IP address>,..

            Examples: create myfreenas addresses=10.0.0.1
                      create somehost addresses=10.0.0.2,10.0.0.3

            Add an entry to the hosts table. Specify the hostname
            or FQDN and its associated IP address.""")
        self.entity_localdoc['DeleteEntityCommand'] = ("""\
            Usage: delete

            Examples: delete

            Deletes a host.""")
        self.entity_localdoc['SetEntityCommand'] = ("""\
            Usage: set <property>=<value> ...

            Examples: set name=newname
                      set addresses=172.16.0.1,10.0.0.1

            Sets a network host property. For a list of properties, see 'help properties'.""")
        self.entity_localdoc['GetEntityCommand'] = ("""\
            Usage: get <field>

            Examples:
                get name
                get addresses

            Display value of specified field.""")
        self.localdoc['ListCommand'] = ("""\
            Usage: show

            Lists all routes. Optionally, filter or sort by property.
            Use 'help properties' to list available properties.

            Examples:
                show
                show | search name == somehost""")
        self.entity_localdoc['ShowEntityCommand'] = ("""\
            Usage: show

            Examples: show

            Display the property values for the current host.""")
        self.entity_localdoc['EditEntityCommand'] = ("""\
            Usage: edit <field>

            Examples: edit name

            Opens the default editor for the specified property. The default editor
            is inherited from the shell's $EDITOR which can be set from the shell.
            For a list of properties for the current namespace, see 'help properties'.""")

        self.add_property(
            descr='IP addresses',
            name='addresses',
            get='addresses',
            usage=_("""\
            The IP address to add to the hosts file."""),
            type=ValueType.SET,
            list=True
        )

        self.add_property(
            descr='Hostname',
            name='name',
            get='id',
            usage=_("""\
            The hostname or FQDN associated with that
            IP address."""),
            list=True
        )

        self.primary_key = self.get_mapping('name')


@description("Manage global network settings")
class GlobalConfigNamespace(ConfigNamespace):
    """
    The config namespace provides commands for listing and managing
    global network settings that apply to all interfaces.
    For a list of available properties, type 'help properties'.
    Type 'show" to see current settings.
    """
    def __init__(self, name, context):
        super(GlobalConfigNamespace, self).__init__(name, context)
        self.config_call = "network.config.get_config"
        self.update_task = 'network.config.update'

        self.add_property(
            descr='IPv4 gateway',
            name='ipv4_gateway',
            get='gateway.ipv4',
            usage=_("""\
            IPv4 address of the network's default gateway.
            Only needs to be set when using static addressing
            and will be set to 'none' when using DHCP."""),
            list=True
        )

        self.add_property(
            descr='IPv6 gateway',
            name='ipv6_gateway',
            get='gateway.ipv6',
            usage=_("""\
            IPv6 address of the network's default gateway.
            Only needs to be set when using static addressing
            and access to other IPv6 networks is required."""),
            list=True
        )

        self.add_property(
            descr='DNS servers',
            name='dns_servers',
            get='dns.addresses',
            list=True,
            usage=_("""\
            List of available DNS servers.
            Only needs to be set when using static addressing
            and will be set to 'empty' when using DHCP. When
            setting multiple DNS servers, place each address
            within double quotes and a comma with space between
            each address."""),
            type=ValueType.SET
        )

        self.add_property(
            descr='DNS search domains',
            name='dns_search',
            get='dns.search',
            list=True,
            usage=_("""\
            The name of the search domain.
            Only needs to be set when using static addressing
            and will be set to 'empty' when using DHCP."""),
            type=ValueType.SET
        )

        self.add_property(
            descr='DHCP will assign default gateway',
            name='dhcp_gateway',
            get='dhcp.assign_gateway',
            list=True,
            usage=_("""\
            Can be set to yes or no. Indicates whether or
            not the DHCP server should assign the default
            gateway address. If set to no, you will need
            to manually set the 'ipv4_gateway'."""),
            type=ValueType.BOOLEAN
        )

        self.add_property(
            descr='DHCP will assign DNS servers addresses',
            name='dhcp_dns',
            get='dhcp.assign_dns',
            list=True,
            usage=_("""\
            Can be set to yes or no. Indicates whether or
            not the DHCP server should assign the DNS
            server addresses. If set to no, you will need
            to manually set the 'ipv4_gateway'."""),
            type=ValueType.BOOLEAN
        )


@description("Manage routing table")
class RoutesNamespace(EntitySubscriberBasedLoadMixin, TaskBasedSaveMixin, EntityNamespace):
    def __init__(self, name, context):
        super(RoutesNamespace, self).__init__(name, context)
        self.context = context

        self.entity_subscriber_name = 'network.route'
        self.create_task = 'network.route.create'
        self.update_task = 'network.route.update'
        self.delete_task = 'network.route.delete'
        self.required_props = ['name', 'gateway', 'network', 'netmask']
        self.localdoc['CreateEntityCommand'] = ("""\
            Usage: create name=<name> gateway=<gateway> network=<network> netmask=<netmask>

            Examples: create name=default gateway=10.0.0.1 network=10.0.0.0 netmask=255.255.255.0
                      create name=myroute gateway=192.168.0.1 network=192.168.0.0 netmask=16
                      create name=myipvsix gateway=fda8:06c3:ce53:a890:0000:0000:0000:0001 network=fda8:06c3:ce53:a890:0000:0000:0000:0000 netmask=64 type=INET6

            Creates a network route. For a list of properties, see 'help properties'.""")
        self.entity_localdoc['SetEntityCommand'] = ("""\
            Usage: set <property>=<value> ...

            Examples: set name=newname
                      set gateway=172.16.0.1
                      set netmask=16

            Sets a network route property. For a list of properties, see 'help properties'.""")
        self.entity_localdoc['DeleteEntityCommand'] = ("""\
            Usage: delete

            Examples: delete

            Deletes a route.""")
        self.entity_localdoc['GetEntityCommand'] = ("""\
            Usage: get <field>

            Examples:
                get gateway
                get network
                get netmask

            Display value of specified field.""")
        self.localdoc['ListCommand'] = ("""\
            Usage: show

            Lists all routes. Optionally, filter or sort by property.
            Use 'help properties' to list available properties.

            Examples:
                show
                show | search name == someroute""")
        self.entity_localdoc['ShowEntityCommand'] = ("""\
            Usage: show

            Examples: show

            Display the property values for the current route.""")
        self.entity_localdoc['EditEntityCommand'] = ("""\
            Usage: edit <field>

            Examples: edit name

            Opens the default editor for the specified property. The default editor
            is inherited from the shell's $EDITOR which can be set from the shell.
            For a list of properties for the current namespace, see 'help properties'.""")

        self.skeleton_entity = {
            'type': 'INET'
        }

        self.add_property(
            descr='Name',
            name='name',
            get='id',
            usage=_("""\
            Alphanumeric name for the route."""),
            list=True
        )

        self.add_property(
            descr='Address family',
            name='type',
            get='type',
            usage=_("""\
            Indicates the type of route. Can be set to "INET" or
            "INET6"."""),
            list=True,
            enum=['INET', 'INET6']
        )

        self.add_property(
            descr='Gateway',
            name='gateway',
            usage=_("""\
            The address to add to the routing table, enclosed within
            double quotes."""),
            get='gateway',
            list=True
        )

        self.add_property(
            descr='Network',
            name='network',
            usage=_("""\
            The network address to associate with this route, enclosed
            within double quotes."""),
            get='network',
            list=True
        )

        self.add_property(
            descr='Subnet prefix',
            name='netmask',
            get='netmask',
            usage=_("""\
            The subnet mask for the route, in CIDR or dotted quad
            notation, enclosed within double quotes."""),
            set=set_netmask,
        )

        self.primary_key = self.get_mapping('name')


@description("Set IPMI configuration")
class IPMINamespace(RpcBasedLoadMixin, EntityNamespace):
    def __init__(self, name, context):
        super(IPMINamespace, self).__init__(name, context)
        self.context = context
        self.query_call = 'ipmi.query'
        self.allow_create = False

        self.entity_localdoc['GetEntityCommand'] = ("""\
            Usage: get <field>

            Examples:
                get gateway
                get network
                get netmask

            Display value of specified field.""")
        self.entity_localdoc['ShowEntityCommand'] = ("""\
            Usage: show

            Examples: show

            Display the property values for the IPMI.""")
        self.entity_localdoc['SetEntityCommand'] = ("""\
            Usage: set <property>=<value> ...

            Examples: set address=192.168.1.101
                      set gateway=172.16.0.1
                      set netmask=16

            Sets a network route property. For a list of properties, see 'help properties'.""")
        self.entity_localdoc['EditEntityCommand'] = ("""\
            Usage: edit <field>

            Examples: edit address

            Opens the default editor for the specified property. The default editor
            is inherited from the shell's $EDITOR which can be set from the shell.
            For a list of properties for the current namespace, see 'help properties'.""")

        self.add_property(
            descr='Channel',
            name='id',
            get='id',
            usage=_("""\
            Number representing the channel to use."""),
            set=None,
            list=True
        )

        self.add_property(
            descr='DHCP',
            name='dhcp',
            get='dhcp',
            usage=_("""\
            Indicates whether or not to receive addressing information
            from a DHCP server. Can be set to true or false, with a default
            of true."""),
            list=True,
            type=ValueType.BOOLEAN
        )

        self.add_property(
            descr='IP Address',
            name='address',
            usage=_("""\
            When using a static IP address instead of DHCP, specify it between
            double quotes."""),
            get='address',
            list=True
        )

        self.add_property(
            descr='Netmask',
            name='netmask',
            get='netmask',
            usage=_("""\
            When using a static address instead of DHCP, specify the subnet mask, in
            either CIDR or dotted quad notation, between double quotes."""),
            set=set_netmask,
            list=True
        )

        self.add_property(
            descr='Gateway',
            name='gateway',
            usage=_("""\
            When using a static address instead of DHCP, specify the IP address of
            the default gateway between double quotes."""),
            get='gateway',
            list=False
        )

        self.add_property(
            descr='VLAN ID',
            name='vlan_id',
            usage=_("""\
            When the IPMI out-of-band management interface is not on the same VLAN as
            management networking, specify the VLAN number."""),
            get='vlan_id',
            type=ValueType.NUMBER,
            list=False
        )

        self.add_property(
            descr='Password',
            name='password',
            usage=_("""\
            Specify the password used to connect to the IPMI interface between double
            quotes."""), 
            get=None,
            set='password',
            list=False
        )

        self.primary_key = self.get_mapping('id')

    def save(self, this, new=False):
        assert not new

        return self.context.submit_task(
            'ipmi.update',
            this.entity['id'],
            this.get_diff(),
            callback=lambda s, t: post_save(this, s, t)
        )

    def namespaces(self):
        if getattr(self, 'is_docgen_instance', False):
            return []
        else:
            return super(IPMINamespace, self).namespaces()


@description("Configure networking")
class NetworkNamespace(Namespace):
    """
    The network namespace is used to configure the network interfaces
    recognized by the system, manage the system routing table,
    manage the entries in the system hosts file, and configure
    global network parameters.
    """
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

        if getattr(self, 'is_docgen_instance', False):
            ret.append(IPMINamespace('ipmi', self.context))

        return ret


def _init(context):
    context.attach_namespace('/', NetworkNamespace('network', context))
    context.map_tasks('network.interface.*', InterfacesNamespace)
    context.map_tasks('network.route.*', RoutesNamespace)
    context.map_tasks('network.host.*', HostsNamespace)
    context.map_tasks('network.config.*', GlobalConfigNamespace)
