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


import re
import copy
import traceback
import errno
import gettext
import sys
import collections
import six
import inspect
from freenas.utils import first_or_default
from freenas.utils.query import wrap
from freenas.cli.parser import CommandCall, Literal, Symbol, BinaryParameter, Comment
from freenas.cli.complete import NullComplete, EnumComplete
from freenas.cli.utils import post_save, edit_in_editor, PrintableNone
from freenas.cli.output import (
    ValueType, Object, Table, Sequence, output_list,
    output_msg, read_value, format_value
)

t = gettext.translation('freenas-cli', fallback=True)
_ = t.gettext


def description(descr):
    def wrapped(fn):
        fn.description = descr
        return fn

    return wrapped


def create_completer(prop):
    if prop.enum:
        return EnumComplete(prop.name + '=', prop.enum)

    if prop.type == ValueType.BOOLEAN:
        return EnumComplete(prop.name + '=', ['yes', 'no'])

    return NullComplete(prop.name + '=')


class Namespace(object):
    def __init__(self, name):
        self.name = name
        self.extra_commands = None
        self.nslist = []
        self.property_mappings = []
        self.localdoc = {}
        self.required_props = None
        self.extra_required_props = None

    def help(self):
        pass

    def get_name(self):
        return self.name

    def serialize(self):
        yield Comment('Namespace: {0}'.format(self.name))
        yield CommandCall([Symbol(self.name)])

        yield [i for i in self.serialize_nested()]

        yield CommandCall([Symbol('..')])

    def serialize_nested(self):
        for i in self.namespaces():
            try:
                for j in i.serialize():
                    yield j
            except NotImplementedError:
                continue

    def commands(self):
        return {}

    def namespaces(self):
        return self.nslist

    def on_enter(self):
        pass

    def on_leave(self):
        return True

    def register_namespace(self, ns):
        self.nslist.append(ns)


class Command(object):
    def __init__(self):
        self.exec_path = None
        self.current_env = None

    def run(self, context, args, kwargs, opargs):
        raise NotImplementedError()

    def complete(self, context):
        return []


class FilteringCommand(Command):
    def run(self, context, args, kwargs, opargs, filtering=None):
        raise NotImplementedError()


class PipeCommand(Command):

    def __init__(self):
        self.must_be_last = False

    def __new__(cls):
        runfunc = getattr(cls, 'run')

        def run_wrapper(self, func):
            def wrapped(self, *args, **kwargs):
                if kwargs.get('input') is None:
                    return None
                return func(self, *args, **kwargs)
            return wrapped
        setattr(cls, 'run', run_wrapper(cls, runfunc))
        return Command.__new__(cls)

    def run(self, context, args, kwargs, opargs, input=None):
        pass

    def serialize_filter(self, context, args, kwargs, opargs):
        pass


class CommandException(Exception):
    def __init__(self, message, code=None, extra=None):
        self.code = code
        self.message = message
        self.extra = extra
        if sys.exc_info()[0]:
            self.stacktrace = traceback.format_exc()
        else:
            self.stacktrace = ''

    def __str__(self):
        if self.code is None:
            return '{0}'.format(self.message)
        else:
            return '{0}: {1}'.format(errno.errorcode[self.code], self.message)


class LongIndexCommand(Command):
    def __init__(self, target):
        self.target = target

    def run(self, context, args, kwargs, opargs):
        pass


class RootNamespace(Namespace):
    pass


