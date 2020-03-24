import asyncio
import re
import warnings
from math import sqrt
from html import unescape
from base64 import b64decode
from urllib.parse import unquote, urlparse

import aiohttp

import async_timeout

from .errors import BadStatusError
from .utils import log, get_headers, IPPattern, IPPortPatternGlobal


class Provider:
    """Proxy provider.

    Provider - a website that publish free public proxy lists.

    :param str url: Url of page where to find proxies
    :param tuple proto:
        (optional) List of the types (protocols) that may be supported
        by proxies returned by the provider. Then used as :attr:`Proxy.types`
    :param int max_conn:
        (optional) The maximum number of concurrent connections on the provider
    :param int max_tries:
        (optional) The maximum number of attempts to receive response
    :param int timeout:
        (optional) Timeout of a request in seconds
    """

    _pattern = IPPortPatternGlobal

    def __init__(self, url=None, proto=(), max_conn=4,
                 max_tries=3, timeout=20):
        self.url = url
        self.proto = proto
        self._max_tries = max_tries
        self._timeout = timeout
        self._session = None
        self._cookies = {}
        # concurrent connections on the current provider
        self._sem_provider = asyncio.Semaphore(max_conn)

    def __str__(self):
        domain = urlparse(self.url).netloc
        return f'{self.__class__.__name__}({domain})'

    async def iter_proxies(self):
        """Receive proxies from the provider and return them.

        :return: :attr:`.proxies`
        """
        log.info(f'{self} started crawling proxies')
        async with aiohttp.ClientSession(headers=get_headers(),
                                         cookies=self._cookies) as self._session:
            async for proxies in self._pipe():
                yield [(*p, str(self)) for p in proxies]
        log.info(f'{self} finished crawling proxies')

    async def _pipe(self):
        yield await self._find_on_page(self.url)

    async def _find_on_page(self, url, data=None, headers=None, method='GET'):
        log.debug(f'{self} Trying to get proxies from {url}')
        received = []
        try:
            page = await self.get(url, data=data, headers=headers, method=method)
            received = self.find_proxies(page)
        except Exception as e:
            log.exception(f'Error getting proxies from {url}: {e}')
        log.debug(f'{self} {len(received)} proxies received from {url}: {received}')
        return received

    async def get(self, url, data=None, headers=None, method='GET'):
        for _ in range(self._max_tries):
            page = await self._get(url, data=data, headers=headers, method=method)
            if page:
                return page
        return None

    async def _get(self, url, data=None, headers=None, method='GET'):
        page = ''
        try:
            async with self._sem_provider, async_timeout.timeout(self._timeout):
                async with self._session.request(method, url, data=data, headers=headers) as resp:
                    page = await resp.text()
                    if resp.status != 200:
                        log.debug(f'{self} getting page from {url} returned {resp.status}\nheaders: {resp.headers}\n'
                                  f'cookies: {resp.cookies}\npage: \n{page:.1000s}%.1000s')
                        raise BadStatusError('Status: %s' % resp.status)
        except (UnicodeDecodeError, BadStatusError, asyncio.TimeoutError,
                aiohttp.ClientOSError, aiohttp.ClientResponseError,
                aiohttp.ServerDisconnectedError) as e:
            page = ''
            log.exception(f'{self} getting {url} page failed')
        return page

    def find_proxies(self, page):
        return self._pattern.findall(page)


class Freeproxylists_com(Provider):
    domain = 'freeproxylists.com'

    async def _pipe(self):
        exp = r'''href\s*=\s*['"](?P<t>[^'"]*)/(?P<uts>\d{10})[^'"]*['"]'''
        urls = ['http://www.freeproxylists.com/socks.html',
                'http://www.freeproxylists.com/elite.html',
                'http://www.freeproxylists.com/anonymous.html']
        pages = await asyncio.gather(*[self.get(url) for url in urls])
        params = re.findall(exp, ''.join(pages))
        # example: http://www.freeproxylists.com/load_socks_1448724717.html
        for t, uts in params:
            yield await self._find_on_page(f'http://www.freeproxylists.com/load_{t}_{uts}.html')


