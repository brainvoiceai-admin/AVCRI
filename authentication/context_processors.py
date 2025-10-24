def user_modules(request):
    """
    Context processor to make user's accessible modules available in templates
    """
    if request.user.is_authenticated:
        return {
            'user_modules': request.user.get_accessible_modules(),
            'user_has_module_access': request.user.has_module_access,
        }
    return {
        'user_modules': [],
        'user_has_module_access': lambda x: False,
    }