class PropertyMapping(object):
    def __init__(self, **kwargs):
        self.index = kwargs.pop('index')
        self.name = kwargs.pop('name')
        self.descr = kwargs.pop('descr', None)
        self.get = kwargs.pop('get')
        self.get_name = kwargs.pop('get_name', self.get)
        self.set = kwargs.pop('set', None) if 'set' in kwargs else self.get
        self.list = kwargs.pop('list', True)
        self.type = kwargs.pop('type', ValueType.STRING)
        self.usage = kwargs.pop('usage', None)
        self.enum = kwargs.pop('enum', None)
        self.usersetable = kwargs.pop('usersetable', True)
        self.createsetable = kwargs.pop('createsetable', True)
        self.regex = kwargs.pop('regex', None)
        self.condition = kwargs.pop('condition', None)
        self.ns = kwargs.pop('ns', None)

    def is_usersetable(self, obj):
        if callable(self.usersetable):
            return self.usersetable(obj)
        else:
            return self.usersetable

    def do_get(self, obj):
        if self.condition and not self.condition(obj):
            return None

        if isinstance(self.get, collections.Callable):
            return self.get(obj)

        return obj.get(self.get)

    def do_set(self, obj, value):
        if self.condition and not self.condition(obj):
            raise ValueError(_("Property '{0}' is not settable for this entity".format(self.name)))

        if self.enum:
            if str(value) not in self.enum:
                raise ValueError(
                    "Invalid value for property '{0}'. Should be one of: {1}".format(
                        self.get_name, ', '.join(self.enum))
                )

        value = read_value(value, self.type)
        if isinstance(self.set, collections.Callable):
            self.set(obj, value)
            return

        obj.set(self.set, value)

    def do_append(self, obj, value):
        if self.type != ValueType.SET:
            raise ValueError('Property is not a set')

        value = read_value(value, self.type)
        oldvalues = obj.get(self.set)
        if oldvalues is not None:
            newvalues = oldvalues + value
        else:
            newvalues = value

        if isinstance(self.set, collections.Callable):
            self.set(obj, newvalues)
            return

        obj.set(self.set, newvalues)

    def do_remove(self, obj, value):
        if self.type != ValueType.SET:
            raise ValueError('Property is not a set')

        value = read_value(value, self.type)
        oldvalues = obj.get(self.set)
        newvalues = oldvalues
        for v in value:
            if v in newvalues:
                newvalues.remove(v)
            else:
                raise CommandException(_('{0} is not a value in {1}'.format(v, self.set)))

        if isinstance(self.set, collections.Callable):
            self.set(obj, newvalues)
            return

        obj.set(self.set, newvalues)


