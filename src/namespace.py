#+
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


import copy
import traceback
import errno
import collections
from texttable import Texttable
from fnutils.query import wrap
from output import (ValueType, Object, Table, output_object, output_table, output_list,
                    output_msg, output_is_ascii, read_value, format_value)


def description(descr):
    def wrapped(fn):
        fn.description = descr
        return fn

    return wrapped


class Namespace(object):
    def __init__(self, name):
        self.name = name
        self.nslist = []

    def help(self):
        pass

    def get_name(self):
        return self.name

    def commands(self):
        # lazy import to avoid circular import hell
        # TODO: can this be avoided? If so please!
        from commands import HelpCommand
        return {
            '?': IndexCommand(self),
            'help': HelpCommand(),
        }

    def namespaces(self):
        return self.nslist

    def on_enter(self):
        pass

    def on_leave(self):
        return True

    def register_namespace(self, ns):
        self.nslist.append(ns)


class Command(object):
    def run(self, context, args, kwargs, opargs):
        raise NotImplementedError()

    def complete(self, context, tokens):
        return []


class FilteringCommand(Command):
    def run(self, context, args, kwargs, opargs, filtering=None):
        raise NotImplementedError()


class PipeCommand(Command):
    def run(self, context, args, kwargs, opargs, input=None):
        pass

    def serialize_filter(self, context, args, kwargs, opargs):
        raise NotImplementedError()


class CommandException(Exception):
    def __init__(self, message, code=None, extra=None):
        self.code = code
        self.message = message
        self.extra = extra
        self.stacktrace = traceback.format_exc()

    def __str__(self):
        if self.code is None:
            return '{0}'.format(self.message)
        else:
            return '{0}: {1}'.format(errno.errorcode[self.code], self.message)


@description("Provides list of commands in this namespace")
class IndexCommand(Command):
    """
    Usage: ?

    Lists all the possible commands and EntityNamespaces accessible form the
    current namespace or the one supplied in the arguments. It also always lists
    the globally avaible builtin set of commands.

    Example:
    ?
    volumes ?
    """
    def __init__(self, target):
        self.target = target

    def run(self, context, args, kwargs, opargs):
        nss = self.target.namespaces()
        cmds = self.target.commands()

        # Only display builtin items if in the RootNamespace
        obj = context.ml.get_relative_object(context.ml.path[-1], args)
        if obj.__class__.__name__ == 'RootNamespace':
            output_msg('Builtin items:', attrs=['bold'])
            output_list(context.ml.builtin_commands.keys())

        output_msg('Current namespace items:', attrs=['bold'])
        out = cmds.keys()
        out += [ns.get_name() for ns in sorted(nss)]
        output_list(out)


class LongIndexCommand(Command):
    def __init__(self, target):
        self.target = target

    def run(self, context, args, kwargs, opargs):
        pass


class RootNamespace(Namespace):
    pass


class PropertyMapping(object):
    def __init__(self, **kwargs):
        self.name = kwargs.pop('name')
        self.descr = kwargs.pop('descr')
        self.get = kwargs.pop('get')
        self.set = kwargs.pop('set', None) if 'set' in kwargs else self.get
        self.list = kwargs.pop('list', True)
        self.type = kwargs.pop('type', ValueType.STRING)
        self.enum = kwargs.pop('enum', None)
        self.condition = kwargs.pop('condition', None)

    def do_get(self, obj):
        if callable(self.get):
            return self.get(obj)

        return obj.get(self.get)

    def do_set(self, obj, value):
        if self.enum:
            if value not in self.enum:
                raise ValueError('Invalid value for property. Should be one of: {0}'.format(', '.join(self.enum)))

        value = read_value(value, self.type)
        if callable(self.set):
            self.set(obj, value)
            return

        obj.set(self.set, value)

    def do_append(self, obj, value):
        if self.type != ValueType.ARRAY:
            raise ValueError('Property is not an array')

        value = read_value(value, self.type)
        self.set(obj, self.get(obj).append(value))

    def do_remove(self, obj, value):
        if self.type != ValueType.ARRAY:
            raise ValueError('Property is not an array')

        value = read_value(value, self.type)


