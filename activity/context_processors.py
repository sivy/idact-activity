import logging


log = logging.getLogger(__name__)


def request(request):
    return {'request': request}


def auth(request):
    user = getattr(request, 'user', None)
    return {} if user is None else {'user': user}