class ItemNamespace(Namespace):
    @description("Shows <entity> properties")
    class ShowEntityCommand(FilteringCommand):
        """
        Usage: show
        
        Display the property values for current entity.
        """
        def __init__(self, parent):
            self.parent = parent

        def run(self, context, args, kwargs, opargs, filtering=None):
            if len(args) != 0:
                raise CommandException('Wrong arguments count')

            self.parent.load()

            values = Object()
            entity = self.parent.entity

            for mapping in self.parent.property_mappings:
                if not mapping.get:
                    continue

                if mapping.ns:
                    continue

                if mapping.condition is not None:
                    if not mapping.condition(entity):
                        continue

                if mapping.set and mapping.is_usersetable(entity) and self.parent.allow_edit:
                    editable = True
                else:
                    editable = False

                value = Object.Item(
                    mapping.descr,
                    mapping.name,
                    mapping.do_get(entity),
                    mapping.type,
                    editable,
                )
                values.append(value)

            if self.parent.leaf_entity:
                leaf_res = ListCommand(self.parent).run(context, args, kwargs, opargs, filtering)
                return Sequence(
                    values,
                    "-- {0} --".format(self.parent.leaf_ns.description),
                    leaf_res
                )
            return values

    @description("Prints single item value")
    class GetEntityCommand(Command):
        """
        Usage: get <field>
        
        Display value of specified field.
        """
        def __init__(self, parent):
            self.parent = parent

        def run(self, context, args, kwargs, opargs):
            if len(args) != 1:
                raise CommandException(_('Wrong arguments count'))

            if not self.parent.has_property(args[0]):
                raise CommandException(_('Property {0} not found'.format(args[0])))

            self.parent.load()

            entity = self.parent.entity
            value = self.parent.get_property(args[0], entity)
            if value is None:
                return PrintableNone()

            return value

        def complete(self, context):
            return [EnumComplete(0, [p.name for p in self.parent.property_mappings])]

    @description("Sets single <entity> property")
    class SetEntityCommand(Command):
        """
        Usage: set <property>=<value> ...

        Set the specified property to the specified value. For a list of properties for the
        current namespace, see 'help properties'.
        """
        def __init__(self, parent):
            self.parent = parent

        def run(self, context, args, kwargs, opargs):
            if not (args or kwargs or opargs):
                raise CommandException(_("You have provided no arguments."))
            if args:
                for arg in args:
                    if self.parent.has_property(arg):
                        raise CommandException('Invalid use of property {0}'.format(arg))
                    else:
                        raise CommandException(
                            'Invalid argument or use of argument {0}'.format(arg)
                        )
            for k, v in list(kwargs.items()):
                if not self.parent.has_property(k):
                    raise CommandException('Property {0} not found'.format(k))

            entity = self.parent.entity

            for k, v in list(kwargs.items()):
                prop = self.parent.get_mapping(k)
                if prop.set is None or not prop.is_usersetable(entity):
                    raise CommandException('Property {0} is not writable'.format(k))
                if prop.regex is not None and not re.match(prop.regex, str(v)):
                    raise CommandException('Invalid input {0} for property {1}.'.format(v, k))
                prop.do_set(entity, v)

            for k, op, v in opargs:
                if op not in ('=+', '=-'):
                    raise CommandException(
                        "Syntax error, invalid operator used")

                prop = self.parent.get_mapping(k)

                if op == '=+':
                    prop.do_append(entity, v)

                if op == '=-':
                    prop.do_remove(entity, v)

            self.parent.modified = True
            self.parent.save()

        def complete(self, context):
            return [create_completer(x) for x in self.parent.property_mappings if x.set]

    @description("Opens an editor for a single <entity> string property")
    class EditEntityCommand(Command):
        """
        Usage: edit <property>

        Opens the default editor for the specified property. The default editor
        is inherited from the shell's $EDITOR which can be set from the shell.
        For a list of properties for the current namespace, see 'help properties'.
        """

        def __init__(self, parent):
            self.parent = parent

        def run(self, context, args, kwargs, opargs):
            if len(args) > 1:
                raise CommandException(_("Invalid syntax:{0}\n{1}.".format(args, inspect.getdoc(self))))
            if len(args) < 1:
                raise CommandException(_("Please provide a property to be edited.\n{0}".format(inspect.getdoc(self))))
            prop = self.parent.get_mapping(args[0])
            if prop.type != ValueType.STRING:
                raise CommandException(_("The edit command can only be used on string properties"))
            value = edit_in_editor(prop.do_get(self.parent.entity))
            prop.do_set(self.parent.entity, value)
            self.parent.modified = True
            self.parent.save()

        def complete(self, context):
            return [EnumComplete(0, [p.name for p in self.parent.property_mappings])]

    @description("Deletes single entity")
    class DeleteEntityCommand(Command):
        """
        Usage: delete

        Examples: / account user myuser delete
                  / network interface lagg0 10.5.100.1 delete
                  / volume mypool delete

        Delete current entity.
        """
        def __init__(self, parent):
            self.parent = parent

        def run(self, context, args, kwargs, opargs):
            if len(args) > 0:
                raise CommandException(_("Invalid syntax:{0}\n{1}.".format(args, inspect.getdoc(self))))
            entity_id = self.parent.primary_key
            self.parent.parent.delete(self.parent, kwargs)
            curr_ns = context.ml.path[-1]
            if curr_ns.get_name() == entity_id and isinstance(curr_ns.parent, self.parent.parent.__class__):
                context.ml.cd_up()

    def __init__(self, name):
        super(ItemNamespace, self).__init__(name)
        self.name = name
        if not hasattr(self, 'description'):
            self.description = name
        self.entity = None
        self.leaf_entity = False
        self.orig_entity = None
        self.allow_edit = True
        self.modified = False
        self.subcommands = {}
        self.nslist = []

    def on_enter(self):
        self.load()

    def literalize_value(self, value):
        if isinstance(value, list):
            value = [Literal(v, type(v)) for v in value]
        if isinstance(value, dict):
            value = {Literal(k, type(k)): Literal(v, type(v)) for k, v in value.items()}
        return Literal(value, type(value))

    def get_name(self):
        return self.name

    def get_changed_keys(self):
        for i in list(self.entity.keys()):
            if i not in list(self.orig_entity.keys()):
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
        return any([x for x in self.property_mappings if x.name == prop])

    def get_mapping(self, prop):
        return list([x for x in self.property_mappings if x.name == prop])[0]

    def get_mapping_by_field(self, field):
        rest = None

        while True:
            ret = first_or_default(lambda p: p.get == field, self.property_mappings)
            if ret:
                if ret.ns:
                    return ret.ns(self).get_mapping_by_field(rest)
                return ret

            if '.' not in field:
                break

            field, rest = field.rsplit('.', 1)

    def add_property(self, **kwargs):
        self.property_mappings.append(PropertyMapping(index=len(self.property_mappings), **kwargs))

    def get_property(self, prop, obj):
        mapping = self.get_mapping(prop)
        return mapping.do_get(obj)

    def has_editable_string(self):
        for prop in self.property_mappings:
            if prop.set is not None and prop.is_usersetable(self.entity) and prop.type == ValueType.STRING:
                if prop.condition and not prop.condition(self.entity):
                    continue
                else:
                    return True
        return False

    def has_editable_property(self):
        for prop in self.property_mappings:
            if prop.set is not None and prop.is_usersetable(self.entity):
                if prop.condition and not prop.condition(self.entity):
                    continue
                else:
                    return True
        return False

    def commands(self):
        base = {
            'get': self.GetEntityCommand(self),
            'show': self.ShowEntityCommand(self),
        }

        if self.allow_edit:
            if self.has_editable_property():
                base['set'] = self.SetEntityCommand(self)
            if self.has_editable_string():
                base['edit'] = self.EditEntityCommand(self)

        if self.commands is not None:
            base.update(self.subcommands)

        return base

    def namespaces(self):
        for i in self.nslist:
            yield i

        for i in self.property_mappings:
            if i.ns:
                yield i.ns(self)

    def update_commands(self):
        pass


