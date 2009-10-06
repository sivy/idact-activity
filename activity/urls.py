from django.conf.urls.defaults import *

urlpatterns = patterns('activity.views',
    url(r'^$', 'home', name='home'),
    url(r'^save_thanks$', 'save_thanks'),
    url(r'^thank/(?P<ident>.*)$', 'single_thanks', name="single_thanks"),
    url(r'^thanks/(?P<openid>.*)$', 'thanks', name="thanks"),
    url(r'^feed/(?P<openid>.*)$', 'thanks',
        {'templatename': 'thanks_feed.xml',
         'content_type': 'application/atom+xml'}),
)


# URLs for OpenID views

urlpatterns += patterns('activity.views',
    url(r'^signin$',  'signin',  name="signin"),
    url(r'^signin/start$', 'start'),
    url(r'^signin/complete$', 'complete'),
    url(r'^signout$', 'signout', name="signout"),
)
