from collections import OrderedDict


def user_modules(request):
    """
    Context processor to make user's accessible modules available in templates,
    grouped by their NavSection for dynamic sidebar rendering.
    """
    empty = {
        'user_modules': [],
        'user_master_modules': [],
        'nav_sections': [],
        'user_has_module_access': lambda x: False,
    }

    if not request.user.is_authenticated:
        return empty

    try:
        if hasattr(request.user, 'pk') and request.user.pk:
            try:
                request.user.refresh_from_db(fields=['role', 'custom_role_id'])
            except Exception:
                pass

        modules_qs = request.user.get_accessible_modules()
        modules_list = list(modules_qs) if hasattr(modules_qs, '__iter__') else []

        seen_names = set()
        unique_modules = []
        for module in modules_list:
            key = (module.name or '').lower()
            if key and key not in seen_names:
                seen_names.add(key)
                unique_modules.append(module)
            elif not key:
                unique_modules.append(module)

        # Preload nav_section to avoid N+1 queries
        from authentication.models import Module as ModuleModel
        mod_ids = [m.id for m in unique_modules]
        mod_map = {}
        if mod_ids:
            for m in ModuleModel.objects.filter(id__in=mod_ids).select_related('nav_section'):
                mod_map[m.id] = m

        # Group by nav_section, preserving section order
        section_dict = OrderedDict()
        unsectioned = []
        for module in unique_modules:
            rich = mod_map.get(module.id, module)
            # Attach resolved URL for template usage
            rich.resolved_url = rich.get_url()
            sec = rich.nav_section
            if sec and sec.is_active:
                key = sec.id
                if key not in section_dict:
                    section_dict[key] = {'section': sec, 'modules': []}
                section_dict[key]['modules'].append(rich)
            else:
                unsectioned.append(rich)

        # Sort sections by order
        sorted_sections = sorted(section_dict.values(), key=lambda s: (s['section'].order, s['section'].name))

        # If there are unsectioned modules, add them under "Other"
        if unsectioned:
            sorted_sections.append({
                'section': type('Obj', (), {'display_name': 'Other', 'icon': '📌', 'name': 'other', 'id': 0})(),
                'modules': unsectioned,
            })

        master_modules = [
            m for m in unique_modules
            if 'master' in (m.name or '').lower()
            or 'master' in (m.display_name or '').lower()
            or 'master' in (getattr(m, 'url_name', '') or '').lower()
        ]

        return {
            'user_modules': unique_modules,
            'user_master_modules': master_modules,
            'nav_sections': sorted_sections,
            'user_has_module_access': request.user.has_module_access,
        }
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error getting user modules: {e}", exc_info=True)
        return empty
