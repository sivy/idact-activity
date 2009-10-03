from activity.models import Person


class AuthenticationMiddleware(object):

    def process_request(self, request):
        person = None

        try:
            openid = request.session['openid']
            person = Person.objects.get(openid=openid)
        except KeyError:
            pass
        except Person.DoesNotExist:
            # Have them sign in again.
            del request.session['openid']

        request.user = person