class ItemNamespace(Namespace):
    @description("Shows single item")
    class ShowEntityCommand(Command):
        """
        Usage: show
        """
        def __init__(self, parent):
            self.parent = parent

        def run(self, context, args, kwargs, opargs):
            if len(args) != 0:
                raise CommandException('Wrong arguments count')

            values = Object()
            entity = self.parent.entity

            for mapping in self.parent.property_mappings:
                if not mapping.get:
                    continue

                if mapping.condition is not None:
                    if not mapping.condition(entity):
                        continue

                values.append(Object.Item(
                    mapping.descr,
                    mapping.name,
                    mapping.do_get(entity),
                    mapping.type
                ))

            return values

    @description("Prints single item value")
    class GetEntityCommand(Command):
        """
        Usage: get <field>
        """
        def __init__(self, parent):
            self.parent = parent

        def run(self, context, args, kwargs, opargs):
            if len(args) < 1:
                output_msg('Wrong arguments count')
                return

            if not self.parent.has_property(args[0]):
                output_msg('Property {0} not found'.format(args[0]))
                return

            entity = self.parent.entity
            return self.parent.get_property(args[0], entity)

        def complete(self, context, tokens):
            return [x.name for x in self.parent.property_mappings]

    @description("Sets single item property")
    class SetEntityCommand(Command):
        """
        Usage: set <field>=<value> [...]
        """
        def __init__(self, parent):
            self.parent = parent

        def run(self, context, args, kwargs, opargs):
            if args:
                for arg in args:
                    if self.parent.has_property(arg):
                        raise CommandException('Invalid use of property {0}'.format(arg))
                    else:
                        raise CommandException('Invalid argument or use of argument {0}'.format(arg))
            for k, v in kwargs.items():
                if not self.parent.has_property(k):
                    raise CommandException('Property {0} not found'.format(k))

            entity = self.parent.entity

            for k, v in kwargs.items():
                prop = self.parent.get_mapping(k)
                if prop.set is None:
                    raise CommandException('Property {0} is not writable'.format(k))

                prop.do_set(entity, v)

            for k, op, v in opargs:
                if op not in ('+=', '-='):
                    raise CommandException(
                        "Syntax error, invalid operator used")

                prop = self.parent.get_mapping(k)

                if op == '+=':
                    prop.do_append(entity, v)

                if op == '-=':
                    prop.do_remove(entity, v)

            self.parent.modified = True

        def complete(self, context, tokens):
            return [x.name + '=' for x in self.parent.property_mappings if x.set]

    @description("Saves item")
    class SaveEntityCommand(Command):
        """
        Usage: save
        """
        def __init__(self, parent):
            self.parent = parent

        def run(self, context, args, kwargs, opargs):
            self.parent.save()

    @description("Discards modified item")
    class DiscardEntityCommand(Command):
        """
        Usage: discard
        """
        def __init__(self, parent):
            self.parent = parent

        def run(self, context, args, kwargs, opargs):
            self.parent.load()
            self.parent.modified = False

    def __init__(self, name):
        super(ItemNamespace, self).__init__(name)
        self.name = name
        self.description = name
        self.entity = None
        self.orig_entity = None
        self.allow_edit = True
        self.modified = False
        self.property_mappings = []
        self.subcommands = {}
        self.nslist = []

    def on_enter(self):
        self.load()

    def on_leave(self):
        if self.modified:
            output_msg('Object was modified. '
                       'Type either "save" or "discard" to leave')
            return False

        return True

    def get_name(self):
        return self.name

    def get_changed_keys(self):
        for i in self.entity.keys():
            if i not in self.orig_entity.keys():
                yield i
                continue

            if self.entity[i] != self.orig_entity[i]:
                yield i

    def get_diff(self):
        return {k: self.entity[k] for k in self.get_changed_keys()}

    def load(self):
        raise NotImplementedError()

    def save(self):
        raise NotImplementedError()

    def has_property(self, prop):
        return any(filter(lambda x: x.name == prop, self.property_mappings))

    def get_mapping(self, prop):
        return filter(lambda x: x.name == prop, self.property_mappings)[0]

    def add_property(self, **kwargs):
        self.property_mappings.append(PropertyMapping(**kwargs))

    def get_property(self, prop, obj):
        mapping = self.get_mapping(prop)
        return mapping.do_get(obj)

    def commands(self):
        base = {
            '?': IndexCommand(self),
            'get': self.GetEntityCommand(self),
            'show': self.ShowEntityCommand(self),
        }

        if self.allow_edit:
            base.update({
                'set': self.SetEntityCommand(self),
                'save': self.SaveEntityCommand(self),
                'discard': self.DiscardEntityCommand(self)
            })

        if self.commands is not None:
            base.update(self.subcommands)

        return base


