# coding=utf-8
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


import gettext
from freenas.cli.namespace import (
    Command, Namespace, EntityNamespace, TaskBasedSaveMixin,
    EntitySubscriberBasedLoadMixin, description, CommandException
)
from freenas.cli.output import ValueType
from freenas.cli.complete import EnumComplete, NullComplete


t = gettext.translation('freenas-cli', fallback=True)
_ = t.gettext


@description(_("Provides access to Cryptography options"))
class CryptoNamespace(EntitySubscriberBasedLoadMixin, EntityNamespace):
    """
    The cryptography namespace is used to manage crypthography related
    aspects of the system.
    """
    def __init__(self, name, context):
        super(CryptoNamespace, self).__init__(name, context)
        self.context = context
        self.entity_subscriber_name = 'crypto.certificate'
        self.primary_key_name = 'name'
        self.allow_create = False

        self.localdoc['ListCommand'] = ("""\
            Usage: show

            Lists all certificates, optionally doing filtering and sorting.
            """)

        self.add_property(
            descr='Name',
            name='name',
            get='name',
            set='name',
            list=True)

        self.add_property(
            descr='Type',
            name='type',
            get='type',
            set='type',
            usersetable=False,
            list=True)

        self.add_property(
            descr='Serial',
            name='serial',
            get='serial',
            set='serial',
            type=ValueType.NUMBER,
            usersetable=False,
            list=True)

    def namespaces(self):
        return [
            CertificateNamespace('certificate', self.context),
            CertificateAuthorityNamespace('ca', self.context)
        ]


class CertificateBaseNamespace(TaskBasedSaveMixin, EntitySubscriberBasedLoadMixin, EntityNamespace):
    """
    Base class for CertificateAuthority and Certificate Namespaces
    """
    def __init__(self, name, context):
        super(CertificateBaseNamespace, self).__init__(name, context)

        self.context = context
        self.entity_subscriber_name = 'crypto.certificate'
        self.create_task = 'crypto.certificate.create'
        self.update_task = 'crypto.certificate.update'
        self.import_task = 'crypto.certificate.import'
        self.delete_task = 'crypto.certificate.delete'
        self.primary_key_name = 'name'

        self.add_property(
            descr='Name',
            name='name',
            get='name',
            set='name',
            list=True)

        self.add_property(
            descr='Certificate',
            name='certificate',
            get='certificate',
            set='certificate',
            type=ValueType.TEXT_FILE,
            usersetable=lambda e: e['type'] in ('CA_EXISTING', 'CERT_EXISTING'),
            list=False)

        self.add_property(
            descr='Certificate Path',
            name='certificate_path',
            get='certificate_path',
            set='certificate_path',
            type=ValueType.STRING,
            usersetable=False,
            list=False)

        self.add_property(
            descr='Private Key',
            name='privatekey',
            get='privatekey',
            set='privatekey',
            type=ValueType.TEXT_FILE,
            usersetable=lambda e: e['type'] in ('CA_EXISTING', 'CERT_EXISTING'),
            list=False)

        self.add_property(
            descr='Private Key Path',
            name='privatekey_path',
            get='privatekey_path',
            set='privatekey_path',
            type=ValueType.STRING,
            usersetable=False,
            list=False)

        self.add_property(
            descr='Serial',
            name='serial',
            get='serial',
            set='serial',
            type=ValueType.NUMBER,
            usersetable=False,
            list=True)

        self.add_property(
            descr="Self-signed",
            name='selfsigned',
            get='selfsigned',
            set='selfsigned',
            usersetable=False,
            type=ValueType.BOOLEAN,
            list=True)

        self.add_property(
            descr='Key length',
            name='key_length',
            get='key_length',
            set='key_length',
            type=ValueType.NUMBER,
            usersetable=False,
            list=False)

        self.add_property(
            descr='Digest algorithm',
            name='digest_algorithm',
            get='digest_algorithm',
            set='digest_algorithm',
            enum=['SHA1', 'SHA224', 'SHA256', 'SHA384', 'SHA512'],
            usersetable=False,
            list=False)

        self.add_property(
            descr='Not Before',
            name='not_before',
            get='not_before',
            set='not_before',
            usersetable=False,
            list=True)

        self.add_property(
            descr='Not After',
            name='not_after',
            get='not_after',
            set='not_after',
            usersetable=False,
            list=True)

        self.add_property(
            descr='Lifetime',
            name='lifetime',
            get='lifetime',
            set='lifetime',
            usage=_("""\
            Certificate lifetime in days, accepts number values"""),
            type=ValueType.NUMBER,
            usersetable=False,
            list=False)

        self.add_property(
            descr='Country',
            name='country',
            get='country',
            set='country',
            usersetable=False,
            list=False)

        self.add_property(
            descr='State',
            name='state',
            get='state',
            set='state',
            usersetable=False,
            list=False)

        self.add_property(
            descr='City',
            name='city',
            get='city',
            set='city',
            usersetable=False,
            list=False)

        self.add_property(
            descr='Organization',
            name='organization',
            get='organization',
            set='organization',
            usersetable=False,
            list=False)

        self.add_property(
            descr='Common Name',
            name='common',
            get='common',
            set='common',
            usersetable=False,
            list=False)

        self.add_property(
            descr='Email',
            name='email',
            get='email',
            set='email',
            usersetable=False,
            list=False)

    def get_ca_names(self):
        return self.context.entity_subscribers[self.entity_subscriber_name].query(
            ('type', 'in', ('CA_INTERNAL', 'CA_INTERMEDIATE')),
            select='name'
        )


