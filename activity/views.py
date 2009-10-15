import httplib2
import logging
from urllib import urlencode

from django.conf import settings
from django.core.urlresolvers import reverse
from django.http import HttpResponseRedirect, HttpResponseNotFound
from django.shortcuts import render_to_response
from django.template import RequestContext
from openid.consumer import consumer, discover
from openid.extensions import sreg, ax

from activity.decorators import auth_forbidden, auth_required
from activity.models import Person, Thanks, OpenIDStore


log = logging.getLogger(__name__)


@auth_required
def home(request, params=None):
    if params is None:
        params = {}

    params['all_thanks'] = Thanks.objects.all()[:20]

    return render_to_response(
        'home.html',
        params,
        context_instance=RequestContext(request),
    )


def thanks(request, openid, templatename=None, content_type=None):
    if templatename is None:
        templatename = 'thanks.html'
    if content_type is None:
        content_type = settings.DEFAULT_CONTENT_TYPE

    try:
        user = Person.objects.get(openid=openid)
    except Person.DoesNotExist:
        return HttpResponseNotFound('No such person %r' % openid,
            content_type='text/plain')

    return render_to_response(
        templatename,
        {
            'user': user,
            'pshub_url': settings.PSHUB_URL,
        },
        context_instance=RequestContext(request),
        mimetype=content_type,
    )


def single_thanks(request, ident):
    try:
        thanks = Thanks.objects.get(id=ident)
    except Thanks.DoesNotExist:
        return HttpResponseNotFound('No such thanks %r' % ident,
            content_type='text/plain')

    return render_to_response(
        'single_thanks.html',
        {
            'thanks': thanks,
        },
        context_instance=RequestContext(request),
    )


@auth_required
def save_thanks(request):
    log.debug('HI SESSIONS ARE AM %r', request.session)
    to_url = request.POST.get('person_to', None)
    message = request.POST.get('message', None)
    if not to_url or not message:
        if not to_url:
            request.flash.put(error='An OpenID to whom to send thanks is required.')
        if not message:
            request.flash.put(error='A message for thanks ')
        return home(request, {
            'person_to': to_url,
            'message': message,
        })

    # Is that really an OpenID?
    csr = consumer.Consumer({}, OpenIDStore())
    try:
        ar = csr.begin(to_url)
    except discover.DiscoveryFailure, exc:
        request.flash.put(error="That doesn't appear to be someone's OpenID: %s"
            % exc.message)
        return home(request, {
            'person_to': to_url,
            'message': message,
        })

    openid_url = ar.endpoint.claimed_id
    try:
        person_to = Person.objects.get(openid=openid_url)
    except Person.DoesNotExist:
        person_to = Person(openid=openid_url)
        person_to.name = OpenIDStore.default_name_for_url(openid_url)
        person_to.save()

    thanks = Thanks()
    thanks.person_from = request.user
    thanks.person_to = person_to
    thanks.message = message
    thanks.save()

    request.flash.put(message='Your thanks have been recorded!')

    # Tell the pubsub hub about it.
    activity_url = reverse('activity_feed',
        kwargs={'openid': request.user.openid})
    activity_url = request.build_absolute_uri(activity_url)
    publ_data = {
        'hub.mode': 'publish',
        'hub.url': activity_url,
    }
    h = httplib2.Http()
    try:
        resp, content = h.request(settings.PSHUB_URL, method='POST',
            body=urlencode(publ_data))
        if resp.status not in (200, 204):
            raise ValueError('%d %s: %s' % (resp.status, resp.reason,
                content if resp['content-type'].startswith('text/plain')
                    else resp['content-type']))
    except Exception, exc:
        request.flash.put(error='There was a %s telling the Internet about '
            'your new thanks: %s' % (type(exc).__name__, str(exc)))

    return HttpResponseRedirect(reverse('home'))


# OpenID views

@auth_forbidden
def signin(request, nexturl=None):
    return render_to_response(
        'signin.html',
        {},
        context_instance=RequestContext(request),
    )


@auth_required
def signout(request):
    del request.session['openid']
    del request.user
    return HttpResponseRedirect(reverse('home'))


@auth_forbidden
def start(request):
    openid_url = request.POST.get('openid_url', None)
    if not openid_url:
        request.flash.put(error="An OpenID as whom to sign in is required.")
        return HttpResponseRedirect(reverse('signin'))
    log.debug('Attempting to sign viewer in as %r', openid_url)

    csr = consumer.Consumer(request.session, OpenIDStore())
    try:
        ar = csr.begin(openid_url)
    except discover.DiscoveryFailure, exc:
        request.flash.put(error=exc.message)
        return HttpResponseRedirect(reverse('signin'))

    # Ask for some stuff by Simple Registration.
    ar.addExtension(sreg.SRegRequest(optional=('nickname', 'fullname', 'email')))

    # Ask for some stuff by Attribute Exchange.
    fr = ax.FetchRequest()
    fr.add(ax.AttrInfo("http://axschema.org/namePerson/first", alias='firstname', required=True))
    fr.add(ax.AttrInfo("http://axschema.org/namePerson/last", alias='lastname'))
    fr.add(ax.AttrInfo("http://axschema.org/contact/email", alias='email', required=True))
    fr.add(ax.AttrInfo("http://axschema.org/media/image/aspect11", alias='avatar'))
    fr.add(ax.AttrInfo("http://activitystrea.ms/axschema/callback", alias='callback', required=False)) # sound good?
    ar.addExtension(fr)

    def whole_reverse(view):
        return request.build_absolute_uri(reverse(view))

    return_to = whole_reverse('activity.views.complete')
    redirect_url = ar.redirectURL(whole_reverse('home'), return_to)
    return HttpResponseRedirect(redirect_url)


@auth_forbidden
def complete(request):
    csr = consumer.Consumer(request.session, OpenIDStore())
    resp = csr.complete(request.GET, request.build_absolute_uri())

    if isinstance(resp, consumer.CancelResponse):
        return HttpResponseRedirect(reverse('home'))

    elif isinstance(resp, consumer.FailureResponse):
        request.flash.put(error=resp.message)
        return HttpResponseRedirect(reverse('signin'))

    elif isinstance(resp, consumer.SuccessResponse):
        OpenIDStore.make_person_from_response(resp)
        request.session['openid'] = resp.identity_url

        # if the id provider returns an activity callback, 
        # we'll post the user's activity stream there
        fr = ax.FetchResponse.fromSuccessResponse(resp)
        if fr is not None:
            callback = fr.getSingle('http://activitystrea.ms/axschema/callback')
            if callback:
                log.debug("Posting user's activity feed back to %r", callback)

                # post the user's stream to the callback
                feed_url = reverse('activity_feed', kwargs={'openid': resp.identity_url})
                data = {
                    'feed_uri': request.build_absolute_uri(feed_url),
                }

                h = httplib2.Http()
                try:
                    resp, content = h.request(callback, method="POST", body=urlencode(data))
                except Exception, exc:
                    log.debug("From callback got %s: %s", type(exc).__name__, str(exc))
                else:
                    if resp['content-type'].startswith('text/plain'):
                        log.debug("From callback got %d %s response: %s", resp.status, resp.reason, content)
                    else:
                        log.debug("From callback got %d %s %s response", resp.status, resp.reason, resp['content-type'])
            else:
                log.debug("Callback was %r so not posting back", callback)
        else:
            log.debug("AX response was %r so not posting back", fr)

        return HttpResponseRedirect(reverse('home'))
