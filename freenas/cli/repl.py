#!/usr/bin/env python
#
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
import enum
import sys
import os
import glob
import argparse
import shlex
import imp
import logging
import errno
import platform
import json
import time
import gettext
import getpass
import traceback
import six
import paramiko
from six.moves.urllib.parse import urlparse
from socket import gaierror as socket_error
from freenas.cli.descriptions import events
from freenas.cli import functions
from freenas.cli import config
from freenas.cli.namespace import (
    Namespace, RootNamespace, Command, FilteringCommand, PipeCommand, CommandException
)
from freenas.cli.parser import (
    parse, Symbol, Literal, BinaryParameter, UnaryExpr, BinaryExpr, PipeExpr, AssignmentStatement,
    IfStatement, ForStatement, WhileStatement, FunctionCall, CommandCall, Subscript,
    ExpressionExpansion, FunctionDefinition, ReturnStatement, BreakStatement, UndefStatement
)
from freenas.cli.output import (
    ValueType, ProgressBar, output_lock, output_msg, read_value, format_value,
    format_output
)
from freenas.dispatcher.client import Client, ClientError
from freenas.dispatcher.entity import EntitySubscriber
from freenas.dispatcher.rpc import RpcException
from freenas.utils.query import wrap
from freenas.cli.commands import (
    ExitCommand, PrintenvCommand, SetenvCommand, ShellCommand, HelpCommand,
    ShowUrlsCommand, ShowIpsCommand, TopCommand, ClearCommand, HistoryCommand,
    SaveenvCommand, EchoCommand, SourceCommand, LessPipeCommand, SearchPipeCommand,
    ExcludePipeCommand, SortPipeCommand, LimitPipeCommand, SelectPipeCommand,
    LoginCommand, DumpCommand
)
import collections

try:
    from shutil import get_terminal_size
except ImportError:
    from backports.shutil_get_terminal_size import get_terminal_size

if platform.system() == 'Darwin':
    import gnureadline as readline
else:
    import readline

DEFAULT_MIDDLEWARE_CONFIGFILE = None
CLI_LOG_DIR = os.getcwd()
if os.environ.get('FREENAS_SYSTEM') == 'YES':
    DEFAULT_MIDDLEWARE_CONFIGFILE = '/usr/local/etc/middleware.conf'
    CLI_LOG_DIR = '/var/tmp'

DEFAULT_CLI_CONFIGFILE = os.path.join(os.getcwd(), '.freenascli.conf')

t = gettext.translation('freenas-cli', fallback=True)
_ = t.gettext


PROGRESS_CHARS = ['-', '\\', '|', '/']
EVENT_MASKS = [
    'client.logged',
    'task.created',
    'task.updated',
    'task.progress',
    'service.stopped',
    'service.started'
]
ENTITY_SUBSCRIBERS = [
    'user',
    'group',
    'disk',
    'volume',
    'volume.snapshot',
    'share',
    'task',
    'alert'
]


def sort_args(args):
    positional = []
    kwargs = {}
    opargs = []

    for i in args:
        if type(i) is tuple:
            if i[1] == '=':
                kwargs[i[0]] = i[2]
            else:
                opargs.append(i)
            continue

        positional.append(i)

    return positional, kwargs, opargs


def convert_to_literals(tokens):
    def conv(t):
        if isinstance(t, list):
            return [conv(i) for i in t]

        if isinstance(t, Symbol):
            return Literal(t.name, str)

        if isinstance(t, BinaryParameter):
            t.right = conv(t.right)

        return t

    return [conv(i) for i in tokens]


class FlowControlInstructionType(enum.Enum):
    RETURN = 'RETURN'
    BREAK = 'BREAK'


