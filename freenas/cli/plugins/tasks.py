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
from freenas.cli.output import ValueType
from freenas.cli.descriptions import tasks
from freenas.cli.namespace import EntityNamespace, EntitySubscriberBasedLoadMixin, Command, description
from freenas.cli.utils import describe_task_state


t = gettext.translation('freenas-cli', fallback=True)
_ = t.gettext


@description("Submits new task")
class SubmitCommand(Command):
    """
    Usage: submit <task>

    Submits a task to the dispatcher for execution

    Examples:
        submit update.check
    """
    def run(self, context, args, kwargs, opargs):
        name = args.pop(0)
        context.submit_task(name, *args)


@description("Aborts running task")
class AbortCommand(Command):
    """
    Usage: abort

    Submits a task to the dispatcher for execution

    Examples:
        submit update.check
    """
    def __init__(self, parent):
        self.parent = parent

    def run(self, context, args, kwargs, opargs):
        context.call_sync('task.abort', self.parent.entity['id'])


@description("Manage tasks")
class TasksNamespace(EntitySubscriberBasedLoadMixin, EntityNamespace):
    def __init__(self, name, context):
        super(TasksNamespace, self).__init__(name, context)

        self.allow_create = False
        self.allow_edit = False
        self.entity_subscriber_name = 'task'

        self.add_property(
            descr='ID',
            name='id',
            get='id',
            list=True,
        )

        self.add_property(
            descr='Started at',
            name='started_at',
            get='started_at',
            list=True,
            type=ValueType.TIME
        )

        self.add_property(
            descr='Finished at',
            name='finished_at',
            get='finished_at',
            list=True,
            type=ValueType.TIME
        )

        self.add_property(
            descr='Description',
            name='description',
            get=self.describe_task,
        )

        self.add_property(
            descr='State',
            name='state',
            get=describe_task_state,
        )

        self.primary_key = self.get_mapping('id')
        self.entity_commands = lambda this: {
            'abort': AbortCommand(this)
        }

        self.extra_commands = {
            'submit': SubmitCommand()
        }

    def serialize(self):
        raise NotImplementedError()

    def describe_task(self, task):
        return tasks.translate(self.context, task['name'], task['args'])


def _init(context):
    context.attach_namespace('/', TasksNamespace('task', context))