@description(_("Provides access to Certificate Authority actions"))
class CertificateAuthorityNamespace(CertificateBaseNamespace):
    """
    The Certificate Authority namespace provides commands for listing and managing CAs.
    """
    def __init__(self, name, context):
        super(CertificateAuthorityNamespace, self).__init__(name, context)

        self.extra_query_params = [
            ('type', 'in', ('CA_EXISTING', 'CA_INTERMEDIATE', 'CA_INTERNAL'))
        ]
        self.extra_commands = {
            'import': ImportCertificateAuthorityCommand(self)
        }

        self.localdoc['CreateEntityCommand'] = ("""\
            Crates a Certificate Authority. For a list of properties, see 'help properties'.

            Usage:

            Examples:
            Create root CA Certificate :
                create type=CA_INTERNAL name=myRootCA selfsigned=yes key_length=2048 digest_algorithm=SHA256
                lifetime=3650 country=PL state=Slaskie city=Czerwionka-Leszczyny
                organization=myCAOrg email=a@b.c common=my_CA_Server
            Create intermediate CA Certificate :
                create type=CA_INTERMEDIATE signing_ca_name=myRootCA name=myInterCA key_length=2048 digest_algorithm=SHA256
                lifetime=365 country=PL state=Slaskie city=Czerwionka-Leszczyny organization=myorg email=a@b.c
                common=MyCommonName""")

        self.add_property(
            descr='Type',
            name='type',
            get='type',
            set='type',
            enum=[
                'CA_EXISTING',
                'CA_INTERMEDIATE',
                'CA_INTERNAL'
            ],
            usersetable=False,
            list=True)

        self.add_property(
            descr="Signing CA's Name",
            name='signing_ca_name',
            get=lambda e: e['signing_ca_name'],
            set='signing_ca_name',
            enum=self.get_ca_names,
            condition=lambda e: e['type'] == 'CA_INTERMEDIATE',
            usersetable=False,
            list=True)

        self.add_property(
            descr="Signing CA's ID",
            name='signing_ca_id',
            get='signing_ca_id',
            set='signing_ca_id',
            condition=lambda e: e['type'] == 'CA_INTERMEDIATE',
            usersetable=False,
            list=False)

        self.add_property(
            descr='Pass Phrase',
            name='passphrase',
            get='passphrase',
            set='passphrase',
            usersetable=False,
            list=False)

        self.primary_key = self.get_mapping('name')


