import logging

from django.core.urlresolvers import reverse
from django.http import HttpResponseRedirect
from openid.consumer import consumer, discover
from openid.extensions import sreg, ax

from activity.decorators import auth_forbidden
from activity.models import OpenIDStore


log = logging.getLogger(__name__)


# OpenID views

@auth_forbidden
def start(request):
    openid_url = request.POST.get('openid_url', None)
    if not openid_url:
        request.flash.put(loginerror="An OpenID as whom to sign in is required.")
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
