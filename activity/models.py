import logging
import re
import time

from django.db import models
import openid.association
from openid.consumer import consumer
from openid.extensions import sreg, ax
from openid.store import interface, nonce


log = logging.getLogger(__name__)


# OpenID models

class Association(Model):
    server_url = db.StringProperty()
    expires = db.IntegerProperty()

    handle = db.StringProperty()
    secret = db.ByteStringProperty()
    issued = db.IntegerProperty()
    lifetime = db.IntegerProperty()
    assoc_type = db.StringProperty()

    def save(self):
        self.expires = self.issued + self.lifetime
        super(Association, self).save()

    def as_openid_association(self):
        return openid.association.Association(
            handle=self.handle,
            secret=self.secret,
            issued=self.issued,
            lifetime=self.lifetime,
            assoc_type=self.assoc_type,
        )


class Squib(Model):
    server_url = db.StringProperty()
    timestamp = db.IntegerProperty()
    salt = db.StringProperty()

    api_type = 'openid_squib'


class OpenIDStore(interface.OpenIDStore):

    def storeAssociation(self, server_url, association):
        a = Association(server_url=server_url)
        for key in ('handle', 'secret', 'issued', 'lifetime', 'assoc_type'):
            setattr(a, key, getattr(association, key))
        a.save()
        log.debug('Stored association %r %r %r %r %r for server %s (expires %r)',
            association.handle, association.secret, association.issued,
            association.lifetime, association.assoc_type, server_url, a.expires)

    def getAssociation(self, server_url, handle=None):
        q = Association.all().filter(server_url=server_url)
        if handle is not None:
            q.filter(handle=handle)

        # No expired associations.
        q.filter(expires__gte=int(time.time()))

        # Get the futuremost association.
        q.order('-expires')

        try:
            a = q[0]
        except IndexError:
            log.debug('Could not find requested association %r for server %s)',
                handle, server_url)
            return
        else:
            log.debug('Found requested association %r for server %s',
                handle, server_url)
            return a.as_openid_association()

    def removeAssociation(self, server_url, handle):
        q = Association.all().filter(server_url=server_url, handle=handle)
        try:
            a = q[0]
        except IndexError:
            log.debug('Could not find requested association %r for server %s to delete',
                handle, server_url)
            return False
        else:
            a.delete()
            log.debug('Found and deleted requested association %r for server %s',
                handle, server_url)
            return True

    def useNonce(self, server_url, timestamp, salt):
        now = int(time.time())
        if timestamp < now - nonce.SKEW or now + nonce.SKEW < timestamp:
            return False

        data = dict(server_url=server_url, timestamp=timestamp, salt=salt)

        q = Squib.all(keys_only=True).filter(**data)
        try:
            s = q[0]
        except IndexError:
            pass
        else:
            log.debug('Discovered squib %r %r for server %s was already used',
                timestamp, salt, server_url)
            return False

        s = Squib(**data)
        s.save()
        log.debug('Noted new squib %r %r for server %s',
            timestamp, salt, server_url)
        return True

    def cleanup(self):
        self.cleanupAssociations()
        self.cleanupNonces()

    def cleanupAssociations(self):
        now = int(time.time())
        q = Association.all(keys_only=True).filter(expires__lt=now - nonce.SKEW)
        db.delete(q.fetch(100))

    def cleanupNonces(self):
        now = int(time.time())
        q = Squib.all(keys_only=True).filter(timestamp__lt=now - nonce.SKEW)
        db.delete(q.fetch(100))

    @classmethod
    def make_person_from_response(cls, resp):
        if not isinstance(resp, consumer.SuccessResponse):
            raise ValueError("Can't make a Person from an unsuccessful response")

        # Find the person.
        openid = resp.identity_url
        p = Person.get(openid=openid)
        if p is None:
            p = Person(openid=openid)

        sr = sreg.SRegResponse.fromSuccessResponse(resp)
        if sr is not None:
            if 'nickname' in sr:
                p.name = sr['nickname']
            if 'email' in sr:
                p.email = sr['email']

        fr = ax.FetchResponse.fromSuccessResponse(resp)
        if fr is not None:
            firstname = fr.getSingle('http://axschema.org/namePerson/first')
            lastname  = fr.getSingle('http://axschema.org/namePerson/last')
            email     = fr.getSingle('http://axschema.org/contact/email')
            if firstname is not None and lastname is not None:
                p.name = ' '.join((firstname, lastname))
            elif firstname is not None:
                p.name = firstname
            if email is not None:
                p.email = email

        if p.name is None:
            name = resp.identity_url
            # Remove the leading scheme, if it's http.
            name = re.sub(r'^http://', '', name)
            # If it's just a domain, strip the trailing slash.
            name = re.sub(r'^([^/]+)/$', r'\1', name)
            p.name = name

        if openid == "http://markpasc.org/mark/":
            p.is_admin = True

        p.save()
