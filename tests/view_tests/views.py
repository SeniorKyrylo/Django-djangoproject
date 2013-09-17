from __future__ import unicode_literals

import os
import sys

from django.core.exceptions import PermissionDenied, SuspiciousOperation
from django.core.urlresolvers import get_resolver
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import render_to_response, render
from django.template import Context, RequestContext, TemplateDoesNotExist
from django.views.debug import technical_500_response, SafeExceptionReporterFilter
from django.views.decorators.debug import (sensitive_post_parameters,
                                           sensitive_variables)
from django.utils._os import upath
from django.utils.log import getLogger

from . import BrokenException, except_args

dirs = (os.path.join(os.path.dirname(upath(__file__)), 'other_templates'),)


def index_page(request):
    """Dummy index page"""
    return HttpResponse('<html><body>Dummy page</body></html>')

def raises(request):
    # Make sure that a callable that raises an exception in the stack frame's
    # local vars won't hijack the technical 500 response. See:
    # http://code.djangoproject.com/ticket/15025
    def callable():
        raise Exception
    try:
        raise Exception
    except Exception:
        return technical_500_response(request, *sys.exc_info())

def raises500(request):
    # We need to inspect the HTML generated by the fancy 500 debug view but
    # the test client ignores it, so we send it explicitly.
    try:
        raise Exception
    except Exception:
        return technical_500_response(request, *sys.exc_info())

def raises400(request):
    raise SuspiciousOperation

def raises403(request):
    raise PermissionDenied

def raises404(request):
    resolver = get_resolver(None)
    resolver.resolve('')

def redirect(request):
    """
    Forces an HTTP redirect.
    """
    return HttpResponseRedirect("target/")

def view_exception(request, n):
    raise BrokenException(except_args[int(n)])

def template_exception(request, n):
    return render_to_response('debug/template_exception.html',
        {'arg': except_args[int(n)]})

def jsi18n(request):
    return render_to_response('jsi18n.html')

# Some views to exercise the shortcuts

def render_to_response_view(request):
    return render_to_response('debug/render_test.html', {
        'foo': 'FOO',
        'bar': 'BAR',
    })

def render_to_response_view_with_request_context(request):
    return render_to_response('debug/render_test.html', {
        'foo': 'FOO',
        'bar': 'BAR',
    }, context_instance=RequestContext(request))

def render_to_response_view_with_content_type(request):
    return render_to_response('debug/render_test.html', {
        'foo': 'FOO',
        'bar': 'BAR',
    }, content_type='application/x-rendertest')

def render_to_response_view_with_dirs(request):
    return render_to_response('render_dirs_test.html', dirs=dirs)

def render_view(request):
    return render(request, 'debug/render_test.html', {
        'foo': 'FOO',
        'bar': 'BAR',
    })

def render_view_with_base_context(request):
    return render(request, 'debug/render_test.html', {
        'foo': 'FOO',
        'bar': 'BAR',
    }, context_instance=Context())

def render_view_with_content_type(request):
    return render(request, 'debug/render_test.html', {
        'foo': 'FOO',
        'bar': 'BAR',
    }, content_type='application/x-rendertest')

def render_view_with_status(request):
    return render(request, 'debug/render_test.html', {
        'foo': 'FOO',
        'bar': 'BAR',
    }, status=403)

def render_view_with_current_app(request):
    return render(request, 'debug/render_test.html', {
        'foo': 'FOO',
        'bar': 'BAR',
    }, current_app="foobar_app")

def render_view_with_current_app_conflict(request):
    # This should fail because we don't passing both a current_app and
    # context_instance:
    return render(request, 'debug/render_test.html', {
        'foo': 'FOO',
        'bar': 'BAR',
    }, current_app="foobar_app", context_instance=RequestContext(request))

def render_with_dirs(request):
    return render(request, 'render_dirs_test.html', dirs=dirs)

def raises_template_does_not_exist(request, path='i_dont_exist.html'):
    # We need to inspect the HTML generated by the fancy 500 debug view but
    # the test client ignores it, so we send it explicitly.
    try:
        return render_to_response(path)
    except TemplateDoesNotExist:
        return technical_500_response(request, *sys.exc_info())

def render_no_template(request):
    # If we do not specify a template, we need to make sure the debug
    # view doesn't blow up.
    return render(request, [], {})

def send_log(request, exc_info):
    logger = getLogger('django.request')
    # The default logging config has a logging filter to ensure admin emails are
    # only sent with DEBUG=False, but since someone might choose to remove that
    # filter, we still want to be able to test the behavior of error emails
    # with DEBUG=True. So we need to remove the filter temporarily.
    admin_email_handler = [
        h for h in logger.handlers
        if h.__class__.__name__ == "AdminEmailHandler"
        ][0]
    orig_filters = admin_email_handler.filters
    admin_email_handler.filters = []
    admin_email_handler.include_html = True
    logger.error('Internal Server Error: %s', request.path,
        exc_info=exc_info,
        extra={
            'status_code': 500,
            'request': request
        }
    )
    admin_email_handler.filters = orig_filters

def non_sensitive_view(request):
    # Do not just use plain strings for the variables' values in the code
    # so that the tests don't return false positives when the function's source
    # is displayed in the exception report.
    cooked_eggs = ''.join(['s', 'c', 'r', 'a', 'm', 'b', 'l', 'e', 'd'])
    sauce = ''.join(['w', 'o', 'r', 'c', 'e', 's', 't', 'e', 'r', 's', 'h', 'i', 'r', 'e'])
    try:
        raise Exception
    except Exception:
        exc_info = sys.exc_info()
        send_log(request, exc_info)
        return technical_500_response(request, *exc_info)