class Blogspot_com_base(Provider):
    _cookies = {'NCR': 1}

    async def _pipe(self):
        exp = r'''<a href\s*=\s*['"]([^'"]*\.\w+/\d{4}/\d{2}/[^'"#]*)['"]>'''
        pages = await asyncio.gather(*[self.get('http://%s/' % d) for d in self.domains])
        for url in re.findall(exp, ''.join(pages)):
            yield await self._find_on_page(url=url)


class Blogspot_com(Blogspot_com_base):
    domain = 'blogspot.com'
    domains = ['sslproxies24.blogspot.com', 'proxyserverlist-24.blogspot.com',
               # 'googleproxies24.blogspot.com'
               ]


class Blogspot_com_socks(Blogspot_com_base):
    domain = 'blogspot.com^socks'
    domains = ['www.socks24.org', ]


class Webanetlabs_net(Provider):
    domain = 'webanetlabs.net'

    async def _pipe(self):
        exp = r'''href\s*=\s*['"]([^'"]*proxylist_at_[^'"]*)['"]'''
        page = await self.get('https://webanetlabs.net/publ/24')
        for path in re.findall(exp, page):
            yield await self._find_on_page(url='https://webanetlabs.net%s' % path)


class Checkerproxy_net(Provider):
    domain = 'checkerproxy.net'

    async def _pipe(self):
        exp = r'''href\s*=\s*['"](/archive/\d{4}-\d{2}-\d{2})['"]'''
        page = await self.get('https://checkerproxy.net/')
        for path in re.findall(exp, page):
            yield await self._find_on_page(url='https://checkerproxy.net/api%s' % path)


class Proxz_com(Provider):
    domain = 'proxz.com'

    def find_proxies(self, page):
        return super().find_proxies(unquote(page))

    async def _pipe(self):
        exp = r'''href\s*=\s*['"]([^'"]?proxy_list_high_anonymous_[^'"]*)['"]'''  # noqa
        page = await self.get(url='http://www.proxz.com/proxy_list_high_anonymous_0.html')
        for path in re.findall(exp, page):
            yield await self._find_on_page(url='http://www.proxz.com/%s' % path)


class Proxy_list_org(Provider):
    domain = 'proxy-list.org'
    _pattern = re.compile(r'''Proxy\('([\w=]+)'\)''')

    def find_proxies(self, page):
        return [b64decode(hp).decode().split(':') for hp in super().find_proxies(page)]

    async def _pipe(self):
        exp = r'''href\s*=\s*['"]\./([^'"]?index\.php\?p=\d+[^'"]*)['"]'''
        page = await self.get('http://proxy-list.org/english/index.php?p=1')
        for path in re.findall(exp, page):
            yield await self._find_on_page(url='http://proxy-list.org/english/%s' % path)


class Aliveproxy_com(Provider):
    # more: http://www.aliveproxy.com/socks-list/socks5.aspx/United_States-us
    domain = 'aliveproxy.com'

    async def _pipe(self):
        paths = [
            'socks5-list', 'high-anonymity-proxy-list', 'anonymous-proxy-list',
            'fastest-proxies', 'us-proxy-list', 'gb-proxy-list',
            'fr-proxy-list', 'de-proxy-list', 'jp-proxy-list', 'ca-proxy-list',
            'ru-proxy-list', 'proxy-list-port-80', 'proxy-list-port-81',
            'proxy-list-port-3128', 'proxy-list-port-8000',
            'proxy-list-port-8080']
        for path in paths:
            yield await self._find_on_page(url='http://www.aliveproxy.com/%s/' % path)


# редиректит хуй поми кудаъ
class Maxiproxies_com(Provider):
    domain = 'maxiproxies.com'

    async def _pipe(self):
        exp = r'''<a href\s*=\s*['"]([^'"]*example[^'"#]*)['"]>'''
        page = await self.get('http://maxiproxies.com/category/proxy-lists/')
        urls = re.findall(exp, page)
        for url in urls:
            yield await self._find_on_page(url=url)