class VariableStore(object):
    class Variable(object):
        def __init__(self, default, type, choices=None):
            self.default = default
            self.type = type
            self.choices = choices
            self.value = default

        def set(self, value):
            value = read_value(value, self.type)
            if self.choices is not None and value not in self.choices:
                raise ValueError(
                    _("Value not on the list of possible choices"))

            self.value = value

        def __str__(self):
            return format_value(self.value, self.type)

    def __init__(self):
        self.save_to_file = DEFAULT_CLI_CONFIGFILE
        self.variables = {
            'output_format': self.Variable('ascii', ValueType.STRING,
                                           ['ascii', 'json', 'table']),
            'datetime_format': self.Variable('natural', ValueType.STRING),
            'language': self.Variable(os.getenv('LANG', 'C'),
                                      ValueType.STRING),
            'prompt': self.Variable('{host}:{path}>', ValueType.STRING),
            'timeout': self.Variable(10, ValueType.NUMBER),
            'tasks_blocking': self.Variable(False, ValueType.BOOLEAN),
            'show_events': self.Variable(True, ValueType.BOOLEAN),
            'debug': self.Variable(False, ValueType.BOOLEAN)
        }

    def load(self, filename):
        try:
            with open(filename, 'r') as f:
                data = json.load(f)
        except IOError:
            # The file does not exist lets just default to default env settings
            # TODO: Should I report this to the user somehow?
            return
        except ValueError:
            # If the data being deserialized is not a valid JSON document,
            # a ValueError will be raised.
            output_msg(
                _("WARNING: The CLI config file: {0} has ".format(filename) +
                  "improper format. Please check the file for errors. " +
                  "Resorting to Default set of Environment Variables."))
            return
        # Now that we know that this file is legit and that it may be different
        # than the default (DEFAULT_CLI_CONFIGFILE) lets just set this class's
        # 'save_to_file' variable to this file.
        self.save_to_file = filename
        for name, setting in data.items():
            self.set(name, setting['value'],
                     ValueType(setting['type']), setting['default'],
                     setting['choices'])

    def save(self, filename=None):
        env_settings = {}
        for key, variable in self.variables.items():
            env_settings[key] = {
                'default': variable.default,
                'type': variable.type.value,
                'choices': variable.choices,
                'value': variable.value
            }
        try:
            with open(filename or self.save_to_file, 'w') as f:
                json.dump(env_settings, f)
        except IOError:
            raise
        except ValueError as err:
            raise ValueError(
                _("Could not save environemnet to file. Following error " +
                  "occured: {0}".format(str(err))))

    def get(self, name):
        return self.variables[name].value

    def get_all(self):
        return list(self.variables.items())

    def get_all_printable(self):
        for name, var in list(self.variables.items()):
            yield (name, str(var))

    def set(self, name, value, vtype=ValueType.STRING,
            default='', choices=None):
        if name not in self.variables:
            self.variables[name] = self.Variable(default, vtype, choices)

        self.variables[name].set(value)


