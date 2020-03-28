"""Errors."""


class ProxyError(Exception):
    pass


class NoProxyError(Exception):
    pass


class ResolveError(Exception):
    pass


class ProxyConnError(ProxyError):
    pass


class ProxyRecvError(ProxyError):  # connection_is_reset
    pass


class ProxySendError(ProxyError):  # connection_is_reset
    pass


class ProxyTimeoutError(ProxyError):
    pass


class ProxyEmptyResponseError(ProxyError):
    pass


class BadStatusError(Exception):  # BadStatusLine
    pass


class BadResponseError(Exception):
    pass


class BadStatusLine(Exception):
    pass


class ErrorOnStream(Exception):
    pass
