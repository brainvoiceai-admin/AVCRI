from functools import wraps
from django.shortcuts import redirect
from django.contrib import messages
from django.http import HttpResponseForbidden

def module_access_required(module_name):
    """
    Decorator to check if user has access to a specific module
    """
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect('login')
            
            if not request.user.has_module_access(module_name):
                messages.error(request, f'You do not have permission to access {module_name}.')
                return HttpResponseForbidden("Access Denied: You do not have permission to access this module.")
            
            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator

def super_admin_required(view_func):
    """
    Decorator to check if user is super admin
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('login')
        
        if request.user.role != 'super_admin':
            messages.error(request, 'You must be a super admin to access this page.')
            return HttpResponseForbidden("Access Denied: Super admin privileges required.")
        
        return view_func(request, *args, **kwargs)
    return wrapper

def role_required(allowed_roles):
    """
    Decorator to check if user has one of the allowed roles
    Usage: @role_required(['doctor', 'admin'])
    """
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect('login')
            
            if request.user.role not in allowed_roles and request.user.role != 'super_admin':
                messages.error(request, f'Access denied. This page is only for: {", ".join(allowed_roles)}.')
                return redirect('patient:home')
            
            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator


