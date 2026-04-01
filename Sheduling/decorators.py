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
                    return redirect('authentication:user_profile')
        
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
                return redirect('authentication:user_profile')
        
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
                return redirect('authentication:user_profile')
        
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


def therapy_data_api_access(view_func):
    """
    Like api_access_required, but also allows scoped read-only therapy-data for:
    - scope=user_entry (current user's allocations) — no therapy_scheduling module required
    - scope=doctor_patients (doctor role + hospital doctor code patients)
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({'error': 'Authentication required'}, status=401)
        scope = (request.GET.get('scope') or '').strip()
        if scope == 'user_entry':
            return view_func(request, *args, **kwargs)
        if scope == 'doctor_patients':
            if getattr(request.user, 'role', None) in ('doctor', 'super_admin'):
                return view_func(request, *args, **kwargs)
            return JsonResponse({
                'error': 'Access denied',
                'message': 'Doctor role required for this scope',
            }, status=403)
        if hasattr(request.user, 'has_module_access'):
            if not request.user.has_module_access('therapy_scheduling'):
                return JsonResponse({
                    'error': 'Access denied',
                    'message': 'You do not have permission to access therapy scheduling',
                }, status=403)
        return view_func(request, *args, **kwargs)
    return wrapper

def procurement_access_required(view_func):
    """
    Decorator to check if user has access to procurement dashboard.
    Allows super_admin, admin, scheduling_staff, and ip_pharmacy_staff.
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('authentication:login')
        
        # Check if user has procurement access
        allowed_roles = ['super_admin', 'admin', 'scheduling_staff', 'ip_pharmacy_staff']
        if request.user.role not in allowed_roles:
            if request.headers.get('Accept') == 'application/json':
                return JsonResponse({
                    'error': 'Access denied',
                    'message': 'You do not have permission to access procurement dashboard'
                }, status=403)
            else:
                messages.error(request, 'You do not have permission to access procurement dashboard.')
                return redirect('authentication:user_profile')
        
        return view_func(request, *args, **kwargs)
    return wrapper

def procurement_api_access_required(view_func):
    """
    Decorator for procurement API endpoints.
    Allows super_admin, admin, scheduling_staff, and ip_pharmacy_staff.
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({
                'error': 'Authentication required'
            }, status=401)
        
        # Check if user has procurement access
        allowed_roles = ['super_admin', 'admin', 'scheduling_staff', 'ip_pharmacy_staff']
        if request.user.role not in allowed_roles:
            return JsonResponse({
                'error': 'Access denied',
                'message': 'You do not have permission to access procurement API'
            }, status=403)
        
        return view_func(request, *args, **kwargs)
    return wrapper

def prescription_scheduling_access_required(view_func):
    """
    Decorator to check if user has access to prescription scheduling.
    Allows users with prescription_scheduling module access or specific roles.
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('authentication:login')
        
        # Allowed roles for prescription scheduling
        allowed_roles = ['super_admin', 'admin', 'scheduling_staff', 'ip_pharmacy_staff', 'doctor']
        
        # Check if user has one of the allowed roles
        if request.user.role in allowed_roles:
            return view_func(request, *args, **kwargs)
        
        # Also check if user has prescription_scheduling module access (for custom roles)
        if hasattr(request.user, 'has_module_access'):
            if request.user.has_module_access('prescription_scheduling'):
                return view_func(request, *args, **kwargs)
        
        # Access denied
        if request.headers.get('Accept') == 'application/json':
            return JsonResponse({
                'error': 'Access denied',
                'message': 'You do not have permission to access prescription scheduling'
            }, status=403)
        else:
            messages.error(request, 'You do not have permission to access prescription scheduling.')
            return redirect('authentication:user_profile')
    
    return wrapper

def prescription_scheduling_api_access_required(view_func):
    """
    Decorator for prescription scheduling API endpoints.
    Allows users with prescription_scheduling module access or specific roles.
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({
                'error': 'Authentication required'
            }, status=401)
        
        # Allowed roles for prescription scheduling
        allowed_roles = ['super_admin', 'admin', 'scheduling_staff', 'ip_pharmacy_staff', 'doctor']
        
        # Check if user has one of the allowed roles
        if request.user.role in allowed_roles:
            return view_func(request, *args, **kwargs)
        
        # Also check if user has prescription_scheduling module access (for custom roles)
        if hasattr(request.user, 'has_module_access'):
            if request.user.has_module_access('prescription_scheduling'):
                return view_func(request, *args, **kwargs)
        
        # Access denied
        return JsonResponse({
            'error': 'Access denied',
            'message': 'You do not have permission to access prescription scheduling'
        }, status=403)
    
    return wrapper