class ConfigNamespace(ItemNamespace):
    def __init__(self, name, context):
        super(ConfigNamespace, self).__init__(name)
        self.context = context
        self.saved = name is not None
        self.config_call = None
        self.update_task = None
        self.config_extra_params = None

    def get_name(self):
        return self.name

    def serialize(self):
        self.on_enter()

        def do_prop(prop):
            value = prop.do_get(self.entity)
            return CommandCall([
                Symbol('set'),
                BinaryParameter(
                    prop.name, '=',
                    self.literalize_value(value)
                )
            ])

        yield Comment('Namespace: {0}'.format(self.name))
        yield CommandCall([Symbol(self.name)])
        for j in self.property_mappings:
            if not j.get:
                continue
            if not j.set:
                continue
            yield do_prop(j)
        yield [i for i in self.serialize_nested()]

        yield CommandCall([Symbol('..')])

    def commands(self):
        base = super(ConfigNamespace, self).commands()

        if self.extra_commands:
            base.update(self.extra_commands)

        return base

    def load(self):
        if self.saved:
            if self.config_extra_params:
                config_extra = self.config_extra_params() if isinstance(self.config_extra_params, collections.Callable) else self.config_extra_params
                self.entity = self.context.call_sync(self.config_call, config_extra)
            else:
                self.entity = self.context.call_sync(self.config_call)
            self.orig_entity = copy.deepcopy(self.entity)
        else:
            # This is in case the task failed!
            self.entity = copy.deepcopy(self.orig_entity)
        self.modified = False

    def save(self):
        self.context.submit_task(
            self.update_task,
            self.get_diff(),
            callback=lambda s, t: post_save(self, s, t)
        )


