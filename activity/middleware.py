import logging

from activity.models import Person


log = logging.getLogger(__name__)


class AuthenticationMiddleware(object):

    def process_request(self, request):
        person = None
        sessionid = request.COOKIES['sessionid']

        try:
            openid = request.session['openid']
            person = Person.objects.get(openid=openid)
        except KeyError:
            log.debug('Visitor %r has no openid', sessionid)
        except Person.DoesNotExist:
            log.debug('Visitor %r had openid %r but no Person record',
                sessionid, openid)
            # Have them sign in again.
            del request.session['openid']
        else:
            log.debug('Visitor %r has openid %r which is %r',
                sessionid, openid, person)

        request.user = person
