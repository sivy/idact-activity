from django.conf.urls.defaults import *

urlpatterns = patterns('activity.views',
    url(r'^$', 'home', name='home'),
)


# URLs for OpenID views

urlpatterns += patterns('activity.views',
    url(r'^signin/start$', 'start'),
    url(r'^signin/complete$', 'complete'),
)