class SingleItemNamespace(ItemNamespace):
    def __init__(self, name, parent, **kwargs):
        super(SingleItemNamespace, self).__init__(name)
        self.parent = parent
        self.saved = name is not None
        self.property_mappings = parent.property_mappings
        self.localdoc = parent.entity_localdoc
        self.leaf_harborer = False
        self.leaf_entity = kwargs.get('leaf_entity', False)
        self.leaf_entity_namespace = self.parent.leaf_entity_namespace
        self.leaf_ns = None
        self.password = None

        if parent.entity_commands:
            self.subcommands = parent.entity_commands(self)

        if parent.entity_namespaces:
            self.nslist = parent.entity_namespaces(self)

        if parent.leaf_entity_namespace:
            self.leaf_ns = parent.leaf_entity_namespace(self)
            if self.nslist:
                self.nslist.append(self.leaf_ns)
            else:
                self.nslist = [self.leaf_ns]

        if hasattr(parent, 'allow_edit'):
            self.allow_edit = parent.allow_edit

    def entity_doc(self):
        return (
            "{0} '{1}', expands into commands for managing this entity.".format
            (self.parent.get_name().title(), self.get_name()))

    def update_commands(self):
        if self.parent.entity_commands:
            self.subcommands = self.parent.entity_commands(self)

    @property
    def primary_key(self):
        return self.parent.primary_key.do_get(self.entity)

    def get_name(self):
        name = self.primary_key if self.entity else self.name
        if not name and name != 0:
            name = 'unnamed'

        return name

    def serialize(self):
        self.on_enter()

        if self.parent.entity_serialize:
            return self.parent.entity_serialize(self)

        createable = self.parent.allow_create
        if hasattr(self.parent, 'createable'):
            createable = self.parent.createable(self.entity)

        if createable:
            ret = CommandCall([Symbol('create')])
        else:
            ret = CommandCall([
                Symbol(self.primary_key),
                Symbol('set')
            ])

        return_args = []
        postcreation_mappings = []
        for mapping in self.property_mappings:
            if not mapping.get:
                continue

            if not mapping.set:
                continue

            if not createable and not mapping.is_usersetable(self.entity):
                continue

            if mapping.condition is not None:
                if not mapping.condition(self.entity):
                    continue

            if createable and not mapping.createsetable and mapping.is_usersetable(self.entity):
                postcreation_mappings.append(mapping)
                continue

            value = mapping.do_get(self.entity)

            if mapping.type == ValueType.SET and value is not None:
                value = list(value)

            return_args.append(BinaryParameter(mapping.name, '=', self.literalize_value(value)))

        if len(return_args) > 0:
            ret.args += return_args
            yield ret

        if len(postcreation_mappings) > 0:
            ret = CommandCall([
                Symbol(self.primary_key),
                Symbol('set')
            ])

            for mapping in postcreation_mappings:
                value = mapping.do_get(self.entity)

                if mapping.type == ValueType.SET and value is not None:
                    value = list(value)

                ret.args.append(BinaryParameter(mapping.name, '=', self.literalize_value(value)))

            yield ret

    def load(self):
        if self.saved:
            self.entity = self.parent.get_one(self.get_name())
            self.orig_entity = copy.deepcopy(self.entity)
        else:
            # This is in case the task failed!
            self.entity = copy.deepcopy(self.orig_entity)
        self.modified = False

    def save(self):
        self.parent.save(self, not self.saved)

    def commands(self):
        command_set = super(SingleItemNamespace, self).commands()
        if self.parent.leaf_harborer:
            if self.leaf_ns.allow_create:
                command_set.update({
                    'create': CreateEntityCommand(self),
                })

        if self.parent.allow_create:
            command_set['delete'] = self.DeleteEntityCommand(self)

        return command_set

    def namespaces(self):
        if not self.leaf_entity:
            return super(SingleItemNamespace, self).namespaces()
        if self.leaf_ns.primary_key is None:
            return

        # for some reason yield does not work below
        nslst = []
        for i in self.leaf_ns.query([], {}):
            name = self.leaf_ns.primary_key.do_get(i)
            nslst.append(SingleItemNamespace(name, self.leaf_ns, leaf_entity=self.leaf_harborer))
        return nslst


@description("Lists <entity>s")
class BaseListCommand(FilteringCommand):
    """
    Usage: show

    Examples:
        show
        show | search username == root
        show | search uid > 1000
        show | search fullname~="John" | sort fullname

    Lists items in current namespace, optinally doing filtering and sorting.
    """
    def __init__(self, parent):
        if hasattr(parent, 'leaf_entity') and parent.leaf_entity:
            self.parent = parent.leaf_ns
        else:
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
                # yield k if isinstance(prop.get, collections.Callable) else prop.get, op, v
                # hack to make `accout user show | search group==wheel` work
                # else one would have to `account user show | search group==0`
                if isinstance(prop.set, collections.Callable):
                    dummy_entity = {}
                    prop.set(dummy_entity, v)
                    v = dummy_entity[prop.get_name]
                yield prop.get_name, op, v

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
                        neg = ''
                        if sortkey.startswith('-'):
                            sortkey = sortkey[1:]
                            neg = '-'

                        prop = self.parent.get_mapping(sortkey)
                        if not prop:
                            raise CommandException('Unknown field {0}'.format(sortkey))

                        if not isinstance(prop.get, six.string_types):
                            raise CommandException('Cannot sort on field {0}'.format(sortkey))

                        options.setdefault('sort', []).append(neg + prop.get)
                    continue

                raise CommandException('Unknown field {0}'.format(k))

            params = list(self.__map_filter_properties(filtering['filter']))

        for col in self.parent.property_mappings:
            if not col.list:
                continue

            cols.append(Table.Column(col.descr, col.do_get, col.type))

        return Table(self.parent.query(params, options), cols)


@description("Lists <entity>s")
class ListCommand(BaseListCommand):
    def run(self, context, args, kwargs, opargs, filtering=None):
        if args or kwargs or opargs:
            raise CommandException(_('"show" command doesn\'t take any arguments'))

        return super(ListCommand, self).run(context, args, kwargs, opargs, filtering)


