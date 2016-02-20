import json
import os
import time
from collections import OrderedDict

import pytz
from django.conf import settings
from django.core.urlresolvers import get_script_prefix
from django.http import HttpRequest, HttpResponse
from django.utils import timezone, translation
from django.utils.cache import patch_vary_headers
from django.utils.translation import LANGUAGE_SESSION_KEY
from django.utils.translation.trans_real import (
    check_for_language, get_supported_language_variant, language_code_re,
    parse_accept_lang_header,
)

_supported = None


class LocaleMiddleware:

    """
    This middleware sets the correct locale and timezone
    for a request.
    """

    def process_request(self, request: HttpRequest):
        language = get_language_from_request(request)
        if hasattr(request, 'event') and not request.path.startswith(get_script_prefix() + 'control'):
            if language not in request.event.settings.locales:
                firstpart = language.split('-')[0]
                if firstpart in request.event.settings.locales:
                    language = firstpart
                else:
                    language = request.event.settings.locale
                    for lang in request.event.settings.locales:
                        if lang.startswith(firstpart + '-'):
                            language = lang
                            break
        translation.activate(language)
        request.LANGUAGE_CODE = translation.get_language()

        tzname = None
        if request.user.is_authenticated():
            tzname = request.user.timezone
        if hasattr(request, 'event'):
            tzname = request.event.settings.timezone
        if tzname:
            try:
                timezone.activate(pytz.timezone(tzname))
                request.timezone = tzname
            except pytz.UnknownTimeZoneError:
                pass
        else:
            timezone.deactivate()

    def process_response(self, request: HttpRequest, response: HttpResponse):
        language = translation.get_language()
        patch_vary_headers(response, ('Accept-Language',))
        if 'Content-Language' not in response:
            response['Content-Language'] = language
        return response


def get_language_from_user_settings(request: HttpRequest) -> str:
    if request.user.is_authenticated():
        lang_code = request.user.locale
        if lang_code in _supported and lang_code is not None and check_for_language(lang_code):
            return lang_code


def get_language_from_session_or_cookie(request: HttpRequest) -> str:
    if hasattr(request, 'session'):
        lang_code = request.session.get(LANGUAGE_SESSION_KEY)
        if lang_code in _supported and lang_code is not None and check_for_language(lang_code):
            return lang_code

    lang_code = request.COOKIES.get(settings.LANGUAGE_COOKIE_NAME)
    try:
        return get_supported_language_variant(lang_code)
    except LookupError:
        pass


def get_language_from_event(request: HttpRequest) -> str:
    if hasattr(request, 'event'):
        lang_code = request.event.settings.locale
        try:
            return get_supported_language_variant(lang_code)
        except LookupError:
            pass


def get_language_from_browser(request: HttpRequest) -> str:
    accept = request.META.get('HTTP_ACCEPT_LANGUAGE', '')
    for accept_lang, unused in parse_accept_lang_header(accept):
        if accept_lang == '*':
            break

        if not language_code_re.search(accept_lang):
            continue

        try:
            return get_supported_language_variant(accept_lang)
        except LookupError:
            continue


def get_default_language():
    try:
        return get_supported_language_variant(settings.LANGUAGE_CODE)
    except LookupError:  # NOQA
        return settings.LANGUAGE_CODE


def get_language_from_request(request: HttpRequest) -> str:
    """
    Analyzes the request to find what language the user wants the system to
    show. Only languages listed in settings.LANGUAGES are taken into account.
    If the user requests a sublanguage where we have a main language, we send
    out the main language.
    """
    global _supported
    if _supported is None:
        _supported = OrderedDict(settings.LANGUAGES)

    return (
        get_language_from_user_settings(request)
        or get_language_from_session_or_cookie(request)
        or get_language_from_event(request)
        or get_language_from_browser(request)
        or get_default_language()
    )


class CProfileMiddleware:
    profdir = os.path.join(settings.DATA_DIR, 'profiles')

    def process_request(self, request):
        import cProfile
        request._starttime = time.time()
        self.profiler = cProfile.Profile()
        self.profiler.enable()

        if not os.path.exists(self.profdir):
            os.mkdir(self.profdir)

    def process_response(self, request, response):
        from django.db import connection

        self.profiler.disable()
        self.profiler.dump_stats(os.path.join(self.profdir, '%s_%d.pstat' % (request.path[1:].replace("/", "_"),
                                                                             time.time())))
        diff = time.time() - request._starttime
        response['X-View-Time'] = str(diff)
        response['X-Querycnt'] = len(connection.queries)
        return response