@sensitive_variables('sauce')
@sensitive_post_parameters('bacon-key', 'sausage-key')
def sensitive_view(request):
    # Do not just use plain strings for the variables' values in the code
    # so that the tests don't return false positives when the function's source
    # is displayed in the exception report.
    cooked_eggs = ''.join(['s', 'c', 'r', 'a', 'm', 'b', 'l', 'e', 'd'])
    sauce = ''.join(['w', 'o', 'r', 'c', 'e', 's', 't', 'e', 'r', 's', 'h', 'i', 'r', 'e'])
    try:
        raise Exception
    except Exception:
        exc_info = sys.exc_info()
        send_log(request, exc_info)
        return technical_500_response(request, *exc_info)

@sensitive_variables()
@sensitive_post_parameters()
def paranoid_view(request):
    # Do not just use plain strings for the variables' values in the code
    # so that the tests don't return false positives when the function's source
    # is displayed in the exception report.
    cooked_eggs = ''.join(['s', 'c', 'r', 'a', 'm', 'b', 'l', 'e', 'd'])
    sauce = ''.join(['w', 'o', 'r', 'c', 'e', 's', 't', 'e', 'r', 's', 'h', 'i', 'r', 'e'])
    try:
        raise Exception
    except Exception:
        exc_info = sys.exc_info()
        send_log(request, exc_info)
        return technical_500_response(request, *exc_info)

def sensitive_args_function_caller(request):
    try:
        sensitive_args_function(''.join(['w', 'o', 'r', 'c', 'e', 's', 't', 'e', 'r', 's', 'h', 'i', 'r', 'e']))
    except Exception:
        exc_info = sys.exc_info()
        send_log(request, exc_info)
        return technical_500_response(request, *exc_info)

@sensitive_variables('sauce')
def sensitive_args_function(sauce):
    # Do not just use plain strings for the variables' values in the code
    # so that the tests don't return false positives when the function's source
    # is displayed in the exception report.
    cooked_eggs = ''.join(['s', 'c', 'r', 'a', 'm', 'b', 'l', 'e', 'd'])
    raise Exception

def sensitive_kwargs_function_caller(request):
    try:
        sensitive_kwargs_function(''.join(['w', 'o', 'r', 'c', 'e', 's', 't', 'e', 'r', 's', 'h', 'i', 'r', 'e']))
    except Exception:
        exc_info = sys.exc_info()
        send_log(request, exc_info)
        return technical_500_response(request, *exc_info)

@sensitive_variables('sauce')
def sensitive_kwargs_function(sauce=None):
    # Do not just use plain strings for the variables' values in the code
    # so that the tests don't return false positives when the function's source
    # is displayed in the exception report.
    cooked_eggs = ''.join(['s', 'c', 'r', 'a', 'm', 'b', 'l', 'e', 'd'])
    raise Exception

class UnsafeExceptionReporterFilter(SafeExceptionReporterFilter):
    """
    Ignores all the filtering done by its parent class.
    """

    def get_post_parameters(self, request):
        return request.POST

    def get_traceback_frame_variables(self, request, tb_frame):
        return tb_frame.f_locals.items()


@sensitive_variables()
@sensitive_post_parameters()
def custom_exception_reporter_filter_view(request):
    # Do not just use plain strings for the variables' values in the code
    # so that the tests don't return false positives when the function's source
    # is displayed in the exception report.
    cooked_eggs = ''.join(['s', 'c', 'r', 'a', 'm', 'b', 'l', 'e', 'd'])
    sauce = ''.join(['w', 'o', 'r', 'c', 'e', 's', 't', 'e', 'r', 's', 'h', 'i', 'r', 'e'])
    request.exception_reporter_filter = UnsafeExceptionReporterFilter()
    try:
        raise Exception
    except Exception:
        exc_info = sys.exc_info()
        send_log(request, exc_info)
        return technical_500_response(request, *exc_info)


class Klass(object):

    @sensitive_variables('sauce')
    def method(self, request):
        # Do not just use plain strings for the variables' values in the code
        # so that the tests don't return false positives when the function's
        # source is displayed in the exception report.
        cooked_eggs = ''.join(['s', 'c', 'r', 'a', 'm', 'b', 'l', 'e', 'd'])
        sauce = ''.join(['w', 'o', 'r', 'c', 'e', 's', 't', 'e', 'r', 's', 'h', 'i', 'r', 'e'])
        try:
            raise Exception
        except Exception:
            exc_info = sys.exc_info()
            send_log(request, exc_info)
            return technical_500_response(request, *exc_info)

def sensitive_method_view(request):
    return Klass().method(request)


@sensitive_variables('sauce')
@sensitive_post_parameters('bacon-key', 'sausage-key')
def multivalue_dict_key_error(request):
    cooked_eggs = ''.join(['s', 'c', 'r', 'a', 'm', 'b', 'l', 'e', 'd'])
    sauce = ''.join(['w', 'o', 'r', 'c', 'e', 's', 't', 'e', 'r', 's', 'h', 'i', 'r', 'e'])
    try:
        request.POST['bar']
    except Exception:
        exc_info = sys.exc_info()
        send_log(request, exc_info)
        return technical_500_response(request, *exc_info)
