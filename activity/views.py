import logging

from django.core.urlresolvers import reverse
from django.http import HttpResponseRedirect
from django.shortcuts import render_to_response
from django.template import RequestContext
from openid.consumer import consumer, discover
from openid.extensions import sreg, ax

from activity.decorators import auth_forbidden, auth_required
from activity.models import Person, Thanks, OpenIDStore


log = logging.getLogger(__name__)


@auth_required
def home(request, params=None):
    return render_to_response(
        'home.html',
        {} if params is None else params,
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
    fr.add(ax.AttrInfo("http://schema.activitystrea.ms/activity/callback", alias='callback', required=False)) # sound good?
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
        return HttpResponseRedirect(reverse('home'))
