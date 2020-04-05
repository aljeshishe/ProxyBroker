import io
# import signal
import asyncio
import warnings
from pprint import pprint
from functools import partial
from collections import defaultdict, Counter

import aiostream

from .errors import ResolveError
from .proxy import Proxy
from .server import Server
from .checker import Checker
from .utils import log, IPPortPatternLine
from .resolver import Resolver
from .providers import Provider, get_providers

# Pause between grabbing cycles; in seconds.
GRAB_PAUSE = 180

# The maximum number of providers that are parsed concurrently
MAX_CONCURRENT_PROVIDERS = 10


class Broker:
    """The Broker.

    | One broker to rule them all, one broker to find them,
    | One broker to bring them all and in the darkness bind them.

    :param asyncio.Queue queue: (optional) Queue of found/checked proxies
    :param int timeout: (optional) Timeout of a request in seconds
    :param int max_conn:
        (optional) The maximum number of concurrent checks of proxies
    :param int max_tries:
        (optional) The maximum number of attempts to check a proxy
    :param list judges:
        (optional) Urls of pages that show HTTP headers and IP address.
        Or :class:`~proxybroker.judge.Judge` objects
    :param list providers:
        (optional) Urls of pages where to find proxies.
        Or :class:`~proxybroker.providers.Provider` objects
    :param bool verify_ssl:
        (optional) Flag indicating whether to check the SSL certificates.
        Set to True to check ssl certifications

    .. deprecated:: 0.2.0
        Use :attr:`max_conn` and :attr:`max_tries` instead of
        :attr:`max_concurrent_conn` and :attr:`attempts_conn`.
    """

    def __init__(self, queue=None, timeout=8, max_conn=200, max_tries=2,
                 judges=None, providers=None, verify_ssl=False, **kwargs):
        self._proxies = queue or asyncio.Queue()
        self._resolver = Resolver()
        self._timeout = timeout
        self._verify_ssl = verify_ssl

        self.unique_proxies = set()
        self._checker = None
        self._server = None
        self._limit = 0  # not limited
        self._countries = None
        self._stopped = False
        max_concurrent_conn = kwargs.get('max_concurrent_conn')
        if max_concurrent_conn:
            warnings.warn(
                '`max_concurrent_conn` is deprecated, use `max_conn` instead',
                DeprecationWarning)
            if isinstance(max_concurrent_conn, asyncio.Semaphore):
                max_conn = max_concurrent_conn._value
            else:
                max_conn = max_concurrent_conn

        attempts_conn = kwargs.get('attempts_conn')
        if attempts_conn:
            warnings.warn('`attempts_conn` is deprecated, use `max_tries` instead', DeprecationWarning)
            max_tries = attempts_conn

        # The maximum number of concurrent checking proxies
        self._on_check = asyncio.Queue(maxsize=max_conn)
        self._max_tries = max_tries
        self._judges = judges
        self._providers = [p if isinstance(p, Provider) else Provider(p)
                           for p in (providers or get_providers())]
        self._to_check = 0
        self._ok_proxies = 0
        # try:
        #     self._loop.add_signal_handler(signal.SIGINT, self.stop)
        #     # add_signal_handler() is not implemented on Win
        #     # https://docs.python.org/3.5/library/asyncio-eventloops.html#windows
        # except NotImplementedError:
        #     pass

    # async def grab(self, *, types=None, countries=None, limit=0):
    #     """Gather proxies from the providers without checking.
    #
    #     :param list types:
    #         Types (protocols) that need to be check on support by proxy.
    #         Supported: HTTP, HTTPS, SOCKS4, SOCKS5, CONNECT:80, CONNECT:25
    #         And levels of anonymity (HTTP only): Transparent, Anonymous, High
    #     :param list countries: (optional) List of ISO country codes
    #                            where should be located proxies
    #     :param int limit: (optional) The maximum number of proxies
    #
    #     :ref:`Example of usage <proxybroker-examples-grab>`.
    #     """
    #     self._countries = countries
    #     self._limit = limit
    #     types = _update_types(types)
    #     task = asyncio.ensure_future(self._grab(types=types, check=False))

    async def find(self, *, types=None, data=None, countries=None,
                   post=False, strict=False, dnsbl=None, limit=0, check=True, **kwargs):
        """Gather and check proxies from providers or from a passed data.

        :ref:`Example of usage <proxybroker-examples-find>`.

        :param list types:
            Types (protocols) that need to be check on support by proxy.
            Supported: HTTP, HTTPS, SOCKS4, SOCKS5, CONNECT:80, CONNECT:25
            And levels of anonymity (HTTP only): Transparent, Anonymous, High
        :param data:
            (optional) String or list with proxies. Also can be a file-like
            object supports `read()` method. Used instead of providers
        :param list countries:
            (optional) List of ISO country codes where should be located
            proxies
        :param bool post:
            (optional) Flag indicating use POST instead of GET for requests
            when checking proxies
        :param bool strict:
            (optional) Flag indicating that anonymity levels of types
            (protocols) supported by a proxy must be equal to the requested
            types and levels of anonymity. By default, strict mode is off and
            for a successful check is enough to satisfy any one of the
            requested types
        :param list dnsbl:
            (optional) Spam databases for proxy checking.
            `Wiki <https://en.wikipedia.org/wiki/DNSBL>`_
        :param int limit: (optional) The maximum number of proxies

        :raises ValueError:
            If :attr:`types` not given.

        .. versionchanged:: 0.2.0
            Added: :attr:`post`, :attr:`strict`, :attr:`dnsbl`.
            Changed: :attr:`types` is required.
        """
        ip = await self._resolver.get_real_ext_ip()
        types = _update_types(types)

        if not types:
            raise ValueError('`types` is required')

        self._checker = Checker(
            judges=self._judges, timeout=self._timeout,
            verify_ssl=self._verify_ssl, max_tries=self._max_tries,
            real_ext_ip=ip, types=types, post=post,
            strict=strict, dnsbl=dnsbl)
        self._countries = countries
        self._limit = limit

        await self._checker.check_judges()
        if data:
            await asyncio.ensure_future(self._load(data, check=check))
        else:
            await asyncio.ensure_future(self._grab(types, check=check))

    async def _load(self, data, check=True):
        """Looking for proxies in the passed data.

        Transform the passed data from [raw string | file-like object | list]
        to set {(host, port), ...}: {('192.168.0.1', '80'), }
        """
        log.debug('Load proxies from the raw data')
        if isinstance(data, io.TextIOWrapper):
            data = data.read()
        if isinstance(data, str):
            data = IPPortPatternLine.findall(data)
        proxies = set(data)
        for proxy in proxies:
            await self._handle(proxy, check=check)
        await self._on_check.join()
        self._done()

    async def _grab(self, types=None, check=False):
        try:
            while True:
                log.debug('Start grabbing proxies')
                generators = [pr.iter_proxies() for pr in self._providers if not types or not pr.proto or bool(pr.proto & types.keys())]
                combine = aiostream.stream.merge(*generators)
                async with combine.stream() as streamer:
                    async for proxies in streamer:
                        self._to_check += len(proxies)
                        for proxy in proxies:
                            await self._handle(proxy, check=check)
                            if self._stopped:
                                return
                    if self._server:
                        log.debug('fall asleep for %d seconds' % GRAB_PAUSE)
                        await asyncio.sleep(GRAB_PAUSE)
                        log.debug('awaked')
                    else:
                        break
            await self._on_check.join()
            self._done()
        except Exception as e:
            log.exception('Exception while grabbing proxies')
            raise

    async def _handle(self, proxy, check=False):
        try:
            proxy = Proxy(*proxy, timeout=self._timeout, verify_ssl=self._verify_ssl)

            if not self._is_unique(proxy) or not self._geo_passed(proxy):
                return

            if check:
                await self._push_to_check(proxy)
            else:
                self._push_to_result(proxy)

        except Exception as e:
            log.exception(f'Exception while checking proxy {proxy}')

    def _is_unique(self, proxy):
        if proxy.host_port in self.unique_proxies:
            proxy.log('Proxy already processed(possibly from other provider)')
            return False

        self.unique_proxies.add(proxy.host_port)
        return True

    def _geo_passed(self, proxy):
        if self._countries and (proxy.geo.code not in self._countries):
            proxy.log('Location of proxy is outside the given countries list')
            return False

        return True

    async def _push_to_check(self, proxy):
        def _task_done(proxy, f):
            self._to_check -= 1
            self._on_check.task_done()
            if not self._on_check.empty():
                self._on_check.get_nowait()
            try:
                if f.result():
                    # proxy is working and its types is equal to the requested
                    self._push_to_result(proxy)
            except asyncio.CancelledError:
                pass

        if self._server and not self._proxies.empty() and self._limit <= 0:
            log.debug('pause. proxies: %s; limit: %s' % (
                self._proxies.qsize(), self._limit))
            await self._proxies.join()
            log.debug('unpause. proxies: %s' % self._proxies.qsize())

        await self._on_check.put(None)
        task = asyncio.ensure_future(self._checker.check(proxy))
        task.add_done_callback(partial(_task_done, proxy))

    def _push_to_result(self, proxy):
        self._ok_proxies += 1
        log.info(f'_on_check:{self._on_check.qsize()}  _to_check:{self._to_check} unique:{len(self.unique_proxies)} '
                 f'ok:{self._ok_proxies} Found proxy {proxy} ')
        self._proxies.put_nowait(proxy)
        self._update_limit()

    def _update_limit(self):
        self._limit -= 1
        if self._limit == 0 and not self._server:
            self._done()

    def stop(self):
        """Stop all tasks, and the local proxy server if it's running."""
        self._done()
        if self._server:
            self._server.stop()
            self._server = None
        log.info('Stop!')

    def _done(self):
        for task in asyncio.all_tasks():
            task.cancel()
        self._push_to_result(None)
        self._stopped = True
        log.info('Finished!')

    def show_stats(self, verbose=False, **kwargs):
        """Show statistics on the found proxies.

        Useful for debugging, but you can also use if you're interested.

        :param verbose: Flag indicating whether to print verbose stats

        .. deprecated:: 0.2.0
            Use :attr:`verbose` instead of :attr:`full`.
        """
        if kwargs:
            verbose = True
            warnings.warn('`full` in `show_stats` is deprecated, '
                          'use `verbose` instead.', DeprecationWarning)

        # found_proxies = self.unique_proxies.values() # TODO unique_proxies is set now
        num_working_proxies = len([p for p in found_proxies if p.is_working])

        if not found_proxies:
            log.info('Proxy not found')
            return

        errors = Counter()
        for p in found_proxies:
            errors.update(p.stat['errors'])

        proxies_by_type = {'SOCKS5': [], 'SOCKS4': [], 'HTTPS': [], 'HTTP': [],
                           'CONNECT:80': [], 'CONNECT:25': []}

        stat = {'Wrong country': [],
                'Wrong protocol/anonymity lvl': [],
                'Connection success': [],
                'Connection timeout': [],
                'Connection failed': []}

        for p in found_proxies:
            msgs = ' '.join([l[1] for l in p.get_log()])
            full_log = [p, ]
            for proto in p.types:
                proxies_by_type[proto].append(p)
            if 'Location of proxy' in msgs:
                stat['Wrong country'].append(p)
            elif 'Connection: success' in msgs:
                if 'Protocol or the level' in msgs:
                    stat['Wrong protocol/anonymity lvl'].append(p)
                stat['Connection success'].append(p)
                if not verbose:
                    continue
                events_by_ngtr = defaultdict(list)
                for ngtr, event, runtime in p.get_log():
                    events_by_ngtr[ngtr].append((event, runtime))
                for ngtr, events in sorted(events_by_ngtr.items(),
                                           key=lambda item: item[0]):
                    full_log.append('\t%s' % ngtr)
                    for event, runtime in events:
                            full_log.append('\t\t{:<66} Runtime: {:.2f}'.format(event, runtime))
                for row in full_log:
                    log.info(row)
            elif 'Connection: failed' in msgs:
                stat['Connection failed'].append(p)
            else:
                stat['Connection timeout'].append(p)
        if verbose:
            log.info('Stats:')
            stream = io.StringIO()
            pprint(stat, stream)
            log.info(stream.read())

        log.info('The number of working proxies: %d' % num_working_proxies)
        for proto, proxies in proxies_by_type.items():
            log.info('%s (%s): %s' % (proto, len(proxies), proxies))
        log.info('Errors:', errors)


def _update_types(types):
    _types = {}
    if not types:
        return _types
    elif isinstance(types, dict):
        return types
    for tp in types:
        lvl = None
        if isinstance(tp, (list, tuple, set)):
            tp, lvl = tp[0], tp[1]
            if isinstance(lvl, str):
                lvl = lvl.split()
        _types[tp] = lvl
    return _types
