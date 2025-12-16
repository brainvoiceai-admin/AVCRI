"""
Custom error handlers for AVCRI
These views handle HTTP error responses and render custom error templates
"""
from django.shortcuts import render
from django.http import HttpResponse


def handler400(request, exception=None):
    """
    Handler for 400 Bad Request errors
    """
    return render(request, 'errortemplates/400.html', status=400)


def handler403(request, exception=None):
    """
    Handler for 403 Forbidden errors
    """
    return render(request, 'errortemplates/403.html', status=403)


def handler404(request, exception=None):
    """
    Handler for 404 Not Found errors
    """
    return render(request, 'errortemplates/404.html', status=404)


def handler500(request):
    """
    Handler for 500 Internal Server Error
    Note: 500 handler doesn't receive exception parameter
    """
    return render(request, 'errortemplates/500.html', status=500)


def csrf_failure(request, reason=""):
    """
    Handler for CSRF verification failures
    """
    return render(request, 'errortemplates/csrf_failure.html', status=403)