class ConfigNamespace(ItemNamespace):
    def __init__(self, name, context):
        super(ConfigNamespace, self).__init__(name)
        self.context = context
        self.property_mappings = []

    def get_name(self):
        name = self.name

        return name if not self.modified else '[{0}]'.format(name)


class EntityNamespace(Namespace):
    class SingleItemNamespace(ItemNamespace):
        def __init__(self, name, parent):
            super(EntityNamespace.SingleItemNamespace, self).__init__(name)
            self.parent = parent
            self.saved = name is not None
            self.property_mappings = parent.property_mappings
            self.localdoc = parent.entity_localdoc

            if parent.entity_commands:
                self.subcommands = parent.entity_commands(self)

            if parent.entity_namespaces:
                self.nslist = parent.entity_namespaces(self)

            if hasattr(parent, 'allow_edit'):
                self.allow_edit = parent.allow_edit

        @property
        def primary_key(self):
            return self.parent.primary_key.do_get(self.entity)

        def get_name(self):
            name = self.primary_key if self.entity else self.name
            if not name:
                name = 'unnamed'

            return name if self.saved and not self.modified else '[{0}]'.format(name)

        def load(self):
            if self.saved:
                self.entity = self.parent.get_one(self.name)

            self.orig_entity = copy.deepcopy(self.entity)

        def save(self):
            self.parent.save(self, not self.saved)

    def __init__(self, name, context):
        super(EntityNamespace, self).__init__(name)
        self.context = context
        self.property_mappings = []
        self.primary_key = None
        self.extra_commands = None
        self.entity_commands = None
        self.entity_namespaces = None
        self.allow_edit = True
        self.allow_create = True
        self.skeleton_entity = {}
        self.create_command = self.CreateEntityCommand
        self.delete_command = self.DeleteEntityCommand
        self.localdoc = {}
        self.entity_localdoc = {}

    @description("Lists items")
    class ListCommand(FilteringCommand):
        """
        Usage: show [<field> <operator> <value> ...] [limit=<n>] [sort=<field>,-<field2>]

        Lists items in current namespace, optinally doing filtering and sorting.

        Examples:
            show
            show username=root
            show uid>1000
            show fullname~="John" sort=fullname
        """
        def __init__(self, parent):
            self.parent = parent

        def __map_filter_properties(self, expr):
            for i in expr:
                if len(i) == 2:
                    op, l = i
                    yield op, list(self.__map_filter_properties(l))

                if len(i) == 3:
                    k, op, v = i
                    if op == '==': op = '='
                    if op == '~=': op = '~'

                    prop = self.parent.get_mapping(k)
                    yield prop.get, op, v

        def run(self, context, args, kwargs, opargs, filtering=None):
            cols = []
            params = []
            options = {}

            if filtering:
                for k, v in filtering['params'].items():
                    if k == 'limit':
                        options['limit'] = int(v)
                        continue

                    if k == 'sort':
                        for sortkey in v:
                            prop = self.parent.get_mapping(sortkey)
                            options.setdefault('sort', []).append(prop.get)
                        continue

                    if not self.parent.has_property(k):
                        raise CommandException('Unknown field {0}'.format(k))

                params = list(self.__map_filter_properties(filtering['filter']))

            for col in filter(lambda x: x.list, self.parent.property_mappings):
                cols.append(Table.Column(col.descr, col.get, col.type))

            return Table(self.parent.query(params, options), cols)

    @description("Creates new item")
    class CreateEntityCommand(Command):
        """
        Usage: create [<field>=<value> ...]
        """
        def __init__(self, parent):
            self.parent = parent

        def run(self, context, args, kwargs, opargs):
            ns = EntityNamespace.SingleItemNamespace(None, self.parent)
            ns.orig_entity = wrap(copy.deepcopy(self.parent.skeleton_entity))
            ns.entity = wrap(copy.deepcopy(self.parent.skeleton_entity))

            if not args and not kwargs:
                context.ml.cd(ns)
                return

            if len(args) > 0:
                prop = self.parent.primary_key
                prop.do_set(ns.entity, args.pop(0))

            for k, v in kwargs.items():
                if not self.parent.has_property(k):
                    output_msg('Property {0} not found'.format(k))
                    return

            for k, v in kwargs.items():
                prop = self.parent.get_mapping(k)
                prop.do_set(ns.entity, v)

            self.parent.save(ns, new=True)

        def complete(self, context, tokens):
            return [x.name + '=' for x in self.parent.property_mappings]

    @description("Removes item")
    class DeleteEntityCommand(Command):
        """
        Usage: delete <primary-key>

        Examples:
            delete john
        """
        def __init__(self, parent):
            self.parent = parent

        def run(self, context, args, kwargs, opargs):
            self.parent.delete(args[0])

    def has_property(self, prop):
        return any(filter(lambda x: x.name == prop, self.property_mappings))

    def get_mapping(self, prop):
        return filter(lambda x: x.name == prop, self.property_mappings)[0]

    def get_property(self, prop, obj):
        mapping = self.get_mapping(prop)
        return mapping.do_get(obj)

    def get_one(self, name):
        raise NotImplementedError()

    def update_entity(self, name):
        raise NotImplementedError()

    def query(self, params, options):
        raise NotImplementedError()

    def add_property(self, **kwargs):
        self.property_mappings.append(PropertyMapping(**kwargs))

    def commands(self):
        base = {
            '?': IndexCommand(self),
            'show': self.ListCommand(self)
        }

        if self.extra_commands:
            base.update(self.extra_commands)

        if self.allow_create:
            base.update({
                'create': self.create_command(self),
                'delete': self.delete_command(self)
            })

        return base

    def namespaces(self):
        if self.primary_key is None:
            return

        for i in self.query([], {}):
            name = self.primary_key.do_get(i)
            yield self.SingleItemNamespace(name, self)


