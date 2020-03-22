"""
Copyright © 2015-2018 Constverum <constverum@gmail.com>. All rights reserved.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""
from asyncio.selector_events import _SelectorTransport

__title__ = 'ProxyBroker'
__package__ = 'proxybroker'
__version__ = '0.3.1'
__short_description__ = '[Finder/Checker/Server] Finds public proxies from multiple sources and concurrently checks them. Supports HTTP(S) and SOCKS4/5.'  # noqa
__author__ = 'Constverum'
__author_email__ = 'constverum@gmail.com'
__url__ = 'https://github.com/constverum/ProxyBroker'
__license__ = 'Apache License, Version 2.0'
__copyright__ = 'Copyright 2015-2018 Constverum'


from .proxy import Proxy  # noqa
from .judge import Judge  # noqa
from .providers import Provider  # noqa
from .checker import Checker  # noqa
from .server import Server, ProxyPool  # noqa
from .api import Broker  # noqa
from .requests import Requests
#
import logging  # noqa
import warnings  # noqa


logger = logging.getLogger('asyncio')
logger.setLevel(logging.INFO)
# logger.addFilter(logging.Filter('has no effect when using ssl'))
# disabled because hides "Task exception was never retrieved" message
warnings.simplefilter('always', UserWarning)
warnings.simplefilter('once', DeprecationWarning)
#

# _SelectorTransport.__del__ closes transport. This leads to exception
# OSError: [WinError 10038] An operation was attempted on something that is not a socket
# so don't close transport
def _del(self):
    if self._sock is not None:
        warnings.warn("unclosed transport %r. Ignoring" % self, ResourceWarning,
                      source=self)


_SelectorTransport.__del__ = _del

__all__ = (
    Proxy,
    Judge,
    Provider,
    Checker,
    Server,
    ProxyPool,
    Broker,
    Requests
)