class _50kproxies_com(Provider):
    domain = '50kproxies.com'

    async def _pipe(self):
        exp = r'''<a href\s*=\s*['"]([^'"]*-proxy-list-[^'"#]*)['"]>'''
        page = await self.get('http://50kproxies.com/category/proxy-list/')
        urls = re.findall(exp, page)
        for url in urls:
            yield await self._find_on_page(url=url)


class Proxylist_me(Provider):
    domain = 'proxylist.me'

    async def _pipe(self):
        exp = r'''href\s*=\s*['"][^'"]*/?page=(\d+)['"]'''
        page = await self.get('https://proxylist.me/')
        # TODO uncomment
        # lastId = max([int(n) for n in re.findall(exp, page)])
        lastId = 10
        for n in range(lastId):
            yield await self._find_on_page(url='https://proxylist.me/?page=%d' % n)


class Foxtools_ru(Provider):
    domain = 'foxtools.ru'

    async def _pipe(self):
        for n in range(1, 6):
            yield await self._find_on_page(url='http://api.foxtools.ru/v2/Proxy.txt?page=%d' % n)


class Gatherproxy_com(Provider):
    domain = 'gatherproxy.com'
    _pattern_h = re.compile(
        r'''(?P<ip>(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?))'''  # noqa
        r'''(?=.*?(?:(?:(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?))|'(?P<port>[\d\w]+)'))''',  # noqa
        flags=re.DOTALL)

    def find_proxies(self, page):
        # if 'gp.dep' in page:
        #     proxies = self._pattern_h.findall(page)  # for http(s)
        #     proxies = [(host, str(int(port, 16)))
        #                for host, port in proxies if port]
        # else:
        #     proxies = self._find_proxies(page)  # for socks
        return [(host, str(int(port, 16)))
                for host, port in self._pattern_h.findall(page) if port]

    async def _pipe(self):
        # TODO works incorrectly
        url = 'https://proxygather.com/proxylist/anonymity/?t=Elite'
        expNumPages = r'href="#(\d+)"'
        method = 'POST'
        # hdrs = {'Content-Type': 'application/x-www-form-urlencoded'}
        urls = []
        for t in ['anonymous', 'elite']:
            data = {'Type': t, 'PageIdx': 1}
            page = await self.get(url, data=data, method=method)
            if not page:
                continue
            lastPageId = max([int(n) for n in re.findall(expNumPages, page)])
            for pid in range(1, lastPageId + 1):
                yield await self._find_on_page(url=url, data={'Type': t, 'PageIdx': pid}, method=method)
        # urls.append({'url': 'http://www.gatherproxy.com/sockslist/',
        #              'method': method})


class Gatherproxy_com_socks(Provider):
    domain = 'gatherproxy.com^socks'

    async def _pipe(self):
        yield await self._find_on_page(url='http://www.gatherproxy.com/sockslist/', method='POST')


class Tools_rosinstrument_com_base(Provider):
    # more: http://tools.rosinstrument.com/cgi-bin/
    #       sps.pl?pattern=month-1&max=50&nskip=0&file=proxlog.csv
    domain = 'tools.rosinstrument.com'
    sqrtPattern = re.compile(r'''sqrt\((\d+)\)''')
    bodyPattern = re.compile(r'''hideTxt\(\n*'(.*)'\);''')
    _pattern = re.compile(
        r'''(?:(?P<domainOrIP>(?:[a-z0-9\-.]+\.[a-z]{2,6})|'''
        r'''(?:(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}'''
        r'''(?:25[0-5]|2[0-4]\d|[01]?\d\d?))))(?=.*?(?:(?:'''
        r'''[a-z0-9\-.]+\.[a-z]{2,6})|(?:(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)'''
        r'''\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?))|(?P<port>\d{2,5})))''',
        flags=re.DOTALL)

    def find_proxies(self, page):
        x = self.sqrtPattern.findall(page)
        if not x:
            return []
        x = round(sqrt(float(x[0])))
        hiddenBody = self.bodyPattern.findall(page)[0]
        hiddenBody = unquote(hiddenBody)
        toCharCodes = [ord(char) ^ (x if i % 2 else 0)
                       for i, char in enumerate(hiddenBody)]
        fromCharCodes = ''.join([chr(n) for n in toCharCodes])
        page = unescape(fromCharCodes)
        return super().find_proxies(page)