class Context(object):
    def __init__(self):
        self.uri = None
        self.parsed_uri = None
        self.hostname = None
        self.connection = Client()
        self.ml = None
        self.logger = logging.getLogger('cli')
        self.plugin_dirs = []
        self.task_callbacks = {}
        self.plugins = {}
        self.variables = VariableStore()
        self.root_ns = RootNamespace('')
        self.event_masks = ['*']
        self.event_divert = False
        self.event_queue = six.moves.queue.Queue()
        self.keepalive_timer = None
        self.argparse_parser = None
        self.entity_subscribers = {}
        self.call_stack = [CallStackEntry('<stdin>', [], '<stdin>', 1, 1)]
        self.builtin_operators = functions.operators
        self.builtin_functions = functions.functions
        self.global_env = Environment(self)
        config.instance = self

    @property
    def is_interactive(self):
        return os.isatty(sys.stdout.fileno())

    def start(self, password=None):
        self.discover_plugins()
        self.connect(password)

    def start_entity_subscribers(self):
        for i in ENTITY_SUBSCRIBERS:
            e = EntitySubscriber(self.connection, i)
            e.start()
            self.entity_subscribers[i] = e

    def connect(self, password=None):
        try:
            self.connection.connect(self.uri, password=password)
        except socket_error as err:
            output_msg(_(
                "Could not connect to host: {0} due to error: {1}".format(
                    self.parsed_uri.hostname, err)
            ))
            self.argparse_parser.print_help()
            sys.exit(1)
        except paramiko.ssh_exception.AuthenticationException as err:
            output_msg(_(
                "Incorrect username or password"))
            sys.exit(1)
        except ConnectionRefusedError as err:
            output_msg(_(
                "Connection refused by host: {0}".format(
                    self.parsed_uri.hostname)))
            sys.exit(1)

    def login(self, user, password):
        try:
            self.connection.login_user(user, password)
            self.connection.subscribe_events(*EVENT_MASKS)
            self.connection.on_event(self.handle_event)
            self.connection.on_error(self.connection_error)
        except RpcException as e:
            if e.code == errno.EACCES:
                self.connection.disconnect()
                output_msg(_("Wrong username or password"))
                sys.exit(1)

        self.start_entity_subscribers()
        self.login_plugins()

    def keepalive(self):
        if self.connection.opened:
            self.connection.call_sync('management.ping')

    def read_middleware_config_file(self, file):
        """
        If there is a cli['plugin-dirs'] in middleware.conf use that,
        otherwise use the default plugins dir within cli namespace
        """
        plug_dirs = None
        if file:
            with open(file, 'r') as f:
                data = json.load(f)

            if 'cli' in data and 'plugin-dirs' in data['cli']:

                if type(data['cli']['plugin-dirs']) != list:
                    return

                self.plugin_dirs += data['cli']['plugin-dirs']

        if plug_dirs is None:
            # Support for pyinstaller
            if hasattr(sys, '_MEIPASS'):
                plug_dirs = os.path.join(sys._MEIPASS, 'freenas/cli/plugins')
            else:
                plug_dirs = os.path.join(
                    os.path.dirname(os.path.realpath(__file__)), 'plugins'
                )
            self.plugin_dirs += [plug_dirs]

    def discover_plugins(self):
        for dir in self.plugin_dirs:
            self.logger.debug(_("Searching for plugins in %s"), dir)
            self.__discover_plugin_dir(dir)

    def login_plugins(self):
        for i in list(self.plugins.values()):
            if hasattr(i, '_login'):
                i._login(self)

    def __discover_plugin_dir(self, dir):
        for i in glob.glob1(dir, "*.py"):
            self.__try_load_plugin(os.path.join(dir, i))

    def __try_load_plugin(self, path):
        if path in self.plugins:
            return

        self.logger.debug(_("Loading plugin from %s"), path)
        name, ext = os.path.splitext(os.path.basename(path))
        plugin = imp.load_source(name, path)

        if hasattr(plugin, '_init'):
            plugin._init(self)
            self.plugins[path] = plugin

    def __try_reconnect(self):
        output_lock.acquire()
        self.ml.blank_readline()

        output_msg(_('Connection lost! Trying to reconnect...'))
        retries = 0
        if self.parsed_uri.scheme == 'ssh':
            password = getpass.getpass()
        else:
            password = None

        while True:
            retries += 1
            try:
                time.sleep(2)
                try:
                    self.connection.connect(self.uri, password=password)
                except paramiko.ssh_exception.AuthenticationException:
                    output_msg(_("Incorrect password"))
                    password = getpass.getpass()
                    continue
                except Exception as e:
                    output_msg(_(
                        "Error reconnecting to host {0}: {1}".format(
                            self.hostname, e)))
                    continue
                try:
                    if self.hostname in ('127.0.0.1', 'localhost') \
                            or self.parsed_uri.scheme == 'unix':
                        self.connection.login_user(getpass.getuser(), '')
                    else:
                        self.connection.login_token(self.connection.token)

                    self.connection.subscribe_events(*EVENT_MASKS)
                except RpcException:
                    output_msg(_("Reauthentication failed (most likely token expired or server was restarted), use the 'login' command to log back in."))
                break
            except Exception as e:
                output_msg(_('Cannot reconnect: {0}'.format(str(e))))

        self.ml.restore_readline()
        output_lock.release()

    def attach_namespace(self, path, ns):
        splitpath = path.split('/')
        ptr = self.root_ns
        ptr_namespaces = ptr.namespaces()

        for n in splitpath[1:-1]:

            if n not in list(ptr_namespaces().keys()):
                self.logger.warn(_("Cannot attach to namespace %s"), path)
                return

            ptr = ptr_namespaces()[n]

        ptr.register_namespace(ns)

    def connection_error(self, event, **kwargs):
        if event == ClientError.LOGOUT:
            output_msg('Logged out from server.')
            self.connection.disconnect()
            sys.exit(0)

        if event == ClientError.CONNECTION_CLOSED:
            time.sleep(1)
            self.__try_reconnect()
            return

    def handle_event(self, event, data):
        if event == 'task.updated':
            if data['id'] in self.task_callbacks:
                self.handle_task_callback(data)

        self.print_event(event, data)

    def handle_task_callback(self, data):
        if data['state'] in ('FINISHED', 'CANCELLED', 'ABORTED', 'FAILED'):
            self.task_callbacks[data['id']](data['state'])

    def print_event(self, event, data):
        if self.event_divert:
            self.event_queue.put((event, data))
            return

        if event == 'task.progress':
            return

        output_lock.acquire()
        self.ml.blank_readline()

        translation = events.translate(self, event, data)
        if translation:
            output_msg(translation)
            if 'state' in data:
                if data['state'] == 'FAILED':
                    status = self.connection.call_sync('task.status', data['id'])
                    output_msg(_(
                        "Task #{0} error: {1}".format(
                            data['id'],
                            status['error'].get('message', '') if status.get('error') else ''
                        )
                    ))

        sys.stdout.flush()
        self.ml.restore_readline()
        output_lock.release()

    def call_sync(self, name, *args, **kwargs):
        return wrap(self.connection.call_sync(name, *args, **kwargs))

    def call_task_sync(self, name, *args, **kwargs):
        self.ml.skip_prompt_print = True
        wrapped_result = wrap(self.connection.call_task_sync(name, *args))
        self.ml.skip_prompt_print = False
        return wrapped_result

    def submit_task(self, name, *args, **kwargs):
        callback = kwargs.pop('callback', None)
        message_formatter = kwargs.pop('message_formatter', None)

        if not self.variables.get('tasks_blocking'):
            tid = self.connection.call_sync('task.submit', name, args)
            if callback:
                self.task_callbacks[tid] = callback

            return tid
        else:
            output_msg(_("Hit Ctrl+C to terminate task if needed"))
            self.event_divert = True
            tid = self.connection.call_sync('task.submit', name, args)
            progress = ProgressBar()
            try:
                while True:
                    event, data = self.event_queue.get()

                    if event == 'task.progress' and data['id'] == tid:
                        message = data['message']
                        if isinstance(message_formatter, collections.Callable):
                            message = message_formatter(message)
                        progress.update(percentage=data['percentage'], message=message)

                    if event == 'task.updated' and data['id'] == tid:
                        progress.update(message=data['state'])
                        if data['state'] == 'FINISHED':
                            progress.finish()
                            break

                        if data['state'] == 'FAILED':
                            six.print_()
                            break
            except KeyboardInterrupt:
                six.print_()
                output_msg(_("User requested task termination. Task abort signal sent"))
                self.call_sync('task.abort', tid)

        self.event_divert = False
        return tid

    def eval(self, *args, **kwargs):
        return self.ml.eval(*args, **kwargs)

    def eval_block(self, *args, **kwargs):
        return self.ml.eval_block(*args, **kwargs)