@description("Imports given CA")
class ImportCertificateAuthorityCommand(Command):
    """
    Usage: import type=CA_EXISTING name=<name>

    Examples:
    Import existing CA Certificate :
    import type=CA_EXISTING name=myImportedCA
    myImportedCA edit certificate
    myImportedCA edit privatekey

    Imports a Certificate Authority.
    """
    def __init__(self, parent):
        self.parent = parent

    def run(self, context, args, kwargs, opargs):
        if not kwargs:
            raise CommandException(_("Import requires more arguments, see 'help import' for more information"))
        if 'type' not in kwargs or kwargs['type'] != "CA_EXISTING":
            raise CommandException(_("Pleaes specify valid 'type' argument value"))
        if 'name' not in kwargs:
            raise CommandException(_("Please specify name of the imported CA"))

        context.submit_task(self.parent.import_task, kwargs)

    def complete(self, context):
        return [
            NullComplete('name='),
            EnumComplete('type=', ['CA_EXISTING'])
        ]


@description(_("Provides access to Certificate actions"))
class CertificateNamespace(CertificateBaseNamespace):
    """
    The Certificate namespace provides commands for listing and managing cryptography certificates.
    """
    def __init__(self, name, context):
        super(CertificateNamespace, self).__init__(name, context)

        self.extra_query_params = [
            ('type', 'in', ('CERT_INTERNAL', 'CERT_CSR', 'CERT_INTERMEDIATE', 'CERT_EXISTING'))
        ]
        self.extra_commands = {
            'import': ImportCertificateCommand(self)
        }

        self.localdoc['CreateEntityCommand'] = ("""\
            Crates a certificate. For a list of properties, see 'help properties'.

            Usage:

            Examples:
            Create self-signed server certificate without CA:
                create type=CERT_INTERNAL name=mySelfSignedServerCert selfsigned=yes key_length=2048
                digest_algorithm=SHA256 lifetime=365 country=PL state=Slaskie city=Czerwionka-Leszczyny
                organization=myorg email=a@b.c common=www.myserver.com
            Create server certificate signed by internal root CA Certificate:
                create type=CERT_INTERNAL name=myCASignedServerCert signing_ca_name=myRootCA key_length=2048
                digest_algorithm=SHA256 lifetime=365 country=PL state=Slaskie city=Czerwionka-Leszczyny
                organization=myorg email=a@b.c common=www.myserver.com""")

        self.add_property(
            descr='Type',
            name='type',
            get='type',
            set='type',
            enum=[
                'CERT_CSR',
                'CERT_EXISTING',
                'CERT_INTERMEDIATE',
                'CERT_INTERNAL',
            ],
            usersetable=False,
            list=True)

        self.add_property(
            descr="Signing CA's Name",
            name='signing_ca_name',
            get=lambda e: e['signing_ca_name'],
            set='signing_ca_name',
            enum=self.get_ca_names,
            condition=lambda e: e['type'] != 'CERT_EXISTING' and e['type'] != 'CERT_CSR',
            usersetable=False,
            list=True)

        self.add_property(
            descr="Signing CA's ID",
            name='signing_ca_id',
            get='signing_ca_id',
            set='signing_ca_id',
            condition=lambda e: e['type'] != 'CERT_EXISTING' and e['type'] != 'CERT_CSR',
            usersetable=False,
            list=False)

        self.primary_key = self.get_mapping('name')


@description("Imports given CA")
class ImportCertificateCommand(Command):
    """
    Usage: import type=CERT_EXISTING name=<name>

    Examples:
    Import existing server certificate:
    import type=CERT_EXISTING name=myImportedServerCert
    myImportedServerCert edit certificate
    myImportedServerCert edit privatekey

    Imports a Certificate.
    """
    def __init__(self, parent):
        self.parent = parent

    def run(self, context, args, kwargs, opargs):
        if not kwargs:
            raise CommandException(_("Import requires more arguments, see 'help import' for more information"))
        if 'type' not in kwargs or kwargs['type'] != "CERT_EXISTING":
            raise CommandException(_("Pleaes specify valid 'type' argument value"))
        if 'name' not in kwargs:
            raise CommandException(_("Please specify name of the imported Certificate"))

        context.submit_task(self.parent.import_task, kwargs)

    def complete(self, context):
        return [
            NullComplete('name='),
            EnumComplete('type=', ['CERT_EXISTING'])
        ]


def _init(context):
    context.attach_namespace('/', CryptoNamespace('crypto', context))
    context.map_tasks('crypto.certificate.*', CertificateNamespace)
    context.map_tasks('crypto.certificate.*', CertificateAuthorityNamespace)


def get_top_namespace(context):
    return CryptoNamespace('crypto', context)
