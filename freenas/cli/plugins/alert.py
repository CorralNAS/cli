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

import gettext
from freenas.cli.namespace import (
    Namespace, EntityNamespace, Command, EntitySubscriberBasedLoadMixin,
    IndexCommand, description, CommandException
)
from freenas.cli.output import ValueType, Table


t = gettext.translation('freenas-cli', fallback=True)
_ = t.gettext


@description("System alerts")
class AlertNamespace(EntitySubscriberBasedLoadMixin, EntityNamespace):
    def __init__(self, name, context):
        super(AlertNamespace, self).__init__(name, context)
        self.entity_subscriber_name = 'alert'
        self.primary_key_name = 'id'
        self.allow_edit = False

        self.add_property(
            descr='ID',
            name='id',
            get='id',
            set=None,
            list=True
        )

        self.add_property(
            descr='Timestamp',
            name='timestamp',
            get='created_at',
            set=None,
            list=True,
            type=ValueType.TIME
        )

        self.add_property(
            descr='Severity',
            name='severity',
            get='severity',
            list=True,
            set=None,
        )

        self.add_property(
            descr='Message',
            name='description',
            get='description',
            list=True,
            set=None,
        )

        self.add_property(
            descr='Dismissed',
            name='dismissed',
            get='dismissed',
            list=True,
            type=ValueType.BOOLEAN
        )

        self.primary_key = self.get_mapping('id')


def _init(context):
    context.attach_namespace('/', AlertNamespace('alert', context))