class FlowControlInstruction(BaseException):
    def __init__(self, type, payload=None):
        self.type = type
        self.payload = payload


class CallStackEntry(object):
    def __init__(self, func, args, file, line, column):
        self.func = func
        self.args = args
        self.file = file
        self.line = line
        self.column = column

    def __str__(self):
        return "at {0}({1}), file {2}, line {3}, column {4}".format(
            self.func,
            ', '.join([str(i) for i in self.args]),
            self.file,
            self.line,
            self.column
        )


class Function(object):
    def __init__(self, context, name, param_names, exp, env):
        self.context = context
        self.name = name
        self.param_names = param_names
        self.exp = exp
        self.env = env

    def __call__(self, *args):
        env = Environment(self.context, self.env, zip(self.param_names, args))
        try:
            self.context.eval_block(self.exp, env, False)
        except FlowControlInstruction as f:
            if f.type == FlowControlInstructionType.RETURN:
                return f.payload

            raise f

    def __str__(self):
        return "<user-defined function '{0}'>".format(self.name)

    def __repr__(self):
        return str(self)


class BuiltinFunction(object):
    def __init__(self, context, name, f):
        self.context = context
        self.name = name
        self.f = f

    def __call__(self, *args):
        return self.f(*args)

    def __str__(self):
        return "<built-in function '{0}'>".format(self.name)

    def __repr__(self):
        return str(self)


class Environment(dict):
    class Variable(object):
        def __init__(self, value):
            self.value = value

    def __init__(self, context, outer=None, iterable=None):
        super(Environment, self).__init__()
        self.context = context
        self.outer = outer
        if iterable:
            for k, v in iterable:
                self[k] = Environment.Variable(v)

    def find(self, var):
        if var in self:
            return self[var]

        if self.outer:
            return self.outer.find(var)

        if var in self.context.builtin_functions:
            return BuiltinFunction(self.context, var, self.context.builtin_functions.get(var))

        raise KeyError(var)


