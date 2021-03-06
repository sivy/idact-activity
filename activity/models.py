from base64 import b64encode, b64decode
import logging
import re
import time

from django.db import models
import openid.association
from openid.consumer import consumer
from openid.extensions import ax
from openid.store import interface, nonce


log = logging.getLogger(__name__)


class Person(models.Model):

    openid = models.CharField(max_length=500)
    avatar = models.CharField(max_length=255)
    name = models.CharField(max_length=500)
    email = models.EmailField()
    created = models.DateTimeField(auto_now_add=True)

    def get_permalink_url(self):
        return self.openid

    @property
    def newest_thanks_sent(self):
        try:
            return self.thanks_sent.order_by('-created')[0]
        except IndexError:
            return


class Thanks(models.Model):

    person_from = models.ForeignKey(Person, related_name='thanks_sent')
    person_to = models.ForeignKey(Person, related_name='thanks_received')
    message = models.TextField()
    created = models.DateTimeField(auto_now_add=True)


# OpenID models

class Association(models.Model):
    server_url = models.CharField(max_length=500)
    expires = models.IntegerField()

    handle = models.CharField(max_length=500)
    secret = models.CharField(max_length=500)
    issued = models.IntegerField()
    lifetime = models.IntegerField()
    assoc_type = models.CharField(max_length=500)

    def save(self):
        self.expires = self.issued + self.lifetime
        super(Association, self).save()

    def as_openid_association(self):
        return openid.association.Association(
            handle=self.handle,
            # We had to store the secret base64 encoded.
            secret=b64decode(self.secret),
            issued=self.issued,
            lifetime=self.lifetime,
            assoc_type=self.assoc_type,
        )


class Nonce(models.Model):

    server_url = models.CharField(max_length=500)
    timestamp = models.IntegerField()
    salt = models.CharField(max_length=500)


class OpenIDStore(interface.OpenIDStore):

    def storeAssociation(self, server_url, association):
        a = Association(server_url=server_url)
        for key in ('handle', 'issued', 'lifetime', 'assoc_type'):
            setattr(a, key, getattr(association, key))

        # The secret is a bytestring, which Django will try to decode as UTF-8 later,
        # so base64 encode it first.
        a.secret = b64encode(association.secret)

        a.save()
        log.debug('Stored association %r %r %r %r %r for server %s (expires %r)',
            association.handle, association.secret, association.issued,
            association.lifetime, association.assoc_type, server_url, a.expires)

    def getAssociation(self, server_url, handle=None):
        q = Association.objects.all().filter(server_url=server_url)
        if handle is not None:
            q.filter(handle=handle)

        # No expired associations.
        q.filter(expires__gte=int(time.time()))

        # Get the futuremost association.
        q.order_by('-expires')

        try:
            a = q[0]
        except IndexError:
            log.debug('Could not find requested association %r for server %s',
                handle, server_url)
            return

        log.debug('Found requested association %r for server %s',
            handle, server_url)
        return a.as_openid_association()

    def removeAssociation(self, server_url, handle):
        q = Association.objects.all().filter(server_url=server_url, handle=handle)
        try:
            a = q[0]
        except IndexError:
            log.debug('Could not find requested association %r for server %s to delete',
                handle, server_url)
            return False

        a.delete()
        log.debug('Found and deleted requested association %r for server %s',
            handle, server_url)
        return True

    def useNonce(self, server_url, timestamp, salt):
        now = int(time.time())
        if timestamp < now - nonce.SKEW or now + nonce.SKEW < timestamp:
            return False

        data = dict(server_url=server_url, timestamp=timestamp, salt=salt)

        q = Nonce.objects.all().filter(**data)
        try:
            s = q[0]
        except IndexError:
            pass
        else:
            log.debug('Discovered nonce %r %r for server %s was already used',
                timestamp, salt, server_url)
            return False

        s = Nonce(**data)
        s.save()
        log.debug('Noted new nonce %r %r for server %s',
            timestamp, salt, server_url)
        return True

    def cleanup(self):
        self.cleanupAssociations()
        self.cleanupNonces()

    def cleanupAssociations(self):
        now = int(time.time())
        q = Association.objects.all().filter(expires__lt=now - nonce.SKEW)
        q.delete()
        log.debug('Deleted expired associations')

    def cleanupNonces(self):
        now = int(time.time())
        q = Nonce.objects.all().filter(timestamp__lt=now - nonce.SKEW)
        q.delete()
        log.debug('Deleted expired nonces')

    @classmethod
    def default_name_for_url(cls, name):
        # Remove the leading scheme, if it's http.
        name = re.sub(r'^http://', '', name)
        # If it's just a domain, strip the trailing slash.
        name = re.sub(r'^([^/]+)/$', r'\1', name)
        return name

    @classmethod
    def make_person_from_response(cls, resp):
        if not isinstance(resp, consumer.SuccessResponse):
            raise ValueError("Can't make a Person from an unsuccessful response")

        # Find the person.
        openid = resp.identity_url
        try:
            p = Person.objects.get(openid=openid)
        except Person.DoesNotExist:
            p = Person(openid=openid)

        # Save Attribute Exchange data we may have asked for.
        fr = ax.FetchResponse.fromSuccessResponse(resp)
        if fr is not None:
            log.info('For %s, got Attribute Exchange fields: %r', openid, fr.data.keys())
            nickname = fr.getSingle('http://axschema.org/namePerson/friendly')
            avatar   = fr.getSingle('http://axschema.org/media/image/aspect11')
            if nickname:
                p.name = nickname
            if avatar:
                p.avatar = avatar

        # Make up a name from the URL if necessary.
        if not p.name:
            p.name = cls.default_name_for_url(resp.identity_url)

        p.save()
