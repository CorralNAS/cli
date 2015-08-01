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

import os
import tty
import inspect
import termios
import sys
import select
import sandbox
import readline
import icu
import re
from namespace import Command, CommandException, description
from output import (Column, output_value, output_dict, ValueType,
                    format_value, output_msg, output_list, output_table,
                    output_lock, output_less)
from dispatcher.shell import ShellClient

t = icu.Transliterator.createInstance("Any-Accents",
                                      icu.UTransDirection.FORWARD)
_ = t.transliterate


@description("Sets variable value")
class SetenvCommand(Command):
    """
    Usage: setenv <variable> <value>

    Sets value of environment variable.
    """
    def run(self, context, args, kwargs, opargs):
        if len(args) < 2:
            raise CommandException('Wrong parameter count')

        context.variables.set(args[0], args[1])

    def complete(self, context, tokens):
        return [k for k, foo in context.variables.get_all()]


@description("Prints variable value")
class PrintenvCommand(Command):
    """
    Usage: printenv [variable]

    Prints a list of environment variables and their values (if called without
    arguments) or value of single environment variable (if called with single
    positional argument - variable name)
    """
    def run(self, context, args, kwargs, opargs):
        if len(args) == 0:
            output_dict(dict(context.variables.get_all_printable()))

        if len(args) == 1:
            try:
                # Yes, the manual call to __str__() is needed as the output_msg
                # in some formatters (ascii) replies on cprint instead of print
                # thus making it a no-go to rely directly on __str__ to be
                # invoked!
                output_msg(context.variables.variables[args[0]].__str__())
            except KeyError:
                output_msg(_("No such Environment Variable exists"))
            return


@description("Saves the Environment Variables to cli config file")
class SaveenvCommand(Command):
    """
    Usage: saveenv filename(Optional)

    Saves the current set of environment variables to the cli config
    file. If not specified then this defaults to "~/.freenascli.conf".
    If the cli was run with the config option (i.e. `cli -c path_to_file)
    and that file existed and was a legitimate config file for the cli and was
    loaded whilst initialization of the cli, then that file is used to dump
    the current environment variables.
    """
    def run(self, context, args, kwargs, opargs):
        if len(args) == 0:
            context.variables.save()
            output_msg(
                'Environment Variables Saved to file: {0}'.format(
                    context.variables.save_to_file))
        if len(args) == 1:
            context.variables.save(args[0])
            output_msg(
                'Environment Variables Saved to file: {0}'.format(args[0]))


@description("Evaluates Python code")
class EvalCommand(Command):
    """
    Usage: eval <Python code fragment>

    Examples:
        eval "print 'hello world'"
    """
    def run(self, context, args, kwargs, opargs):
        sandbox.evaluate(args[0])


@description("Spawns shell, enter \"!shell\" (example: \"!sh\")")
class ShellCommand(Command):
    """
    Usage: shell [command]

    Launches interactive shell on FreeNAS host. That means if CLI is
    used to connect to remote host, also remote shell will be used.
    By default, launches current (logged in) user's login shell. Optional
    positional argument may specify alternative command to run.
    """
    def __init__(self):
        super(ShellCommand, self).__init__()
        self.closed = False

    def run(self, context, args, kwargs, opargs):
        def read(data):
            sys.stdout.write(data)
            sys.stdout.flush()

        def close():
            self.closed = True

        self.closed = False
        name = args[0] if len(args) > 0 and len(args[0]) > 0 else '/bin/sh'
        token = context.connection.call_sync('shell.spawn', name)
        shell = ShellClient(context.hostname, token)
        shell.open()
        shell.on_data(read)
        shell.on_close(close)

        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        tty.setraw(fd)

        while not self.closed:
            r, w, x = select.select([fd], [], [], 0.1)
            if fd in r:
                ch = os.read(fd, 1)
                shell.write(ch)

        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


@description("Shuts the system down")
class ShutdownCommand(Command):
    """
    Usage: shutdown

    Shuts the system down.
    """
    def run(self, context, args, kwargs, opargs):
        output_msg(_("System going for a shutdown..."))
        context.submit_task('system.shutdown')


@description("Reboots the system")
class RebootCommand(Command):
    """
    Usage: reboot

    Reboots the system.
    """
    def run(self, context, args, kwargs, opargs):
        output_msg(_("System going for a reboot..."))
        context.submit_task('system.reboot')