class MainLoop(object):
    pipe_commands = {
        'search': SearchPipeCommand(),
        'exclude': ExcludePipeCommand(),
        'sort': SortPipeCommand(),
        'limit': LimitPipeCommand(),
        'select': SelectPipeCommand(),
        'less': LessPipeCommand()
    }
    base_builtin_commands = {
        'login': LoginCommand(),
        'exit': ExitCommand(),
        'setenv': SetenvCommand(),
        'printenv': PrintenvCommand(),
        'saveenv': SaveenvCommand(),
        'shell': ShellCommand(),
        'help': HelpCommand(),
        'top': TopCommand(),
        'showips': ShowIpsCommand(),
        'showurls': ShowUrlsCommand(),
        'source': SourceCommand(),
        'dump': DumpCommand(),
        'clear': ClearCommand(),
        'history': HistoryCommand(),
        'echo': EchoCommand(),
    }
    builtin_commands = base_builtin_commands.copy()
    builtin_commands.update(pipe_commands)

    def __init__(self, context):
        self.context = context
        self.root_path = [self.context.root_ns]
        self.path = self.root_path[:]
        self.prev_path = self.path[:]
        self.start_from_root = False
        self.namespaces = []
        self.connection = None
        self.skip_prompt_print = False
        self.cached_values = {
            'rel_cwd': None,
            'rel_tokens': None,
            'rel_ptr': None,
            'rel_ptr_namespaces': None,
            'obj': None,
            'obj_namespaces': None,
            'choices': None,
            'scope_cwd': None,
            'scope_namespaces': None,
            'scope_commands': None,
        }

    def __get_prompt(self):
        variables = {
            'path': '/'.join([str(x.get_name()) for x in self.path]),
            'host': self.context.uri
        }
        return self.context.variables.get('prompt').format(**variables)

    def greet(self):
        # output_msg(
        #     _("Welcome to the FreeNAS CLI! Type 'help' to get started."))
        output_msg(self.context.connection.call_sync(
            'system.general.cowsay',
            "Welcome to the FreeNAS CLI! Type 'help' to get started."
        )[0])
        output_msg("")

    def cd(self, ns):
        if not self.cwd.on_leave():
            return

        self.prev_path = self.path[:]
        self.path.append(ns)
        self.cwd.on_enter()

    def cd_up(self):
        if not self.cwd.on_leave():
            return

        self.prev_path = self.path[:]
        if len(self.path) > 1:
            del self.path[-1]
        self.cwd.on_enter()

    @property
    def cwd(self):
        return self.path[-1]

    def repl(self):
        readline.parse_and_bind('tab: complete')
        readline.set_completer(self.complete)

        self.greet()
        a = ShowUrlsCommand()
        try:
            format_output(a.run(self.context, None, None, None))
        except:
            output_msg(_('Cannot show GUI urls'))

        while True:
            try:
                line = six.moves.input(self.__get_prompt()).strip()
            except EOFError:
                six.print_()
                return
            except KeyboardInterrupt:
                six.print_()
                output_msg(_('User terminated command'))
                continue

            self.process(line)

    def find_in_scope(self, token, cwd=None):
        if not cwd:
            cwd = self.cwd

        if token in list(self.builtin_commands.keys()):
            return self.builtin_commands[token]

        cwd_namespaces = cwd.namespaces()
        cwd_commands = list(cwd.commands().items())

        for ns in cwd_namespaces:
            if token == ns.get_name():
                return ns

        for name, cmd in cwd_commands:
            if token == name:
                return cmd

        return None

    def eval_block(self, block, env=None, allow_break=False):
        if env is None:
            env = self.context.global_env

        for stmt in block:
            ret = self.eval(stmt, env)
            if type(ret) is FlowControlInstruction:
                if ret.type == FlowControlInstructionType.BREAK:
                    if not allow_break:
                        raise SyntaxError("'break' cannot be used in this block")

                raise ret

    def eval(self, token, env=None, path=None, serialize_filter=None, input_data=None, dry_run=False):
        if self.start_from_root:
            self.path = self.root_path[:]
            self.start_from_root = False

        cwd = path[-1] if path else self.cwd
        path = path or []

        if env is None:
            env = self.context.global_env

        try:
            if isinstance(token, list):
                return [self.eval(i, env, path) for i in token]

            if isinstance(token, UnaryExpr):
                expr = self.eval(token.expr, env)
                return self.context.builtin_operators[token.op](expr)

            if isinstance(token, BinaryExpr):
                left = self.eval(token.left, env)
                right = self.eval(token.right, env)
                return self.context.builtin_operators[token.op](left, right)

            if isinstance(token, Literal):
                if token.type is list:
                    return [self.eval(i, env) for i in token.value]

                if token.type is dict:
                    return {k: self.eval(v, env) for k, v in token.value.items()}

                return token.value

            if isinstance(token, Symbol):
                try:
                    item = env.find(token.name)
                    return item.value if isinstance(item, Environment.Variable) else item
                except KeyError:
                    item = self.find_in_scope(token.name, cwd=cwd)
                    if item is not None:
                        return item

                # After all scope checks are done check if this is a
                # config environment var of the cli
                try:
                    return self.context.variables.variables[token.name]
                except KeyError:
                    pass
                raise SyntaxError(_('{0} not found'.format(token.name)))

            if isinstance(token, AssignmentStatement):
                expr = self.eval(token.expr, env)

                try:
                    self.context.variables.variables[token.name]
                    raise SyntaxError(_(
                        "{0} is an Environment Variable. Use `setenv` command to set it".format(token.name)
                    ))
                except KeyError:
                    pass
                if isinstance(token.name, Subscript):
                    array = self.eval(token.name.expr, env)
                    index = self.eval(token.name.index, env)
                    array[index] = expr
                    return

                try:
                    env.find(token.name).value = expr
                except KeyError:
                    env[token.name] = Environment.Variable(expr)

                return

            if isinstance(token, IfStatement):
                expr = self.eval(token.expr, env)
                body = token.body if expr else token.else_body
                local_env = Environment(self.context, outer=env)
                self.eval_block(body, local_env, False)
                return

            if isinstance(token, ForStatement):
                local_env = Environment(self.context, outer=env)
                expr = self.eval(token.expr, env)
                if isinstance(token.var, tuple):
                    for k, v in expr.items():
                        local_env[token.var[0]] = k
                        local_env[token.var[1]] = v
                        try:
                            self.eval_block(token.body, local_env, True)
                        except FlowControlInstruction as f:
                            if f.type == FlowControlInstructionType.BREAK:
                                return

                            raise f
                else:
                    for i in expr:
                        local_env[token.var] = i
                        try:
                            self.eval_block(token.body, local_env, True)
                        except FlowControlInstruction as f:
                            if f.type == FlowControlInstructionType.BREAK:
                                return

                            raise f

                return

            if isinstance(token, WhileStatement):
                local_env = Environment(self.context, outer=env)
                while True:
                    expr = self.eval(token.expr, env)
                    if not expr:
                        return

                    try:
                        self.eval_block(token.body, local_env, True)
                    except FlowControlInstruction as f:
                        if f.type == FlowControlInstructionType.BREAK:
                            return

                        raise f

            if isinstance(token, ReturnStatement):
                return FlowControlInstruction(
                    FlowControlInstructionType.RETURN,
                    self.eval(token.expr, env)
                )

            if isinstance(token, BreakStatement):
                return FlowControlInstruction(FlowControlInstructionType.BREAK)

            if isinstance(token, UndefStatement):
                del env[token.name]

            if isinstance(token, ExpressionExpansion):
                expr = self.eval(token.expr, env)
                return expr

            if isinstance(token, CommandCall):
                token = copy.deepcopy(token)
                success = True

                try:
                    if len(token.args) == 0:
                        for i in path:
                            self.cd(i)

                        return

                    top = token.args.pop(0)
                    if top == '..':
                        if not path:
                            self.cd_up()
                            return

                        return self.eval(token, env, path=path[:-1])

                    if isinstance(top, Literal):
                        top = Symbol(top.value)

                    item = self.eval(top, env, path=path)

                    if isinstance(item, (six.string_types, int, bool)):
                        item = self.find_in_scope(str(item), cwd=cwd)

                    if isinstance(item, Namespace):
                        item.on_enter()
                        return self.eval(token, env, path=path+[item], dry_run=dry_run)

                    if isinstance(item, Command):
                        token_args = convert_to_literals(token.args)
                        args, kwargs, opargs = sort_args([self.eval(i, env) for i in token_args])

                        if dry_run:
                            return item, cwd, args, kwargs, opargs

                        if isinstance(item, PipeCommand):
                            if serialize_filter:
                                ret = item.serialize_filter(self.context, args, kwargs, opargs)
                                if ret is not None:
                                    if 'filter' in ret:
                                        serialize_filter['filter'] += ret['filter']

                                    if 'params' in ret:
                                        serialize_filter['params'].update(ret['params'])

                            return item.run(self.context, args, kwargs, opargs, input=input_data)

                        return item.run(self.context, args, kwargs, opargs)
                except BaseException as err:
                    success = False
                    raise err
                finally:
                    env['_success'] = Environment.Variable(success)

                env['_success'] = Environment.Variable(False)
                raise SyntaxError("Command or namespace {0} not found".format(top.name))

            if isinstance(token, FunctionCall):
                args = list(map(lambda a: self.eval(a, env), token.args))
                func = env.find(token.name)
                if func:
                    self.context.call_stack.append(CallStackEntry(func.name, args, token.file, token.line, token.column))
                    result = func(*args)
                    self.context.call_stack.pop()
                    return result

                raise SyntaxError("Function {0} not found".format(token.name))

            if isinstance(token, Subscript):
                expr = self.eval(token.expr, env)
                index = self.eval(token.index, env)
                return expr[index]

            if isinstance(token, FunctionDefinition):
                env[token.name] = Function(self.context, token.name, token.args, token.body, env)
                return

            if isinstance(token, BinaryParameter):
                return token.left, token.op, self.eval(token.right, env)

            if isinstance(token, PipeExpr):
                if serialize_filter:
                    self.eval(token.left, env, path, serialize_filter=serialize_filter)
                    self.eval(token.right, env, path, serialize_filter=serialize_filter)
                    return

                cmd, cwd, args, kwargs, opargs = self.eval(token.left, env, path, dry_run=True)
                cwd.on_enter()
                self.context.pipe_cwd = cwd
                if isinstance(cmd, FilteringCommand):
                    # Do serialize_filter pass
                    filt = {"filter": [], "params": {}}
                    self.eval(token.right, env, path, serialize_filter=filt)
                    result = cmd.run(self.context, args, kwargs, opargs, filtering=filt)
                elif isinstance(cmd, PipeCommand):
                    result = cmd.run(self.context, args, kwargs, opargs, input=input_data)
                else:
                    result = cmd.run(self.context, args, kwargs, opargs)

                ret = self.eval(token.right, input_data=result)
                self.context.pipe_cwd = None
                return ret

        except SystemExit as err:
            raise err

        except BaseException as err:
            raise err

        raise SyntaxError("Unknown AST token: {0}".format(token))

    def process(self, line):
        if len(line) == 0:
            return

        if line[0] == '!':
            self.builtin_commands['shell'].run(
                self.context, [line[1:]], {}, {})
            return

        if line[0] == '/':
            if line.strip() == '/':
                self.prev_path = self.path[:]
                self.path = self.root_path[:]
                return
            else:
                self.start_from_root = True
                line = line[1:]

        if line == '-':
            prev = self.prev_path[:]
            self.prev_path = self.path[:]
            self.path = prev
            return

        try:
            tokens = parse(line, '<stdin>')
            if not tokens:
                return

            for i in tokens:
                try:
                    ret = self.eval(i)
                except SystemExit as err:
                    raise err
                except BaseException as err:
                    output_msg('Error: {0}'.format(str(err)))
                    if len(self.context.call_stack) > 1:
                        output_msg('Call stack: ')
                        for i in self.context.call_stack:
                            output_msg('  ' + str(i))

                    if self.context.variables.get('debug'):
                        output_msg('Python call stack: ')
                        output_msg(traceback.format_exc())

                    return

                if ret:
                    format_output(ret)
        except SyntaxError as e:
            output_msg(_('Syntax error: {0}'.format(str(e))))
        except CommandException as e:
            output_msg(_('Error: {0}'.format(str(e))))
            self.context.logger.error(e.stacktrace)
            if self.context.variables.get('debug'):
                output_msg(e.stacktrace)
        except RpcException as e:
            self.context.logger.error(str(e))
            output_msg(_('RpcException Error: {0}'.format(str(e))))
        except SystemExit as e:
            sys.exit(e)
        except Exception as e:
            output_msg(_('Unexpected Error: {0}'.format(str(e))))
            error_trace = traceback.format_exc()
            self.context.logger.error(error_trace)
            if self.context.variables.get('debug'):
                output_msg(error_trace)

    def get_relative_object(self, ns, tokens):
        ptr = ns
        while len(tokens) > 0:
            token = tokens.pop(0)

            if token == '..' and len(self.path) > 1:
                self.prev_path = self.path[:]
                ptr = self.path[-2]

            if issubclass(type(ptr), Namespace):
                if (
                    self.cached_values['rel_ptr'] == ptr and
                    self.cached_values['rel_ptr_namespaces'] is not None
                   ):
                    nss = self.cached_values['rel_ptr_namespaces']
                else:
                    # Try to somehow make the below work as it saves us one .namespace()
                    # lookup. BUt for now it does work and results in stale autocorrect
                    # options hence commenting
                    # if (
                    #     ptr == self.cached_values['obj'] and
                    #     self.cached_values['obj_namespaces'] is not None
                    #    ):
                    #     nss = self.cached_values['obj_namespaces']
                    # else:
                    nss = ptr.namespaces()
                    self.cached_values.update({
                        'rel_ptr': ptr,
                        'rel_ptr_namespaces': nss
                        })
                for ns in nss:
                    if ns.get_name() == token:
                        ptr = ns
                        break

                cmds = ptr.commands()
                if token in cmds:
                    return cmds[token]

                if token in self.builtin_commands:
                    return self.builtin_commands[token]

        return ptr

    def complete(self, text, state):
        readline_buffer = readline.get_line_buffer()
        tokens = shlex.split(readline_buffer.split('|')[-1].strip(), posix=False)

        if "|" in readline_buffer:
            choices = [x + ' ' for x in list(self.pipe_commands.keys())]
            options = [i for i in choices if i.startswith(text)]
            if state < len(options):
                return options[state]
            else:
                return None
        cwd = self.cwd

        if tokens:
            if tokens[0][0] == '/':
                cwd = self.root_path[0]

        obj = self.cached_values['obj']
        if (
            cwd != self.cached_values['rel_cwd'] or
            tokens != self.cached_values['rel_tokens'] or
            self.cached_values['obj'] is None
           ):
            obj = self.get_relative_object(cwd, tokens[:])
            self.cached_values.update({
                'rel_cwd': cwd,
                'rel_tokens': tokens,
                })

        if issubclass(type(obj), Namespace):
            if self.cached_values['obj'] != obj:
                obj_namespaces = obj.namespaces()
                new_choices = [x.get_name() for x in obj_namespaces] + list(obj.commands().keys())
                self.cached_values.update({
                    'obj': obj,
                    'choices': new_choices,
                    'obj_namespaces': obj_namespaces,
                })
            choices = self.cached_values['choices'][:]
            if (
                len(tokens) == 0 or
                (len(tokens) <= 1 and text not in ['', None])
               ):
                choices += list(self.base_builtin_commands.keys()) + ['..', '/', '-']
            elif 'help' not in choices:
                choices += ['help']
            choices = [i + ' ' for i in choices]

        elif issubclass(type(obj), Command):
            if (
                self.cached_values['obj'] != obj or
                self.cached_values['choices'] is None
               ):
                new_choices = obj.complete(self.context, tokens)
                self.cached_values.update({
                    'obj': obj,
                    'choices': new_choices,
                    'obj_namespaces': None,
                })
            choices = self.cached_values['choices'][:]
        else:
            choices = []

        options = [i for i in choices if i.startswith(text)]
        if state < len(options):
            return options[state]
        else:
            return None

    def sigint(self):
        pass

    def blank_readline(self):
        cols = get_terminal_size((80, 20)).columns
        text_len = len(readline.get_line_buffer()) + 2
        sys.stdout.write('\x1b[2K')
        sys.stdout.write('\x1b[1A\x1b[2K' * int(text_len / (cols or 80)))
        sys.stdout.write('\x1b[0G')

    def restore_readline(self):
        if not self.skip_prompt_print:
            sys.stdout.write(self.__get_prompt() + readline.get_line_buffer().rstrip())
            sys.stdout.flush()