class Tools_rosinstrument_com(Tools_rosinstrument_com_base):
    domain = 'tools.rosinstrument.com'

    async def _pipe(self):
        tpl = 'http://tools.rosinstrument.com/raw_free_db.htm?%d&t=%d'
        for pid in range(51):
            for t in range(1, 3):
                yield await self._find_on_page(url=tpl % (pid, t))


class Tools_rosinstrument_com_socks(Tools_rosinstrument_com_base):
    domain = 'tools.rosinstrument.com^socks'

    async def _pipe(self):
        tpl = 'http://tools.rosinstrument.com/raw_free_db.htm?%d&t=3'
        for pid in range(51):
            yield await self._find_on_page(url=tpl % pid)


class Xseo_in(Provider):
    domain = 'xseo.in'
    charEqNum = {}

    def char_js_port_to_num(self, matchobj):
        chars = matchobj.groups()[0]
        num = ''.join([self.charEqNum[ch] for ch in chars if ch != '+'])
        return num

    def find_proxies(self, page):
        expPortOnJS = r'\(""\+(?P<chars>[a-z+]+)\)'
        expCharNum = r'\b(?P<char>[a-z])=(?P<num>\d);'
        self.charEqNum = {char: i for char, i in re.findall(expCharNum, page)}
        page = re.sub(expPortOnJS, self.char_js_port_to_num, page)
        return super().find_proxies(page)

    async def _pipe(self):
        yield await self._find_on_page(url='http://xseo.in/proxylist', data={'submit': 1}, method='POST')


class Nntime_com(Provider):
    domain = 'nntime.com'
    charEqNum = {}
    _pattern = re.compile(
        r'''\b(?P<ip>(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}'''
        r'''(?:25[0-5]|2[0-4]\d|[01]?\d\d?))(?=.*?(?:(?:(?:(?:25'''
        r'''[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)'''
        r''')|(?P<port>\d{2,5})))''',
        flags=re.DOTALL)

    def char_js_port_to_num(self, matchobj):
        chars = matchobj.groups()[0]
        num = ''.join([self.charEqNum[ch] for ch in chars if ch != '+'])
        return num

    def find_proxies(self, page):
        expPortOnJS = r'\(":"\+(?P<chars>[a-z+]+)\)'
        expCharNum = r'\b(?P<char>[a-z])=(?P<num>\d);'
        self.charEqNum = {char: i for char, i in re.findall(expCharNum, page)}
        page = re.sub(expPortOnJS, self.char_js_port_to_num, page)
        return super().find_proxies(page)

    async def _pipe(self):
        tpl = 'http://www.nntime.com/proxy-updated-{:02}.htm'
        for n in range(1, 31):
            yield await self._find_on_page(url=tpl.format(n))


class Proxynova_com(Provider):
    domain = 'proxynova.com'

    async def _pipe(self):
        expCountries = r'"([a-z]{2})"'
        page = await self.get('https://www.proxynova.com/proxy-server-list/')
        tpl = 'https://www.proxynova.com/proxy-server-list/country-%s/'
        for isoCode in re.findall(expCountries, page):
            if isoCode != 'en':
                yield await self._find_on_page(url=tpl % isoCode)