class RpcBasedLoadMixin(object):
    def __init__(self, *args, **kwargs):
        super(RpcBasedLoadMixin, self).__init__(*args, **kwargs)
        self.primary_key_name = 'id'
        self.extra_query_params = []

    def query(self, params, options):
        return wrap(self.context.connection.call_sync(
            self.query_call,
            self.extra_query_params + params, options))

    def get_one(self, name):
        return wrap(self.context.connection.call_sync(
            self.query_call,
            self.extra_query_params + [(self.primary_key_name, '=', name)],
            {'single': True}))


class TaskBasedSaveMixin(object):
    def __init__(self, *args, **kwargs):
        super(TaskBasedSaveMixin, self).__init__(*args, **kwargs)
        self.save_key_name = getattr(self, 'primary_key_name', 'id')

    def post_save(self, this, status):
        if status == 'FINISHED':
            this.modified = False
            this.saved = True

    def save(self, this, new=False):
        if new:
            self.context.submit_task(
                self.create_task,
                this.entity,
                callback=lambda s: self.post_save(this, s))
            return

        self.context.submit_task(
            self.update_task,
            this.orig_entity[self.save_key_name],
            this.get_diff(),
            callback=lambda s: self.post_save(this, s))

    def delete(self, name):
        entity = self.get_one(name)
        if entity:
            self.context.submit_task(self.delete_task, entity[self.save_key_name])
        else:
            output_msg("Cannot delete {0}, item does not exist".format(name))

