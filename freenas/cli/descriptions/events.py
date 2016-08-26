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


import gettext


t = gettext.translation('freenas-cli', fallback=True)
_ = t.gettext


events = {
    'server.client_login': (
        _("User logged in"),
        lambda c, a: _("User {0} logged in").format(a['username'])
    ),
    'server.client_logout': (
        _("Client logged out"),
        lambda c, a: _("Client {0} logged out").format(a['username'])
    ),
    'service.started': (
        _("Service started"),
        lambda c, a: _("Service {0} started".format(a.get('name')))
    ),
    'service.stopped': (
        _("Service stopped"),
        lambda c, a: _("Service {0} stopped".format(a.get('name')))
    ),
    'session.message': (
        _("A message"),
        lambda c, a: _("Message from user {0}: {1}".format(
            a.get('sender_name'),
            a.get('message')
        ))
    )
}


def translate(context, name, args=None):
    if name not in list(events.keys()):
        return

    first, second = events[name]

    if args is None:
        return first

    return second(context, args)