class Spys_ru(Provider):
    domain = 'spys.ru'
    charEqNum = {}

    def char_js_port_to_num(self, matchobj):
        chars = matchobj.groups()[0].split('+')
        # ex: '+(i9w3m3^k1y5)+(g7g7g7^v2e5)+(d4r8o5^i9u1)+(y5c3e5^t0z6)'
        # => ['', '(i9w3m3^k1y5)', '(g7g7g7^v2e5)',
        #     '(d4r8o5^i9u1)', '(y5c3e5^t0z6)']
        # => ['i9w3m3', 'k1y5'] => int^int
        num = ''
        for numOfChars in chars[1:]:  # first - is ''
            var1, var2 = numOfChars.strip('()').split('^')
            digit = self.charEqNum[var1] ^ self.charEqNum[var2]
            num += str(digit)
        return num

    def find_proxies(self, page):
        expPortOnJS = r'(?P<js_port_code>(?:\+\([a-z0-9^+]+\))+)'
        # expCharNum = r'\b(?P<char>[a-z\d]+)=(?P<num>[a-z\d\^]+);'
        expCharNum = r'[>;]{1}(?P<char>[a-z\d]{4,})=(?P<num>[a-z\d\^]+)'
        # self.charEqNum = {
        #     char: i for char, i in re.findall(expCharNum, page)}
        res = re.findall(expCharNum, page)
        for char, num in res:
            if '^' in num:
                digit, tochar = num.split('^')
                num = int(digit) ^ self.charEqNum[tochar]
            self.charEqNum[char] = int(num)
        page = re.sub(expPortOnJS, self.char_js_port_to_num, page)
        return super().find_proxies(page)

    async def _pipe(self):
        expSession = r"'([a-z0-9]{32})'"
        url = 'http://spys.one/proxies/'
        page = await self.get(url)
        sessionId = re.findall(expSession, page)[0]
        data = {'xf0': sessionId,  # session id
                'xpp': 3,          # 3 - 200 proxies on page
                'xf1': None}       # 1 = ANM & HIA; 3 = ANM; 4 = HIA
        for lvl in [3, 4]:
            yield await self._find_on_page(url=url, data={**data, 'xf1': lvl}, method='POST')

        # expCountries = r'>([A-Z]{2})<'
        # url = 'http://spys.ru/proxys/'
        # page = await self.get(url)
        # links = ['http://spys.ru/proxys/%s/' %
        #          isoCode for isoCode in re.findall(expCountries, page)]


class My_proxy_com(Provider):
    domain = 'my-proxy.com'

    async def _pipe(self):
        exp = r'''href\s*=\s*['"]([^'"]?free-[^'"]*)['"]'''
        url = 'https://www.my-proxy.com/free-proxy-list.html'
        page = await self.get(url)
        for path in re.findall(exp, page):
            yield await self._find_on_page(url='https://www.my-proxy.com/%s' % path)


class Free_proxy_cz(Provider):
    domain = 'free-proxy.cz'
    _pattern = re.compile(
        r'''decode\("([\w=]+)".*?\("([\w=]+)"\)''', flags=re.DOTALL)

    def find_proxies(self, page):
        return [(b64decode(h).decode(), b64decode(p).decode())
                for h, p in super().find_proxies(page)]

    async def _pipe(self):
        tpl = 'http://free-proxy.cz/en/proxylist/main/date/%d'
        for n in range(1, 15):
            yield await self._find_on_page(url=tpl % n)

        # _urls = []
        # for url in urls:
        #     if len(_urls) == 15:
        #         await self._find_on_pages(_urls)
        #         print('sleeping on 61 sec')
        #         await asyncio.sleep(61)
        #         _urls = []
        #     _urls.append(url)
        # =========
        # expNumPages = r'href="/en/proxylist/main/(\d+)"'
        # page = await self.get('http://free-proxy.cz/en/')
        # if not page:
        #     return
        # lastPageId = max([int(n) for n in re.findall(expNumPages, page)])
        # tpl = 'http://free-proxy.cz/en/proxylist/main/date/%d'
        # urls = [tpl % pid for pid in range(1, lastPageId+1)]
        # _urls = []
        # for url in urls:
        #     if len(_urls) == 15:
        #         await self._find_on_pages(_urls)
        #         print('sleeping on 61 sec')
        #         await asyncio.sleep(61)
        #         _urls = []
        #     _urls.append(url)