def main():
    current_cli_logfile = os.path.join(CLI_LOG_DIR, 'freenascli.{0}.log'.format(os.getpid()))
    logging.basicConfig(filename=current_cli_logfile, level=logging.DEBUG)
    # create symlink to latest created cli log
    # but first check if previous exists and nuke it
    try:
        if platform.system() != 'Windows':
            latest_log = os.path.join(CLI_LOG_DIR, 'freenascli.latest.log')
            if os.path.lexists(latest_log):
                os.unlink(latest_log)
            os.symlink(current_cli_logfile, latest_log)
            # Try to set the permissions on this symlink to be readable, writable by all
            os.chmod(latest_log, 0o777)
    except OSError:
        # not there no probs or cannot make this symlink move on
        pass
    parser = argparse.ArgumentParser()
    parser.add_argument('uri', metavar='URI', nargs='?',
                        default='unix:')
    parser.add_argument('-m', metavar='MIDDLEWARECONFIG',
                        default=DEFAULT_MIDDLEWARE_CONFIGFILE)
    parser.add_argument('-c', metavar='CONFIG', default=DEFAULT_CLI_CONFIGFILE)
    parser.add_argument('-e', metavar='COMMANDS')
    parser.add_argument('-f', metavar='INPUT')
    parser.add_argument('-p', metavar='PASSWORD')
    parser.add_argument('-D', metavar='DEFINE', action='append')
    args = parser.parse_args()

    if os.environ.get('FREENAS_SYSTEM') != 'YES' and args.uri == 'unix:':
        args.uri = six.moves.input('Please provide FreeNAS IP: ')

    context = Context()
    context.argparse_parser = parser
    context.uri = args.uri
    context.parsed_uri = urlparse(args.uri)
    if context.parsed_uri.scheme == '':
        context.parsed_uri = urlparse("ws://" + args.uri)
    if context.parsed_uri.scheme == 'ws':
        context.uri = context.parsed_uri.hostname
    username = None
    if context.parsed_uri.hostname is None:
        context.hostname = 'localhost'
    else:
        context.hostname = context.parsed_uri.hostname
    if context.parsed_uri.scheme != 'unix' \
            and context.parsed_uri.netloc not in (
                    'localhost', '127.0.0.1', None):
        if context.parsed_uri.username is None:
            username = six.moves.input('Please provide a username: ')
            if context.parsed_uri.scheme == 'ssh':
                context.uri = 'ssh://{0}@{1}'.format(
                        username,
                        context.parsed_uri.hostname)
                if context.parsed_uri.port is not None:
                    context.uri = "{0}:{1}".format(
                            context.uri,
                            context.parsed_uri.port)
                context.parsed_uri = urlparse(context.uri)
        else:
            username = context.parsed_uri.username
        if args.p is None:
            args.p = getpass.getpass('Please provide a password: ')
        else:
            args.p = args.p

    context.read_middleware_config_file(args.m)
    context.variables.load(args.c)
    context.start(args.p)

    ml = MainLoop(context)
    context.ml = ml

    if username is not None:
        context.login(username, args.p)
    elif context.parsed_uri.netloc in ('127.0.0.1', 'localhost') \
            or context.parsed_uri.scheme == 'unix':
        context.login(getpass.getuser(), '')

    if args.D:
        for i in args.D:
            name, value = i.split('=')
            context.variables.set(name, value)

    if args.e:
        ml.process(args.e)
        return

    if args.f:
        try:
            f = sys.stdin if args.f == '-' else open(args.f)
            for line in f:
                ml.process(line.strip())

            f.close()
        except EnvironmentError as e:
            sys.stderr.write('Cannot open input file: {0}'.format(str(e)))
            sys.exit(1)

        return

    ml.repl()


if __name__ == '__main__':
    main()
