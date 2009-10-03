import logging


log = logging.getLogger(__name__)


def auth(request):
    user = getattr(request, 'user', None)
    return {} if user is None else {'user': user}
