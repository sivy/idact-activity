from os.path import join, dirname

from django.conf.urls.defaults import *


urlpatterns = patterns('',
    url(r'^', include('activity.urls')),

    url(r'^static/(?P<path>.*)$', 'django.views.static.serve',
        {'document_root': join(dirname(__file__), 'static')},
        name='static'),
)
