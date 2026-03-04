def user_modules(request):
    """
    Context processor to make user's accessible modules available in templates
    """
    if request.user.is_authenticated:
        try:
            # Refresh user from database to ensure we have latest role and custom_role data
            # Only refresh if user is not being created (has a pk)
            if hasattr(request.user, 'pk') and request.user.pk:
                try:
                    request.user.refresh_from_db(fields=['role', 'custom_role_id'])
                except:
                    pass  # If refresh fails, continue with current values
            
            # Get modules - this will return a queryset
            modules_queryset = request.user.get_accessible_modules()
            
            # Convert to list to force evaluation and ensure it's always fresh
            # This also ensures the queryset is evaluated once per request
            if hasattr(modules_queryset, '__iter__'):
                modules_list = list(modules_queryset)
            else:
                modules_list = []
            
            # Filter to ensure unique module names (by name field, not display_name)
            # If multiple modules have the same name, only show the first one
            # But allow modules with different names even if they have the same URL
            seen_names = set()
            unique_modules = []
            for module in modules_list:
                # Use the 'name' field (not display_name) to check for duplicates
                module_name_lower = module.name.lower() if hasattr(module, 'name') else ''
                if module_name_lower and module_name_lower not in seen_names:
                    seen_names.add(module_name_lower)
                    unique_modules.append(module)
                elif not module_name_lower:
                    # If module has no name, include it anyway (shouldn't happen, but safe)
                    unique_modules.append(module)
            
            master_modules = [
                m for m in unique_modules
                if 'master' in (m.name or '').lower()
                or 'master' in (m.display_name or '').lower()
                or 'master' in (m.url_name or '').lower()
            ]

            return {
                'user_modules': unique_modules,
                'user_master_modules': master_modules,
                'user_has_module_access': request.user.has_module_access,
            }
        except Exception as e:
            # If there's any error, return empty list to prevent template errors
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error getting user modules: {e}", exc_info=True)
            return {
                'user_modules': [],
                'user_master_modules': [],
                'user_has_module_access': lambda x: False,
            }
    return {
        'user_modules': [],
        'user_master_modules': [],
        'user_has_module_access': lambda x: False,
    }