class Proxyb_net(Provider):
    domain = 'proxyb.net'
    _port_pattern_b64 = re.compile(r"stats\('([\w=]+)'\)")
    _port_pattern = re.compile(r"':(\d+)'")

    def find_proxies(self, page):
        if not page:
            return []
        _hosts, _ports = page.split('","ports":"')
        hosts, ports = [], []
        for host in _hosts.split('<\/tr><tr>'):
            host = IPPattern.findall(host)
            if not host:
                continue
            hosts.append(host[0])
        ports = [self._port_pattern.findall(b64decode(port).decode())[0]
                 for port in self._port_pattern_b64.findall(_ports)]
        return [(host, port) for host, port in zip(hosts, ports)]

    async def _pipe(self):
        for p in range(0, 151):
            yield await self._find_on_page(url='http://proxyb.net/ajax.php',
                                           data={'action': 'getProxy',
                                                 'p': p,
                                                 'page': '/anonimnye_proksi_besplatno.html'},
                                           method='POST',
                                           headers={'X-Requested-With': 'XMLHttpRequest'})


class Proxylistplus_com(Provider):
    domain = 'list.proxylistplus.com'

    async def _pipe(self):
        names = ['Fresh-HTTP-Proxy', 'SSL', 'Socks']
        for i in names:
            for n in range(1, 7):
                yield await self._find_on_page(url='http://list.proxylistplus.com/%s-List-%d' % (i, n))