@description("Creates new <entity>")
class CreateEntityCommand(Command):
    """
    Usage: create <name> <property>=<value> ...

    For a list of properties for the current namespace, see 'help properties'.
    """
    def __init__(self, parent):
        if hasattr(parent, 'leaf_entity') and parent.leaf_entity:
            self.parent = parent.leaf_ns
        else:
            self.parent = parent

    def run(self, context, args, kwargs, opargs):
        ns = SingleItemNamespace(None, self.parent)
        ns.orig_entity = wrap(copy.deepcopy(self.parent.skeleton_entity))
        ns.entity = wrap(copy.deepcopy(self.parent.skeleton_entity))
        kwargs = collections.OrderedDict(kwargs)

        if len(args) > 0:
            # Do not allow user to specify name as both implicit and explicit parameter as this suggests a mistake
            if 'name' in kwargs:
                raise CommandException(_("Both implicit and explicit 'name' parameters are specified."))
            else:
                prop = self.parent.primary_key
                kwargs[prop.name] = args.pop(0)
                kwargs.move_to_end(prop.name, False)

        for k, v in list(kwargs.items()):
            if not self.parent.has_property(k):
                output_msg('Property {0} not found'.format(k))
                return
            mapping = self.parent.get_mapping(k)
            if mapping.set is None or not mapping.createsetable:
                output_msg('Property {0} is not writable'.format(k))
                return
            if mapping.regex is not None and not re.match(mapping.regex, str(v)):
                output_msg('Invalid input {0} for property {1}.'.format(v, k))
                return

        if self.parent.required_props:
            missing_args = []
            for prop in self.parent.required_props:
                if isinstance(prop, list):
                    has_arg = False
                    for p in prop:
                        if p in kwargs.keys():
                            has_arg = True
                    if not has_arg:
                        missing_args.append("{0}".format(' or '.join(prop)))
                else:
                    if prop not in kwargs.keys():
                        missing_args.append(prop)
            if self.parent.extra_required_props:
                for prop_set in self.parent.extra_required_props:
                    found_one = False
                    missing = False
                    for prop in prop_set:
                        if prop in kwargs.keys():
                            found_one = True
                        else:
                            if found_one:
                                missing = True
                    if found_one and missing:
                        missing_args.append(' and '.join(prop_set))
            if hasattr(self.parent, 'conditional_required_props'):
                for prop in self.parent.conditional_required_props(kwargs):
                    if prop not in kwargs.keys():
                        missing_args.append(prop)
            if len(missing_args) > 0:
                output_msg(_('Required properties not provided: {0}'.format(', '.join(missing_args))))
                return
        else:
            if not args and not kwargs:
                return

        mappings = map(lambda i: (self.parent.get_mapping(i[0]), i[1]), kwargs.items())
        for prop, v in sorted(mappings, key=lambda i: i[0].index):
            prop.do_set(ns.entity, v)

        self.parent.save(ns, new=True)

    def complete(self, context):
        return [create_completer(x) for x in self.parent.property_mappings if x.set]


class EntityNamespace(Namespace):
    def __init__(self, name, context):
        super(EntityNamespace, self).__init__(name)
        self.context = context
        self.primary_key = None
        self.entity_commands = None
        self.entity_namespaces = None
        self.entity_serialize = None
        self.allow_edit = True
        self.allow_create = True
        self.skeleton_entity = {}
        self.entity_localdoc = {}
        self.leaf_harborer = False
        self.leaf_entity_namespace = None

    def has_property(self, prop):
        return any([x for x in self.property_mappings if x.name == prop])

    def get_mapping(self, prop):
        return first_or_default(lambda x: x.name == prop, self.property_mappings)

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
        self.property_mappings.append(PropertyMapping(index=len(self.property_mappings), **kwargs))

    def commands(self):
        base = {
            'show': ListCommand(self)
        }

        if self.extra_commands:
            base.update(self.extra_commands)

        if self.allow_create:
            base.update({
                'create': CreateEntityCommand(self)
            })

        return base

    def namespaces(self):
        if self.primary_key is None:
            return

        for i in self.query([], {}):
            name = self.primary_key.do_get(i)
            yield SingleItemNamespace(name, self, leaf_entity=self.leaf_harborer)


