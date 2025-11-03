from functools import wraps
from django.shortcuts import redirect
from django.contrib import messages
from django.http import JsonResponse


def patient_dashboard_access_required(view_func):
    """
    Decorator to check if user has access to patient dashboard
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        # Check if user is authenticated
        if not request.user.is_authenticated:
            if request.headers.get('Content-Type') == 'application/json':
                return JsonResponse({'error': 'Authentication required'}, status=401)
            return redirect('authentication:login')
        
        # Check if user has the patient dashboard module
        user_modules = getattr(request.user, 'get_accessible_modules', lambda: [])()
        module_names = [module.name for module in user_modules]
        
        if 'patient_dashboard' not in module_names:
            # For API endpoints, always return JSON (check path or Accept header)
            is_api_request = (
                '/api/' in request.path or 
                request.headers.get('Accept', '').startswith('application/json') or
                request.headers.get('Content-Type') == 'application/json'
            )
            if is_api_request:
                return JsonResponse({'error': 'Access denied to patient dashboard'}, status=403)
            messages.error(request, 'You do not have access to the patient dashboard.')
            # Try to redirect to home, but if that fails, return 403
            try:
                return redirect('patient:home')
            except:
                return JsonResponse({'error': 'Access denied to patient dashboard'}, status=403)
        
        return view_func(request, *args, **kwargs)
    return wrapper


def patient_data_access_required(view_func):
    """
    Decorator to ensure user can only access their own patient data
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        # Check if user is authenticated
        if not request.user.is_authenticated:
            # For API endpoints, always return JSON (check path or Accept header)
            is_api_request = (
                '/api/' in request.path or 
                request.headers.get('Accept', '').startswith('application/json') or
                request.headers.get('Content-Type') == 'application/json'
            )
            if is_api_request:
                return JsonResponse({'error': 'Authentication required'}, status=401)
            return redirect('authentication:login')
        
        # For patient dashboard, users can only see their own data
        # This is enforced in the view logic, but we can add additional checks here
        return view_func(request, *args, **kwargs)
    return wrapper
