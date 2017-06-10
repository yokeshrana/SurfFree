# -*- coding: utf-8 -*-
import re
import logging
import requests

from django.http import HttpResponse
from django.views.generic import View
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator

from utils.serializer import serialize_session, deserialize_session

logger = logging.getLogger(__name__)


REWRITE_REGEX = re.compile(r'((?:src|action|href)=["\'])/(?!\/)')


class DProxy(View):
    """
    Class-based view to configure Django Proxy for a URL pattern.

    In its most basic usage::

            from dproxy.views import DProxy

            urlpatterns += patterns('',
                (r'^my-proxy/(?P<url>.*)$',
                    DProxy.as_view(base_url='http://python.org/')),
            )

    Using the above configuration (and assuming your Django project is server by
    the Django development server on port 8000), a request to
    ``http://localhost:8000/my-proxy/index.html`` is proxied to
    ``http://python.org/index.html``.
    """

    base_url = None
    """
    The base URL that the proxy should forward requests to.
    """

    rewrite = False
    """
    If you configure the DProxy view on any non-root URL, the proxied
    responses may still contain references to resources as if they were served
    at the root. By setting this attribute to ``True``, the response will be
    :meth:`rewritten <dproxy.views.DProxy.rewrite_response>` to try to
    fix the paths.
    """

    @method_decorator(csrf_exempt)
    def dispatch(self, request, url, *args, **kwargs):
        self.url = url
        self.original_request_path = request.path
        request = self.normalize_request(request)
        response = super(DProxy, self).dispatch(request, *args, **kwargs)
        if self.rewrite:
            response = self.rewrite_response(request, response)
        return response

    def normalize_request(self, request):
        """
        Updates all path-related info in the original request object with the
        url given to the proxy.

        This way, any further processing of the proxy'd request can just ignore
        the url given to the proxy and use request.path safely instead.
        """
        if not self.url.startswith('/'):
            self.url = '/' + self.url
        request.path = self.url
        request.path_info = self.url
        request.META['PATH_INFO'] = self.url
        return request

    def rewrite_response(self, request, response):
        """
        Rewrites the response to fix references to resources loaded from HTML
        files (images, etc.).

        .. note::
            The rewrite logic uses a fairly simple regular expression to look for
            "src", "href" and "action" attributes with a value starting with "/"
            – your results may vary.
        """
        proxy_root = self.original_request_path.rsplit(request.path, 1)[0]
        response.content = REWRITE_REGEX.sub(r'\1{}/'.format(proxy_root), response.content)

        host = request.META['HTTP_HOST'].rstrip('/')
        response.content = response.content.replace(self.base_url.rstrip('/'), host)

        return response

    def get_session(self, request):
        if 'proxy' not in request.session:
            self.session = requests.Session()
        else:
            self.session = deserialize_session(request.session['proxy'])
        return self.session

    def save_session(self, request):
        request.session['proxy'] = serialize_session(self.session)

    def get_header(self, request):
        headers = dict()
        if 'HTTP_REFERER' in request.META:
            headers['Referer'] = self.raw_rewrite(request, request.META['HTTP_REFERER'])
        if 'HTTP_ORIGIN' in request.META:
            headers['Origin'] = self.raw_rewrite(request, request.META['HTTP_ORIGIN'])
        if 'HTTP_USER_AGENT' in request.META:
            headers['User-Agent'] = request.META['HTTP_USER_AGENT']
        if 'HTTP_X_REQUESTED_WITH' in request.META:
            headers['X-Requested-With'] = request.META['HTTP_X_REQUESTED_WITH']
        return headers

    def get(self, request, *args, **kwargs):
        self.get_session(request)
        request_url = self.get_full_url(self.url)
        headers = self.get_header(request)
        r = self.session.get(request_url, params=request.GET, headers=headers, allow_redirects=False)
        response_body = r.content
        status = r.status_code
        self.save_session(request)
        logger.info('"GET {}" {}'.format(self.url, status, len(response_body)))
        http_response = HttpResponse(response_body, status=status, content_type=r.headers['Content-Type'])
        if 'Location' in r.headers:
            http_response['Location'] = r.headers['Location']
        return http_response

    def raw_rewrite(self, request, content):
        if self.rewrite:
            host = request.META['HTTP_HOST']
            url = self.base_url.replace('http://', '').replace('https://', '').rstrip('/')
            return content.replace(host, url)
        return content

    def post(self, request, *args, **kwargs):
        self.get_session(request)
        request_url = self.get_full_url(self.url)
        headers = self.get_header(request)
        r = self.session.post(request_url, data=request.POST, headers=headers, allow_redirects=False)
        response_body = r.content
        status = r.status_code
        self.save_session(request)
        logger.info('"POST {}" {}'.format(self.url, status, len(response_body)))
        http_response = HttpResponse(response_body, status=status, content_type=r.headers['Content-Type'])
        if 'Location' in r.headers:
            http_response['Location'] = r.headers['Location']
        return http_response

    def get_full_url(self, url):
        """
        Constructs the full URL to be requested.
        """
        param_str = self.request.GET.urlencode()
        url = url.lstrip('/')
        request_url = u'%s/%s' % (self.base_url.lstrip(), url)
        request_url += '?%s' % param_str if param_str else ''
        return request_url