class RpcBasedLoadMixin(object):
    def __init__(self, *args, **kwargs):
        super(RpcBasedLoadMixin, self).__init__(*args, **kwargs)
        self.primary_key_name = 'id'
        self.extra_query_params = []

    def query(self, params, options):
        return self.context.call_sync(self.query_call, self.extra_query_params + params, options)

    def get_one(self, name):
        return self.context.call_sync(
            self.query_call,
            self.extra_query_params + [(self.primary_key_name, '=', name)],
            {'single': True})


class EntitySubscriberBasedLoadMixin(object):
    def __init__(self, *args, **kwargs):
        super(EntitySubscriberBasedLoadMixin, self).__init__(*args, **kwargs)
        self.primary_key_name = 'id'
        self.entity_subscriber_name = None
        self.extra_query_params = []

    def on_enter(self, *args, **kwargs):
        super(EntitySubscriberBasedLoadMixin, self).on_enter(*args, **kwargs)
        self.context.entity_subscribers[self.entity_subscriber_name].on_delete.add(self.on_delete)
        self.context.entity_subscribers[self.entity_subscriber_name].on_update.add(self.on_update)

    def on_delete(self, entity):
        cwd = self.context.ml.cwd
        if isinstance(cwd, SingleItemNamespace) and cwd.parent == self and cwd.name == entity[self.primary_key_name]:
            self.context.ml.cd_up()

    def on_update(self, old_entity, new_entity):
        cwd = self.context.ml.cwd
        if isinstance(cwd, SingleItemNamespace) and cwd.parent == self:
            if old_entity[self.primary_key_name] == cwd.entity[self.primary_key_name]:
                cwd.entity[self.primary_key_name] = new_entity[self.primary_key_name]
                cwd.load()

            if not cwd.entity:
                self.context.ml.cd_up()

    def query(self, params, options):
        if not params and not options:
            return self.context.entity_subscribers[self.entity_subscriber_name].viewport(
                *self.extra_query_params
            )

        return self.context.entity_subscribers[self.entity_subscriber_name].query(
            *(self.extra_query_params + params),
            **options
        )

    def get_one(self, name):
        return self.context.entity_subscribers[self.entity_subscriber_name].query(
            (self.primary_key_name, '=', name), *self.extra_query_params,
            single=True
        )


class TaskBasedSaveMixin(object):
    def __init__(self, *args, **kwargs):
        super(TaskBasedSaveMixin, self).__init__(*args, **kwargs)
        self.save_key_name = getattr(self, 'primary_key_name', 'id')

    def save(self, this, new=False, callback=None):
        if callback is None:
            callback = lambda s, t: post_save(this, s, t)

        if new:
            self.context.submit_task(
                self.create_task,
                this.entity,
                callback=callback)
            return

        self.context.submit_task(
            self.update_task,
            this.orig_entity[self.save_key_name],
            this.get_diff(),
            callback=callback)

    def delete(self, this, kwargs):
        self.context.submit_task(self.delete_task, this.entity[self.save_key_name])


class NestedObjectLoadMixin(object):
    def __init__(self, *args, **kwargs):
        super(NestedObjectLoadMixin, self).__init__(*args, **kwargs)
        self.primary_key_name = 'id'
        self.extra_query_params = []

    def query(self, params, options):
        return self.parent.entity.get(self.parent_path, []).query(*(self.extra_query_params + params), **options)

    def get_one(self, name):
        return first_or_default(
            lambda a: a[self.primary_key_name] == name,
            self.parent.entity.get(self.parent_path, [])
        )


class NestedObjectSaveMixin(object):
    def save(self, this, new=False):
        if new:
            if self.parent.entity[self.parent_path] is None:
                 self.parent.entity[self.parent_path] = []

            self.parent.entity[self.parent_path].append(this.entity)
        else:
            entity = first_or_default(
                lambda a: a[self.primary_key_name] == this.entity['name'],
                self.parent.entity[self.parent_path]
            )
            entity.update(this.entity)

        self.parent.save()

    def delete(self, this, kwargs):
        self.parent.entity[self.parent_path] = list(filter(
            lambda i: i[self.primary_key_name] != this.entity[self.primary_key_name],
            self.parent.entity[self.parent_path]
        ))

        self.parent.save()


class NestedEntityMixin(object):
    @property
    def entity(self):
        return self.parent.entity[self.parent_entity_path]

    @entity.setter
    def entity(self, value):
        pass

    def load(self):
        pass

    def save(self):
        return self.parent.save()