@description("Displays the active IP addresses from all configured network interface")
class ShowIpsCommand(Command):
    """
    Usage: showips

    Displays the active IP addresses from all configured network interfaces.
    """
    def run(self, context, args, kwargs, opargs):
        output_msg(_("These are the active ips from all the configured"
                     " network interfaces"))
        output_list(context.connection.call_sync('network.config.get_my_ips'),
                    _("IP Addresses"))


@description("Displays the URLs to access the web GUI from")
class ShowUrlsCommand(Command):
    """
    Usage: showurls

    Displays the URLs to access the web GUI from.
    """
    def run(self, context, args, kwargs, opargs):
        output_msg(_("You may try the following URLs to access"
                     " the web user interface:"))
        my_ips = context.connection.call_sync('network.config.get_my_ips')
        my_protocols = context.connection.call_sync(
            'system.ui.get_config')
        urls = []
        for proto in my_protocols['webui_procotol']:
            proto_port = my_protocols['webui_{0}_port'.format(proto.lower())]
            if proto_port is not None:
                if proto_port in [80, 443]:
                    for x in my_ips:
                        urls.append('{0}://{1}'.format(proto.lower(), x))
                else:
                    for x in my_ips:
                        urls.append('{0}://{1}:{2}'.format(proto.lower(), x,
                                                           proto_port))
        output_list(urls, label=_('URLs'))


@description("Exits the CLI, enter \"^D\" (ctrl+D)")
class ExitCommand(Command):
    """
    Usage: exit

    Exits from the CLI.
    """
    def run(self, context, args, kwargs, opargs):
        sys.exit(0)


@description("Provides help on commands")
class HelpCommand(Command):
    """
    Usage: help [command command ...]

    Provides usage information on particular command. If command can't be
    reached directly in current namespace, may be specified as chain,
    eg: "account users show".

    Examples:
        help
        help printenv
        help account users show
    """
    def run(self, context, args, kwargs, opargs):
        obj = context.ml.get_relative_object(context.ml.path[-1], args)
        bases = map(lambda x: x.__name__, obj.__class__.__bases__)

        if 'Command' in bases and obj.__doc__:
            output_msg(inspect.getdoc(obj))

        if any(i in ['Namespace', 'EntityNamespace'] for i in bases):
            # First listing the Current Namespace's commands
            cmd_dict_list = []
            ns_cmds = obj.commands()
            for key, value in ns_cmds.iteritems():
                cmd_dict = {
                    'cmd': key,
                    'description': value.description,
                }
                cmd_dict_list.append(cmd_dict)

            # Then listing the namespaces available form this namespace
            namespaces_dict_list = []
            for nss in obj.namespaces():
                namespace_dict = {
                    'name': nss.name,
                    'description': nss.description,
                }
                namespaces_dict_list.append(namespace_dict)

            # Finally listing the builtin cmds
            builtin_cmd_dict_list = []
            for key, value in context.ml.builtin_commands.iteritems():
                builtin_cmd_dict = {
                    'cmd': key,
                    'description': value.description,
                }
                builtin_cmd_dict_list.append(builtin_cmd_dict)

            # Finally printing all this out in unix `LESS(1)` pager style
            output_call_list = []
            if cmd_dict_list:
                output_call_list.append(lambda: output_table(cmd_dict_list, [
                    Column('Command', 'cmd', ValueType.STRING),
                    Column('Description', 'description', ValueType.STRING)]))
            if namespaces_dict_list:
                output_call_list.append(
                    lambda: output_table(namespaces_dict_list, [
                        Column('Namespace', 'name', ValueType.STRING),
                        Column('Description', 'description', ValueType.STRING)
                        ]))
            # Only display the help on builtin commands if in the RootNamespace
            if obj.__class__.__name__ == 'RootNamespace':
                output_call_list.append(
                    lambda: output_table(builtin_cmd_dict_list, [
                        Column('Builtin Command', 'cmd', ValueType.STRING),
                        Column('Description', 'description', ValueType.STRING)
                    ]))
            output_less(output_call_list)


@description("Sends the user to the top level")
class TopCommand(Command):
    """
    Usage: top, /

    Sends you back to the top level of the command tree.
    """
    def run(self, context, args, kwargs, opargs):
        context.ml.path = [context.root_ns]


@description("Clears the cli stdout")
class ClearCommand(Command):
    """
    Usage: clear

    Clears the CLI's stdout. Works exactly the same as its shell counterpart.
    """
    def run(self, context, args, kwargs, opargs):
        output_lock.acquire()
        os.system('cls' if os.name == 'nt' else 'clear')
        output_lock.release()


