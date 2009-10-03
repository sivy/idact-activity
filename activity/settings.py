from __future__ import absolute_import

from settings import *

TEMPLATE_CONTEXT_PROCESSORS = (
    'django.core.context_processors.debug',
    'django.core.context_processors.i18n',
    'django.core.context_processors.media',
    'djangoflash.context_processors.flash',
)

MIDDLEWARE_CLASSES = MIDDLEWARE_CLASSES + (
    'activity.middleware.AuthenticationMiddleware',
)


import logging
logging.basicConfig(level=logging.DEBUG)
