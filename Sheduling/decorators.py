from functools import wraps
from django.http import JsonResponse, HttpResponseForbidden
from django.shortcuts import redirect
from django.contrib import messages
from django.urls import reverse

def scheduling_access_required(view_func):
    """
    Decorator to check if user has access to therapy scheduling module.
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('authentication:login')
        
        # Check if user has access to therapy scheduling module
        if hasattr(request.user, 'has_module_access'):
            if not request.user.has_module_access('therapy_scheduling'):
                if request.headers.get('Accept') == 'application/json':
                    return JsonResponse({
                        'error': 'Access denied',
                        'message': 'You do not have permission to access therapy scheduling'
                    }, status=403)
                else:
                    messages.error(request, 'You do not have permission to access therapy scheduling.')
                    return redirect('authentication:dashboard')
        
        return view_func(request, *args, **kwargs)
    return wrapper

def scheduling_admin_required(view_func):
    """
    Decorator to check if user has admin access to therapy scheduling.
    Only super_admin, admin, and scheduling_staff roles can access.
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('authentication:login')
        
        # Check if user has admin access to scheduling
        allowed_roles = ['super_admin', 'admin', 'scheduling_staff']
        if request.user.role not in allowed_roles:
            if request.headers.get('Accept') == 'application/json':
                return JsonResponse({
                    'error': 'Access denied',
                    'message': 'You do not have admin permission for therapy scheduling'
                }, status=403)
            else:
                messages.error(request, 'You do not have admin permission for therapy scheduling.')
                return redirect('authentication:dashboard')
        
        return view_func(request, *args, **kwargs)
    return wrapper

def therapist_access_required(view_func):
    """
    Decorator to check if user has therapist access to therapy scheduling.
    Therapists can view their assigned therapies but not modify scheduling.
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('authentication:login')
        
        # Check if user has therapist access
        allowed_roles = ['super_admin', 'admin', 'scheduling_staff', 'therapist', 'doctor']
        if request.user.role not in allowed_roles:
            if request.headers.get('Accept') == 'application/json':
                return JsonResponse({
                    'error': 'Access denied',
                    'message': 'You do not have permission to view therapy schedules'
                }, status=403)
            else:
                messages.error(request, 'You do not have permission to view therapy schedules.')
                return redirect('authentication:dashboard')
        
        return view_func(request, *args, **kwargs)
    return wrapper

def api_access_required(view_func):
    """
    Decorator for API endpoints that require scheduling access.
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({
                'error': 'Authentication required'
            }, status=401)
        
        # Check if user has access to therapy scheduling module
        if hasattr(request.user, 'has_module_access'):
            if not request.user.has_module_access('therapy_scheduling'):
                return JsonResponse({
                    'error': 'Access denied',
                    'message': 'You do not have permission to access therapy scheduling'
                }, status=403)
        
        return view_func(request, *args, **kwargs)
    return wrapper