@description("Shows the CLI command history")
class HistoryCommand(Command):
    """
    Usage: history

    Lists the list commands previously executed in this CLI instance.
    """
    def run(self, context, args, kwargs, opargs):
        histroy_range = readline.get_current_history_length()
        history = [readline.get_history_item(i) for i in range(histroy_range)]
        output_less(lambda: output_list(history, label="Command History"))


@description("Imports a script for parsing")
class SourceCommand(Command):
    """
    Usage: source <filename>
           source <filename1> <filename2> <filename3>

    Imports scripts of cli commands for parsing.
    """

    def run(self, context, args, kwargs, opargs):
        if len(args) == 0:
            output_msg(_("Usage: source <filename>"))
        else:
            for arg in args:
                if os.path.isfile(arg):
                    path = context.ml.path[:]
                    context.ml.path = [context.root_ns]
                    try:
                        with open(arg, 'r') as f:
                            for line in f:
                                context.ml.process(line)
                    except UnicodeDecodeError, e:
                        output_msg(_("Incorrect filetype, cannot parse file: {0}".format(str(e))))
                    finally:
                        context.ml.path = path
                else:
                    output_msg(_("File " + arg + " does not exist."))


@description("Prints the provided message to the output")
class EchoCommand(Command):
    """
    Usage: echo string_to_display

    The echo utility writes any specified operands, separated by single blank
    (` ') characters and followed by a newline (`\\n') character, to the
    standard output. It also has the ability to expand and substitute
    environment variables in place using the '$' or '${variable_name}' syntax/

    Examples:
    echo Have a nice Day!
    output: Have a nice Day!

    echo Hey \\n how are you?
    output: Hey
    how are you?

    echo Hello the current cli session timeout is $timeout seconds
    output: Hello the current cli session timeout is 10 seconds

    echo Hi there, you are using ${language}lang
    output Hi there, you are using Clang
    """
    def run(sef, context, args, kwargs, opargs):
        if len(args) == 0:
            output_msg("")
        else:
            curly_regex = "\$\{([\w]+)\}"
            echo_output_list = ' '.join(args)
            echo_output_list = echo_output_list.split('\\n')
            for x, lst in enumerate(echo_output_list):
                tmp_lst = lst.split(' ')
                for y, word in enumerate(tmp_lst):
                    occurences = re.findall(curly_regex, word)
                    for r in occurences:
                        try:
                            value = context.variables.variables[r].__str__()
                        except:
                            output_msg(r + " " + _("No such Environment Variable exists"))
                            return
                        rep = "\$\{" + r + "\}"
                        word = re.sub(rep, value, word)
                    tmp_lst[y] = word
                    if word.startswith('$'):
                        try:
                            tmp_lst[y] = context.variables.variables[word.strip()[1:]].__str__()
                        except KeyError:
                            output_msg(word[1:] + " " + _("No such Environment Variable exists"))
                            return

                echo_output_list[x] = ' '.join(tmp_lst)
            map(output_msg, echo_output_list)


@description("Allows the user to scroll through output")
class LessCommand(Command):
    """
    Usage: less <really long string of text>
           <command> | less

    Examples: task list | less

    Allows paging and scrolling through long outputs of text.
    """
    def run(self, context, args, kwargs, opargs):
        if len(args) == 0:
            output_msg("")
        else:
            less_output = ' '.join(args)
            output_less(lambda: output_msg(less_output))


@description("Shows the user the last few lines of output")
class TailCommand(Command):
    """
    Usage : <command> | tail
            <command> | tail -n <number>

    Examples: tasks list | tail
              tasks list | tail -n 10

    Displays the last lines of output.
    """
    def run(self, context, args, kwargs, opargs):
        if len(args) == 0:
            output_msg("")
        else:
            numlines = 5
            tail_output = ""
            tail_input_list = ' '.join(args).split('\n')
            tailargs = tail_input_list[0].strip().split(' ')[0:2]
            if tailargs[0] == '-n':
                try:
                    numlines = int(tailargs[1])
                    # strip off the first "-n <number>" from the input
                    tail_input_list[0] = re.sub("-n\s*\d*", '', tail_input_list[0], 1).lstrip()
                except:
                    pass
            tail_length = len(tail_input_list)
            if tail_length < numlines:
                numlines = tail_length
            for i in range(tail_length - numlines, tail_length):
                tail_output += tail_input_list[i]
                if i < tail_length - 1:
                    tail_output += '\n'
            output_msg(tail_output);