def get_providers():
    PROVIDERS = [
    Provider(url='http://www.proxylists.net/',
             proto=('HTTP', 'CONNECT:80', 'HTTPS', 'CONNECT:25')),  # 49
    Provider(url='http://ipaddress.com/proxy-list/',
             proto=('HTTP', 'CONNECT:80', 'HTTPS', 'CONNECT:25')),  # 53
    # Provider(url='https://www.sslproxies.org/',
    #          proto=('HTTP', 'CONNECT:80', 'HTTPS', 'CONNECT:25')),  # 100
    # Provider(url='https://freshfreeproxylist.wordpress.com/',
    #          proto=('HTTP', 'CONNECT:80', 'HTTPS', 'CONNECT:25')),  # 50
    # Provider(url='https://free-proxy-list.net/',
    #          proto=('HTTP', 'CONNECT:80', 'HTTPS', 'CONNECT:25')),  # 300
    # Provider(url='https://us-proxy.org/',
    #          proto=('HTTP', 'CONNECT:80', 'HTTPS', 'CONNECT:25')),  # 200
    # Provider(url='http://fineproxy.org/eng/fresh-proxies/',
    #          proto=('HTTP', 'CONNECT:80', 'HTTPS', 'CONNECT:25')),  # 5500
    # Provider(url='https://socks-proxy.net/',
    #          proto=('SOCKS4', 'SOCKS5')),                           # 80
    # Provider(url='http://www.httptunnel.ge/ProxyListForFree.aspx',
    #          proto=('HTTP', 'CONNECT:80', 'HTTPS', 'CONNECT:25')),  # 200
    # Provider(url='http://cn-proxy.com/',
    #          proto=('HTTP', 'CONNECT:80', 'HTTPS', 'CONNECT:25')),  # 70
    # Provider(url='http://pubproxy.com/api/proxy?limit=20&format=txt',
    #          proto=('HTTP', 'CONNECT:80', 'HTTPS', 'CONNECT:25')),  # 20
    # Xseo_in(proto=('HTTP', 'CONNECT:80', 'HTTPS', 'CONNECT:25')),                  # noqa; 240
    # Spys_ru(proto=('HTTP', 'CONNECT:80', 'HTTPS', 'CONNECT:25')),                  # noqa; 660
    # Foxtools_ru(proto=('HTTP', 'CONNECT:80', 'HTTPS', 'CONNECT:25'), max_conn=1),  # noqa; 500
    # Tools_rosinstrument_com(proto=('HTTP', 'CONNECT:80', 'HTTPS', 'CONNECT:25')),  # noqa; 4000
    # Tools_rosinstrument_com_socks(proto=('SOCKS4', 'SOCKS5')),                     # noqa; 1800
    # My_proxy_com(max_conn=2),                                                      # noqa; 1000
    # Checkerproxy_net(),                                                            # noqa; 60000
    # Aliveproxy_com(),                                                              # noqa; 210
    # Freeproxylists_com(),                                                          # noqa; 1338
    # Webanetlabs_net(),                                                             # noqa; 5000
    # Nntime_com(proto=('HTTP', 'CONNECT:80', 'HTTPS', 'CONNECT:25')),               # noqa; 1050
    # Blogspot_com(proto=('HTTP', 'CONNECT:80', 'HTTPS', 'CONNECT:25')),             # noqa; 24800
    # Blogspot_com_socks(proto=('SOCKS4', 'SOCKS5')),                                # noqa; 1486
    # Gatherproxy_com(proto=('HTTP', 'CONNECT:80', 'HTTPS', 'CONNECT:25')),          # noqa; 3212
    # Gatherproxy_com_socks(proto=('SOCKS4', 'SOCKS5')),                             # noqa; 30
    # Proxylist_me(proto=('HTTP', 'CONNECT:80', 'HTTPS', 'CONNECT:25')),             # noqa; 2872
    # Proxylistplus_com(proto=('HTTP', 'CONNECT:80', 'HTTPS', 'CONNECT:25')),        # noqa; 450
    # Proxy_list_org(proto=('HTTP', 'CONNECT:80', 'HTTPS', 'CONNECT:25')),           # noqa; 140
    # Bad...
    # Provider(url='https://hugeproxies.com/home/',
    #          proto=('HTTP', 'CONNECT:80', 'HTTPS', 'CONNECT:25')),  # 800
    # Provider(url='http://proxy.rufey.ru/',
    #          proto=('HTTP', 'CONNECT:80', 'HTTPS', 'CONNECT:25')),  # 153
    # Maxiproxies_com(),                                                             # noqa; 430
    # Provider(url='https://geekelectronics.org/my-servisy/proxy',
    #          proto=('HTTP', 'CONNECT:80', 'HTTPS', 'CONNECT:25')),  # 400
    # Provider(url='http://proxytime.ru/http',
    #          proto=('HTTP', 'CONNECT:80', 'HTTPS', 'CONNECT:25')),  # 1400
    # http://www.proxylist.ro/
    # Provider(url='http://proxydb.net/',
    #          proto=('HTTP', 'CONNECT:80', 'HTTPS',
    #                'CONNECT:25', 'SOCKS4', 'SOCKS5')),
    # Provider(url='http://www.cybersyndrome.net/pla6.html',
    #          proto=('HTTP', 'CONNECT:80', 'HTTPS', 'CONNECT:25')),  # 1100
    # Provider(url='https://www.ip-adress.com/proxy-list',
    #          proto=('HTTP', 'CONNECT:80', 'HTTPS', 'CONNECT:25')),  # 57
    # Provider(url='https://www.marcosbl.com/lab/proxies/',
    #          proto=('HTTP', 'CONNECT:80', 'HTTPS', 'CONNECT:25')),  # 89
    # Provider(url='http://go4free.xyz/Free-Proxy/',
    #          proto=('HTTP', 'CONNECT:80', 'HTTPS', 'CONNECT:25')),  # 196
    # Provider(url='http://blackstarsecurity.com/proxy-list.txt'),  # 7014
    # Provider(url='http://www.get-proxy.net/proxy-archives'),  # 519
    # Proxyb_net(proto=('HTTP', 'CONNECT:80', 'HTTPS', 'CONNECT:25')), # 857
    # Proxz_com(proto=('HTTP', 'CONNECT:80', 'HTTPS', 'CONNECT:25'),
    #           max_conn=2), # 443
    # Proxynova_com(proto=('HTTP', 'CONNECT:80', 'HTTPS', 'CONNECT:25')), # 818
    # _50kproxies_com(),  # 822
    # Free_proxy_cz(),  # 420
    ]
    return PROVIDERS
