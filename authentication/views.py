from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.forms import AuthenticationForm
from .models import Role, Module, CustomUser, AuditLog
from .decorators import super_admin_required, role_required
from django.core.paginator import Paginator
from django.utils import timezone
from django.db import transaction, models
from django.core.exceptions import ValidationError
import json
from masters.models import get_staying_room_display_number

def log_audit_event(user, action, description, status='success', object_type='', object_id='', additional_data=None, request=None):
    """Utility function to log audit events"""
    try:
        ip_address = None
        user_agent = ''
        
        if request:
            ip_address = get_client_ip(request)
            user_agent = request.META.get('HTTP_USER_AGENT', '')
        
        AuditLog.objects.create(
            user=user,
            action=action,
            description=description,
            ip_address=ip_address,
            user_agent=user_agent,
            status=status,
            object_type=object_type,
            object_id=object_id,
            additional_data=additional_data
        )
    except Exception as e:
        # Don't let audit logging break the main functionality
        print(f"Audit logging error: {e}")

def get_client_ip(request):
    """Get client IP address from request"""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip

@login_required
@super_admin_required
def role_management(request):
    """View for Super Admin to manage roles and module permissions"""
    roles = Role.objects.all().order_by('name')
    
    # Apply filters from GET parameters
    search_query = request.GET.get('search', '').strip()
    status_filter = request.GET.get('status', '').strip()
    
    if search_query:
        from django.db.models import Q
        roles = roles.filter(
            Q(name__icontains=search_query) |
            Q(display_name__icontains=search_query) |
            Q(description__icontains=search_query)
        )
    
    if status_filter == 'active':
        roles = roles.filter(is_active=True)
    elif status_filter == 'inactive':
        roles = roles.filter(is_active=False)
    
    modules = Module.objects.filter(is_active=True).order_by('order', 'name')
    
    context = {
        'roles': roles,
        'modules': modules,
    }
    return render(request, 'authentication/role_management.html', context)

def categorize_modules(modules):
    """Group modules by category based on their names and display names"""
    categories = {
        'Patient Management': [],
        'Therapist Management': [],
        'Pharmacy': [],
        'Masters & Settings': [],
        'Other': []
    }
    
    for module in modules:
        name_lower = module.name.lower()
        display_lower = module.display_name.lower()
        
        # Categorize based on keywords
        if any(keyword in name_lower or keyword in display_lower 
               for keyword in ['patient', 'registration', 'visit', 'session', 'feedback']):
            categories['Patient Management'].append(module)
        elif any(keyword in name_lower or keyword in display_lower 
                 for keyword in ['therapist', 'therapy', 'schedule', 'booking', 'allocation']):
            categories['Therapist Management'].append(module)
        elif any(keyword in name_lower or keyword in display_lower 
                 for keyword in ['pharmacy', 'prescription', 'procurement', 'medicine', 'medicin']):
            categories['Pharmacy'].append(module)
        elif any(keyword in name_lower or keyword in display_lower 
                 for keyword in ['master', 'role', 'user', 'module', 'audit', 'admin', 'management', 'dashboard']):
            categories['Masters & Settings'].append(module)
        else:
            categories['Other'].append(module)
    
    # Remove empty categories
    return {k: v for k, v in categories.items() if v}

@login_required
@super_admin_required
def create_role(request):
    """Create a new role with module permissions"""
    if request.method == 'POST':
        name = request.POST.get('name')
        display_name = request.POST.get('display_name')
        description = request.POST.get('description', '')
        module_ids = request.POST.getlist('modules')
        
        if not name or not display_name:
            messages.error(request, 'Name and Display Name are required.')
            return redirect('authentication:create_role')
        
        if Role.objects.filter(name=name).exists():
            messages.error(request, 'A role with this name already exists.')
            return redirect('authentication:create_role')
        
        role = Role.objects.create(
            name=name,
            display_name=display_name,
            description=description
        )
        
        # Add selected modules
        if module_ids:
            modules = Module.objects.filter(id__in=module_ids)
            role.modules.set(modules)
        
        messages.success(request, f'Role "{role.display_name}" created successfully.')
        # Redirect with success parameter to show toast
        from django.urls import reverse
        return redirect(reverse('authentication:role_management') + '?created=1')
    
    # GET request - show create role form
    modules = Module.objects.filter(is_active=True).order_by('order', 'name')
    modules_by_category = categorize_modules(modules)
    
    context = {
        'modules': modules,
        'modules_by_category': modules_by_category,
    }
    return render(request, 'authentication/create_role.html', context)

@login_required
@super_admin_required
def edit_role(request, role_id):
    """Edit an existing role"""
    role = get_object_or_404(Role, id=role_id)
    
    if request.method == 'POST':
        role.name = request.POST.get('name')
        role.display_name = request.POST.get('display_name')
        role.description = request.POST.get('description', '')
        role.is_active = request.POST.get('is_active') == 'on'
        
        module_ids = request.POST.getlist('modules')
        modules = Module.objects.filter(id__in=module_ids)
        role.modules.set(modules)
        
        role.save()
        
        messages.success(request, f'Role "{role.display_name}" updated successfully.')
        # Redirect with update parameter to show correct toast
        from django.urls import reverse
        return redirect(reverse('authentication:role_management') + '?updated=1')
    
    modules = Module.objects.filter(is_active=True).order_by('order', 'name')
    context = {
        'role': role,
        'modules': modules,
    }
    return render(request, 'authentication/edit_role.html', context)

@login_required
@super_admin_required
def delete_role(request, role_id):
    """Delete a role"""
    role = get_object_or_404(Role, id=role_id)
    
    # Check if any users are using this role
    users_with_role = CustomUser.objects.filter(custom_role=role)
    if users_with_role.exists():
        messages.error(request, f'Cannot delete role "{role.display_name}" because {users_with_role.count()} user(s) are assigned to it.')
        return redirect('authentication:role_management')
    
    role.delete()
    messages.success(request, f'Role "{role.display_name}" deleted successfully.')
    return redirect('authentication:role_management')

@login_required
@super_admin_required
def user_role_assignment(request):
    """View for Super Admin to assign custom roles to users"""
    users = CustomUser.objects.all().order_by('username')
    roles = Role.objects.filter(is_active=True).order_by('name')
    
    # Apply filters from GET parameters
    search_query = request.GET.get('search', '').strip()
    status_filter = request.GET.get('status', '').strip()
    default_role_filter = request.GET.get('default_role', '').strip()
    custom_role_filter = request.GET.get('custom_role', '').strip()
    
    if search_query:
        from django.db.models import Q
        users = users.filter(
            Q(username__icontains=search_query) |
            Q(email__icontains=search_query) |
            Q(first_name__icontains=search_query) |
            Q(last_name__icontains=search_query)
        )
    
    if status_filter == 'active':
        users = users.filter(is_active=True)
    elif status_filter == 'inactive':
        users = users.filter(is_active=False)
    
    if default_role_filter:
        users = users.filter(role=default_role_filter)
    
    if custom_role_filter:
        if custom_role_filter == 'none':
            users = users.filter(custom_role__isnull=True)
        else:
            users = users.filter(custom_role_id=custom_role_filter)
    
    if request.method == 'POST':
        user_id = request.POST.get('user_id')
        role_id = request.POST.get('role_id')
        
        user = get_object_or_404(CustomUser, id=user_id)
        role = get_object_or_404(Role, id=role_id) if role_id else None
        
        user.custom_role = role
        user.save()
        
        messages.success(request, f'Role assignment updated for {user.username}.')
        
        # Preserve filter parameters in redirect
        from django.urls import reverse
        from urllib.parse import urlencode
        
        filter_params = {}
        if request.GET.get('search'):
            filter_params['search'] = request.GET.get('search')
        if request.GET.get('status'):
            filter_params['status'] = request.GET.get('status')
        if request.GET.get('default_role'):
            filter_params['default_role'] = request.GET.get('default_role')
        if request.GET.get('custom_role'):
            filter_params['custom_role'] = request.GET.get('custom_role')
        
        if filter_params:
            redirect_url = reverse('authentication:user_role_assignment') + '?' + urlencode(filter_params)
        else:
            redirect_url = reverse('authentication:user_role_assignment')
        
        return redirect(redirect_url)
    
    context = {
        'users': users,
        'roles': roles,
    }
    return render(request, 'authentication/user_role_assignment.html', context)

@login_required
@super_admin_required
def module_management(request):
    """View for Super Admin to manage modules"""
    modules = Module.objects.all().order_by('order', 'name')
    
    if request.method == 'POST':
        action = request.POST.get('action')
        
        if action == 'create':
            name = request.POST.get('name')
            display_name = request.POST.get('display_name')
            url_name = request.POST.get('url_name')
            icon = request.POST.get('icon', '📋')
            order = request.POST.get('order', 0)
            description = request.POST.get('description', '')
            
            if not name or not display_name or not url_name:
                messages.error(request, 'Name, Display Name, and URL Name are required.')
            else:
                module, created = Module.objects.get_or_create(
                    name=name,
                    defaults={
                        'display_name': display_name,
                        'url_name': url_name,
                        'icon': icon,
                        'order': order,
                        'description': description,
                    }
                )
                if created:
                    messages.success(request, f'Module "{module.display_name}" created successfully.')
                else:
                    messages.error(request, f'A module with name "{name}" already exists.')
        
        elif action == 'update':
            module_id = request.POST.get('module_id')
            module = get_object_or_404(Module, id=module_id)
            
            module.display_name = request.POST.get('display_name')
            module.url_name = request.POST.get('url_name')
            module.icon = request.POST.get('icon', '📋')
            module.order = request.POST.get('order', 0)
            module.description = request.POST.get('description', '')
            module.is_active = request.POST.get('is_active') == 'on'
            module.save()
            
            messages.success(request, f'Module "{module.display_name}" updated successfully.')
        
        elif action == 'delete':
            module_id = request.POST.get('module_id')
            module = get_object_or_404(Module, id=module_id)
            
            # Check if module is used by any roles
            roles_using_module = Role.objects.filter(modules=module)
            if roles_using_module.exists():
                messages.error(request, f'Cannot delete module "{module.display_name}" because it is used by {roles_using_module.count()} role(s).')
        else:
                module.delete()
                messages.success(request, f'Module "{module.display_name}" deleted successfully.')
        
        return redirect('authentication:module_management')
    
    context = {
        'modules': modules,
    }
    return render(request, 'authentication/module_management.html', context)

# Original authentication views that were in the system
def login_view(request):
    """Login view"""
    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            username = form.cleaned_data.get('username')
            password = form.cleaned_data.get('password')
            user = authenticate(username=username, password=password)
            if user is not None:
                login(request, user)
                messages.success(request, f'Welcome back, {user.username}!')
                
                # Log successful login
                log_audit_event(
                    user=user,
                    action='login',
                    description=f'User {user.username} logged in successfully',
                    status='success',
                    request=request
                )
                
                # Redirect to appropriate dashboard based on user role
                redirect_url = get_dashboard_redirect_url(user)
                return redirect(redirect_url)
            else:
                messages.error(request, 'Invalid username or password.')
        else:
            messages.error(request, 'Invalid username or password.')
    
    form = AuthenticationForm()
    return render(request, 'login.html', {'form': form})

def get_dashboard_redirect_url(user):
    """Get the appropriate dashboard URL after login.

    Per current requirement, always redirect to the User Profile Dashboard.
    """
    return 'authentication:user_profile'

def logout_view(request):
    """Logout view"""
    user = request.user
    logout(request)
    
    # Log logout (before user is logged out)
    if user.is_authenticated:
        log_audit_event(
            user=user,
            action='logout',
            description=f'User {user.username} logged out',
            status='success',
            request=request
        )
    
    messages.info(request, 'You have been logged out.')
    return redirect('patient:home')

@login_required
@role_required(['therapist'])
def therapist_dashboard(request):
    """Therapist dashboard view"""
    return render(request, 'dashboards/therapist/therapist_dashboard.html')

@login_required
@role_required(['scheduling_staff'])
def scheduling_dashboard(request):
    """Scheduling dashboard view"""
    return render(request, 'dashboards/scheduling/scheduling_dashboard.html')

@login_required
@role_required(['doctor'])
def doctor_dashboard(request):
    """Doctor dashboard view"""
    return render(request, 'dashboards/doctorsAndHelpDesk/doctor_dashboard.html')

@login_required
@role_required(['admin', 'hr'])
def gm_hr_dashboard(request):
    """GM/HR dashboard view"""
    return render(request, 'dashboards/gm_hr/gm_hr_dashboard.html')

@login_required
@super_admin_required
# Removed views for deleted templates (not in navigation):
# @login_required
# def superadmin_dashboard(request):
#     """Super admin dashboard view"""
#     return render(request, 'dashboards/superadmin/superadmin_dashboard.html')

# @login_required
# @role_required(['doctor'])
# def medicin_prescription(request):
#     """Medicine prescription view"""
#     return render(request, 'dashboards/doctorsAndHelpDesk/medicin_prescription.html')

@login_required
@role_required(['patient'])
def Patient_dashboard(request):
    """Patient dashboard view"""
    return render(request, 'dashboards/patient/Patient_dashboard.html')

# @login_required
# def Tenants_dashboard(request):
#     """Tenants dashboard view"""
#     return render(request, 'dashboards/tenants/tenants_dashboard.html')

# @login_required
# def Helpdeskadmindash(request):
#     """Helpdesk admin dashboard view"""
#     return render(request, 'dashboards/helpdesk/helpdesk_dashboard.html')

# @login_required
# def medicin_prescription_table(request):
#     """Medicine prescription table view"""
#     return render(request, 'dashboards/doctorsAndHelpDesk/medicin_prescription_table.html')

@login_required
@super_admin_required
def Manage_user(request):
    """Enhanced user management view with module permissions"""
    # Get all users (both active and inactive) for management
    users = CustomUser.objects.all().order_by('username')
    
    # Apply filters from GET parameters
    search_query = request.GET.get('search', '').strip()
    status_filter = request.GET.get('status', '').strip()
    role_filter = request.GET.get('role', '').strip()
    
    if search_query:
        from django.db.models import Q
        users = users.filter(
            Q(username__icontains=search_query) |
            Q(email__icontains=search_query) |
            Q(first_name__icontains=search_query) |
            Q(last_name__icontains=search_query) |
            Q(mobile__icontains=search_query)
        )
    
    if status_filter == 'active':
        users = users.filter(is_active=True)
    elif status_filter == 'inactive':
        users = users.filter(is_active=False)
    
    if role_filter:
        users = users.filter(role=role_filter)
    
    roles = Role.objects.filter(is_active=True).order_by('name')
    modules = Module.objects.filter(is_active=True).order_by('order', 'name')
    
    if request.method == 'POST':
        action = request.POST.get('action')
        
        if action == 'create_user':
            # Create new user
            username = request.POST.get('username')
            email = request.POST.get('email')
            first_name = request.POST.get('first_name')
            last_name = request.POST.get('last_name')
            role = request.POST.get('role')
            custom_role_id = request.POST.get('custom_role')
            mobile = request.POST.get('mobile')
            password = request.POST.get('password')
            patient_registration_number = request.POST.get('patient_registration_number')
            therapist_code = request.POST.get('therapist_code')
            
            if not username or not email or not password:
                messages.error(request, 'Username, email, and password are required.')
            elif CustomUser.objects.filter(username=username).exists():
                messages.error(request, f'Username "{username}" already exists.')
            elif CustomUser.objects.filter(email=email).exists():
                messages.error(request, f'Email "{email}" already exists.')
            else:
                # Check for unique constraints on role-specific fields
                if role == 'patient' and patient_registration_number:
                    from authentication.models import PatientProfile
                    if PatientProfile.objects.filter(patient_reg_no=patient_registration_number).exists():
                        messages.error(request, f'Patient registration number "{patient_registration_number}" already exists.')
                        return redirect('authentication:Manage_user')
                elif role == 'therapist' and therapist_code:
                    from authentication.models import TherapistProfile
                    if TherapistProfile.objects.filter(therapist_code=therapist_code).exists():
                        messages.error(request, f'Therapist code "{therapist_code}" already exists.')
                        return redirect('authentication:Manage_user')
                
                gender = request.POST.get('gender', 'male')  # Default to male if not provided
                
                user = CustomUser.objects.create_user(
                    username=username,
                    email=email,
                    password=password,
                    first_name=first_name,
                    last_name=last_name,
                    role=role,
                    mobile=mobile if mobile else None,
                    gender=gender
                )
                
                # Assign custom role if selected
                if custom_role_id:
                    custom_role = get_object_or_404(Role, id=custom_role_id)
                    user.custom_role = custom_role
                    user.save()
                
                # Create appropriate profile based on role
                from authentication.models import PatientProfile, TherapistProfile, DoctorProfile, AdminProfile, NurseProfile, StaffProfile
                
                if role == 'patient' and patient_registration_number:
                    PatientProfile.objects.create(
                        user=user,
                        patient_reg_no=patient_registration_number
                    )
                elif role == 'therapist' and therapist_code:
                    # Create therapist profile
                    therapist_profile = TherapistProfile.objects.create(
                        user=user,
                        therapist_code=therapist_code,
                        employee_code=request.POST.get('employee_code', f"EMP{user.id:06d}"),  # Use provided or generate
                        therapist_grade="Junior"  # Default grade
                    )
                    
                    # Create therapist master record
                    from masters.models import TherapistMaster
                    TherapistMaster.objects.create(
                        user=user,
                        therapist_profile=therapist_profile,
                        therapist_code=therapist_code,
                        therapist_name=user.get_full_name() or user.username,
                        therapist_grade="Junior",
                        employee_code=request.POST.get('employee_code', f"EMP{user.id:06d}"),
                        is_bathing_therapist=True
                    )
                elif role == 'doctor':
                    DoctorProfile.objects.create(
                        user=user,
                        doctor_id=f"DOC{user.id:06d}",
                        specialization="General Medicine",
                        department="Medical",
                        qualification="MBBS",
                        experience_years=0
                    )
                elif role in ['admin', 'super_admin']:
                    AdminProfile.objects.create(
                        user=user,
                        admin_id=f"ADM{user.id:06d}",
                        department="Administration",
                        designation="Administrator" if role == 'admin' else "Super Administrator"
                    )
                elif role == 'nurse':
                    NurseProfile.objects.create(
                        user=user,
                        nurse_id=f"NUR{user.id:06d}",
                        department="Nursing",
                        qualification="B.Sc Nursing",
                        experience_years=0
                    )
                elif role in ['scheduling_staff', 'ip_pharmacy_staff', 'imu_staff', 'finance_staff', 'hr', 'housekeeping_staff']:
                    # Get department from POST data, especially important for IP Pharmacy Staff
                    department = request.POST.get('department', '')
                    if not department and role == 'ip_pharmacy_staff':
                        # Require department for IP Pharmacy Staff
                        messages.error(request, 'Department is required for IP Pharmacy Staff.')
                        return redirect('authentication:Manage_user')
                    if not department:
                        department = _get_department_for_role(role)
                    
                    StaffProfile.objects.create(
                        user=user,
                        staff_id=f"STF{user.id:06d}",
                        department=department,
                        designation=_get_designation_for_role(role)
                    )
                
                messages.success(request, f'User "{user.username}" created successfully.')
                
                # Log user creation
                log_audit_event(
                    user=request.user,
                    action='create',
                    description=f'Created new user: {user.username} with role {user.get_role_display()}',
                    status='success',
                    object_type='User',
                    object_id=str(user.id),
                    request=request
                )
        
        elif action == 'update_user':
            user_id = request.POST.get('user_id')
            user = get_object_or_404(CustomUser, id=user_id)
            
            # Store old role to check if it changed
            old_role = user.role
            new_role = request.POST.get('role')
            
            user.first_name = request.POST.get('first_name')
            user.last_name = request.POST.get('last_name')
            user.email = request.POST.get('email')
            user.role = new_role
            mobile = request.POST.get('mobile')
            user.mobile = mobile if mobile else None
            user.gender = request.POST.get('gender', 'male')  # Default to male if not provided
            user.is_active = request.POST.get('is_active') == 'on'
            
            # Update password if provided
            new_password = request.POST.get('password')
            if new_password and new_password.strip():
                user.set_password(new_password)
                messages.info(request, f'Password for "{user.username}" has been updated.')
            
            # Only call change_user_role if the role actually changed
            if old_role != new_role:
                # Role changed - need to delete old profile and create new one
                from authentication.role_change_utils import change_user_role, get_mandatory_fields_for_role
                
                # Update role-specific fields
                patient_registration_number = request.POST.get('patient_registration_number')
                therapist_code = request.POST.get('therapist_code')
                employee_code = request.POST.get('employee_code')
                
                # Prepare profile data for new role with only mandatory fields
                profile_data = {}
                mandatory_fields = get_mandatory_fields_for_role(new_role)
                
                if new_role == 'patient' and patient_registration_number:
                    profile_data['patient_reg_no'] = patient_registration_number
                elif new_role == 'therapist' and therapist_code:
                    profile_data['therapist_code'] = therapist_code
                    profile_data['employee_code'] = employee_code or f"EMP{user.id:06d}"
                elif new_role == 'doctor':
                    profile_data['doctor_id'] = request.POST.get('doctor_id', f"DOC{user.id:06d}")
                    profile_data['specialization'] = request.POST.get('specialization', 'General Medicine')
                    profile_data['department'] = request.POST.get('department', 'Medical')
                    profile_data['qualification'] = request.POST.get('qualification', 'MBBS')
                    profile_data['experience_years'] = request.POST.get('experience_years', 0)
                elif new_role in ['admin', 'super_admin']:
                    profile_data['admin_id'] = request.POST.get('admin_id', f"ADM{user.id:06d}")
                    profile_data['department'] = request.POST.get('department', 'Administration')
                    profile_data['designation'] = request.POST.get('designation', 
                        'Administrator' if new_role == 'admin' else 'Super Administrator')
                elif new_role == 'nurse':
                    profile_data['nurse_id'] = request.POST.get('nurse_id', f"NUR{user.id:06d}")
                    profile_data['department'] = request.POST.get('department', 'Nursing')
                    profile_data['qualification'] = request.POST.get('qualification', 'B.Sc Nursing')
                elif new_role in ['scheduling_staff', 'ip_pharmacy_staff', 'imu_staff', 'finance_staff', 'hr', 'housekeeping_staff']:
                    profile_data['staff_id'] = request.POST.get('staff_id', f"STF{user.id:06d}")
                    # Get department from POST data, especially important for IP Pharmacy Staff
                    department = request.POST.get('department', '')
                    if not department and new_role == 'ip_pharmacy_staff':
                        # Require department for IP Pharmacy Staff
                        messages.error(request, 'Department is required for IP Pharmacy Staff.')
                        return redirect('authentication:Manage_user')
                    if not department:
                        department = _get_department_for_role(new_role)
                    profile_data['department'] = department
                    profile_data['designation'] = request.POST.get('designation', _get_designation_for_role(new_role))
                
                # Change user role - this will delete all existing data
                success, message, new_profile = change_user_role(user, new_role, profile_data)
                
                if not success:
                    messages.error(request, message)
                    return redirect('authentication:Manage_user')
                else:
                    # Update therapist master if role is therapist
                    if new_role == 'therapist' and new_profile:
                        from masters.models import TherapistMaster
                        therapist_master, created = TherapistMaster.objects.get_or_create(
                            user=user,
                            defaults={
                                'therapist_profile': new_profile,
                                'therapist_code': profile_data.get('therapist_code', f"TH{user.id:06d}"),
                                'therapist_name': user.get_full_name() or user.username,
                                'therapist_grade': 'Junior',
                                'employee_code': profile_data.get('employee_code', f"EMP{user.id:06d}"),
                                'is_bathing_therapist': True
                            }
                        )
                        if not created:
                            # Update existing record
                            therapist_master.therapist_profile = new_profile
                            therapist_master.therapist_code = profile_data.get('therapist_code', therapist_master.therapist_code)
                            therapist_master.therapist_name = user.get_full_name() or user.username
                            therapist_master.employee_code = profile_data.get('employee_code', therapist_master.employee_code)
                            therapist_master.save()
                    
                    messages.warning(request, f"Role changed from {old_role} to {new_role}. All previous profile data has been deleted.")
            else:
                # Role hasn't changed - just update profile fields without deleting
                if user.role == 'therapist':
                    # Update therapist profile and master without deleting
                    therapist_code = request.POST.get('therapist_code')
                    employee_code = request.POST.get('employee_code')
                    
                    if hasattr(user, 'therapist_profile'):
                        # Update existing therapist profile
                        if therapist_code:
                            user.therapist_profile.therapist_code = therapist_code
                        if employee_code:
                            user.therapist_profile.employee_code = employee_code
                        user.therapist_profile.save()
                        
                        # Update TherapistMaster if it exists
                        from masters.models import TherapistMaster
                        try:
                            therapist_master = TherapistMaster.objects.get(user=user)
                            if therapist_code:
                                therapist_master.therapist_code = therapist_code
                            if employee_code:
                                therapist_master.employee_code = employee_code
                            therapist_master.therapist_name = user.get_full_name() or user.username
                            therapist_master.save()
                        except TherapistMaster.DoesNotExist:
                            # Create if doesn't exist
                            TherapistMaster.objects.create(
                                user=user,
                                therapist_profile=user.therapist_profile,
                                therapist_code=therapist_code or user.therapist_profile.therapist_code,
                                therapist_name=user.get_full_name() or user.username,
                                employee_code=employee_code or user.therapist_profile.employee_code,
                                is_bathing_therapist=True
                            )
                elif user.role == 'patient':
                    patient_registration_number = request.POST.get('patient_registration_number')
                    if hasattr(user, 'patient_profile') and patient_registration_number:
                        user.patient_profile.patient_reg_no = patient_registration_number
                        user.patient_profile.save()
                # Add similar logic for other roles if needed
            
            # Update custom role
            custom_role_id = request.POST.get('custom_role')
            if custom_role_id:
                custom_role = get_object_or_404(Role, id=custom_role_id)
                user.custom_role = custom_role
            else:
                user.custom_role = None
            
            user.save()
            messages.success(request, f'User "{user.username}" updated successfully.')
            
            # Log user update
            log_audit_event(
                user=request.user,
                action='update',
                description=f'Updated user: {user.username}',
                status='success',
                object_type='User',
                object_id=str(user.id),
                request=request
            )
        
        elif action == 'delete_user':
            user_id = request.POST.get('user_id')
            user = get_object_or_404(CustomUser, id=user_id)
            username = user.username
            user.delete()
            messages.success(request, f'User "{username}" deleted successfully.')
            
            # Log user deletion
            log_audit_event(
                user=request.user,
                action='delete',
                description=f'Deleted user: {username}',
                status='success',
                object_type='User',
                object_id=str(user_id),
                request=request
            )
        
        elif action == 'toggle_user_status':
            user_id = request.POST.get('user_id')
            user = get_object_or_404(CustomUser, id=user_id)
            is_active = request.POST.get('is_active') == 'true'
            user.is_active = is_active
            user.save()
            
            status_text = 'activated' if is_active else 'deactivated'
            messages.success(request, f'User "{user.username}" {status_text} successfully.')
            
            # Log user status change
            log_audit_event(
                user=request.user,
                action='update',
                description=f'{status_text.capitalize()} user: {user.username}',
                status='success',
                object_type='User',
                object_id=str(user_id),
                request=request
            )
        
        # Preserve filter parameters in redirect
        from django.urls import reverse
        from urllib.parse import urlencode
        
        filter_params = {}
        if request.GET.get('search'):
            filter_params['search'] = request.GET.get('search')
        if request.GET.get('status'):
            filter_params['status'] = request.GET.get('status')
        if request.GET.get('role'):
            filter_params['role'] = request.GET.get('role')
        
        if filter_params:
            redirect_url = reverse('authentication:Manage_user') + '?' + urlencode(filter_params)
        else:
            redirect_url = reverse('authentication:Manage_user')
        
        return redirect(redirect_url)
    
    # Handle AJAX validation requests
    if request.method == 'GET' and request.GET.get('action') == 'check_user_exists':
        username = request.GET.get('username', '').strip()
        email = request.GET.get('email', '').strip()
        
        result = {
            'username_exists': False,
            'email_exists': False,
            'username_message': '',
            'email_message': ''
        }
        
        if username:
            if CustomUser.objects.filter(username=username).exists():
                result['username_exists'] = True
                result['username_message'] = f'Username "{username}" already exists.'
        
        if email:
            if CustomUser.objects.filter(email=email).exists():
                result['email_exists'] = True
                result['email_message'] = f'Email "{email}" already exists.'
        
        return JsonResponse(result)
    
    context = {
        'users': users,
        'roles': roles,
        'modules': modules,
    }
    return render(request, 'dashboards/superadmin/Manage_user.html', context)

@login_required
def therapist_schedule(request):
    """View for therapists to see their next day's schedule"""
    print(request.user.role)
    if request.user.role != 'therapist' and request.user.role != 'super_admin':
        messages.error(request, 'Access denied. This page is only for therapists.')
        return redirect('patient:home')
    
    # Get tomorrow's date
    from datetime import datetime, timedelta
    tomorrow = datetime.now() + timedelta(days=1)
    tomorrow_date = tomorrow.date()
    
    # Get therapist's code
    # Get therapist code from profile
    therapist_code = None
    if hasattr(request.user, 'therapist_profile'):
        therapist_code = request.user.therapist_profile.therapist_code
    
    if not therapist_code:
        messages.warning(request, 'No therapist code assigned. Please contact administrator.')
        return redirect('patient:home')
    
    # Mock therapy sessions data (in real implementation, this would come from a TherapySession model)
    therapy_sessions = [
        {
            'time': '09:00 AM',
            'patient_name': 'John Doe',
            'patient_registration': 'REG001',
            'therapy_type': 'Oil Massage',
            'room': 'Room 101',
            'duration': '60 minutes',
            'status': 'Scheduled'
        },
        {
            'time': '10:30 AM',
            'patient_name': 'Jane Smith',
            'patient_registration': 'REG002',
            'therapy_type': 'Steam Therapy',
            'room': 'Room 102',
            'duration': '45 minutes',
            'status': 'Scheduled'
        },
        {
            'time': '02:00 PM',
            'patient_name': 'Bob Brown',
            'patient_registration': 'REG003',
            'therapy_type': 'Herbal Bath',
            'room': 'Room 103',
            'duration': '30 minutes',
            'status': 'Scheduled'
        },
        {
            'time': '03:30 PM',
            'patient_name': 'Alice Johnson',
            'patient_registration': 'REG004',
            'therapy_type': 'Oil Massage',
            'room': 'Room 101',
            'duration': '60 minutes',
            'status': 'Scheduled'
        }
    ]
    
    context = {
        'therapist_code': therapist_code,
        'schedule_date': tomorrow_date,
        'therapy_sessions': therapy_sessions,
        'total_sessions': len(therapy_sessions)
    }
    
    return render(request, 'dashboards/therapist/therapist_schedule.html', context)

@login_required
@super_admin_required
def Audit_Log(request):
    """Functional audit log view with filtering and pagination"""
    # Get filter parameters
    action_filter = request.GET.get('action', '')
    status_filter = request.GET.get('status', '')
    user_filter = request.GET.get('user', '')
    search_query = request.GET.get('search', '')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    
    # Check if any filters are applied
    has_filters = any([action_filter, status_filter, user_filter, search_query, date_from, date_to])
    
    # Start with all audit logs, but default to today's logs if no filters
    if not has_filters:
        # Default: Show only today's logs
        today = timezone.now().date()
        audit_logs = AuditLog.objects.filter(timestamp__date=today)
    else:
        audit_logs = AuditLog.objects.all()
    
    # Apply filters
    if action_filter:
        audit_logs = audit_logs.filter(action=action_filter)
    
    if status_filter:
        audit_logs = audit_logs.filter(status=status_filter)
    
    if user_filter:
        audit_logs = audit_logs.filter(user__username__icontains=user_filter)
    
    if search_query:
        audit_logs = audit_logs.filter(
            models.Q(description__icontains=search_query) |
            models.Q(user__username__icontains=search_query) |
            models.Q(object_type__icontains=search_query)
        )
    
    if date_from:
        try:
            from datetime import datetime
            date_from_obj = datetime.strptime(date_from, '%Y-%m-%d')
            audit_logs = audit_logs.filter(timestamp__date__gte=date_from_obj.date())
        except ValueError:
            pass
    
    if date_to:
        try:
            from datetime import datetime
            date_to_obj = datetime.strptime(date_to, '%Y-%m-%d')
            audit_logs = audit_logs.filter(timestamp__date__lte=date_to_obj.date())
        except ValueError:
            pass
    
    # Pagination
    paginator = Paginator(audit_logs, 50)  # Show 50 logs per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Get filter options for dropdowns
    actions = AuditLog.ACTION_CHOICES
    statuses = AuditLog.STATUS_CHOICES
    users = CustomUser.objects.filter(auth_audit_logs__isnull=False).distinct().order_by('username')
    
    # Statistics
    total_logs = AuditLog.objects.count()
    today_logs = AuditLog.objects.filter(timestamp__date=timezone.now().date()).count()
    failed_logs = AuditLog.objects.filter(status='failed').count()
    
    context = {
        'page_obj': page_obj,
        'audit_logs': page_obj,
        'actions': actions,
        'statuses': statuses,
        'users': users,
        'total_logs': total_logs,
        'today_logs': today_logs,
        'failed_logs': failed_logs,
        'current_filters': {
            'action': action_filter,
            'status': status_filter,
            'user': user_filter,
            'search': search_query,
            'date_from': date_from,
            'date_to': date_to,
        }
    }
    
    return render(request, 'dashboards/superadmin/Audit_Log.html', context)

@login_required
@super_admin_required
def audit_log_api(request):
    """API endpoint to get all filtered audit logs for PDF generation"""
    from django.http import JsonResponse
    from django.core import serializers
    import json
    
    # Get filter parameters (same as Audit_Log view)
    action_filter = request.GET.get('action', '')
    status_filter = request.GET.get('status', '')
    user_filter = request.GET.get('user', '')
    search_query = request.GET.get('search', '')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    
    # Check if any filters are applied
    has_filters = any([action_filter, status_filter, user_filter, search_query, date_from, date_to])
    
    # Start with all audit logs, but default to today's logs if no filters
    if not has_filters:
        # Default: Show only today's logs
        today = timezone.now().date()
        audit_logs = AuditLog.objects.filter(timestamp__date=today)
    else:
        audit_logs = AuditLog.objects.all()
    
    # Apply filters (same logic as Audit_Log view)
    if action_filter:
        audit_logs = audit_logs.filter(action=action_filter)
    
    if status_filter:
        audit_logs = audit_logs.filter(status=status_filter)
    
    if user_filter:
        audit_logs = audit_logs.filter(user__username__icontains=user_filter)
    
    if search_query:
        audit_logs = audit_logs.filter(
            models.Q(description__icontains=search_query) |
            models.Q(user__username__icontains=search_query) |
            models.Q(object_type__icontains=search_query)
        )
    
    if date_from:
        try:
            from datetime import datetime
            date_from_obj = datetime.strptime(date_from, '%Y-%m-%d')
            audit_logs = audit_logs.filter(timestamp__date__gte=date_from_obj.date())
        except ValueError:
            pass
    
    if date_to:
        try:
            from datetime import datetime
            date_to_obj = datetime.strptime(date_to, '%Y-%m-%d')
            audit_logs = audit_logs.filter(timestamp__date__lte=date_to_obj.date())
        except ValueError:
            pass
    
    # Get all logs (no pagination for API)
    logs_data = []
    for log in audit_logs.select_related('user'):
        # Format additional_data for display
        additional_info = ''
        if log.additional_data:
            try:
                if isinstance(log.additional_data, dict):
                    if log.action == 'allocate_therapy':
                        additional_info = f"Patient: {log.additional_data.get('patient_reg_no', 'N/A')}, Therapy: {log.additional_data.get('therapy_name', 'N/A')}"
                    elif log.action == 'cancel_therapy':
                        additional_info = f"Patient: {log.additional_data.get('patient_reg_no', 'N/A')}, Therapy: {log.additional_data.get('therapy_name', 'N/A')}"
                    elif log.action == 'resume_therapy':
                        additional_info = f"Patient: {log.additional_data.get('patient_reg_no', 'N/A')}, Therapy: {log.additional_data.get('therapy_name', 'N/A')}"
                    elif log.action == 'update_therapy':
                        additional_info = f"Patient: {log.additional_data.get('patient_reg_no', 'N/A')}, Therapy: {log.additional_data.get('therapy_name', 'N/A')}"
                    elif log.action == 'remove_item':
                        additional_info = f"Patient: {log.additional_data.get('patient_reg_no', 'N/A')}, Therapy: {log.additional_data.get('therapy_name', 'N/A')}"
            except:
                pass
        
        object_info = ''
        if log.object_type:
            object_info = log.object_type
            if log.object_id:
                object_info += f" ({log.object_id})"
        
        logs_data.append({
            'id': log.id,
            'user': log.user.username if log.user else 'System',
            'user_role': log.user.get_role_display() if log.user else 'System',
            'action': log.get_action_display(),
            'description': log.description[:100] if log.description else '',  # Limit description length
            'object': object_info,
            'timestamp': log.timestamp.strftime('%b %d, %Y'),
            'time': log.timestamp.strftime('%H:%M:%S'),
            'ip_address': log.ip_address or '-',
            'status': log.get_status_display(),
            'additional_info': additional_info
        })
    
    return JsonResponse({
        'success': True,
        'data': logs_data,
        'count': len(logs_data)
    })

@login_required
@super_admin_required
def Therapy_Audit_Log(request):
    """Therapy-specific audit log view with filtering and pagination"""
    # Get filter parameters
    action_filter = request.GET.get('action', '')
    status_filter = request.GET.get('status', '')
    user_filter = request.GET.get('user', '')
    search_query = request.GET.get('search', '')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    
    # Start with therapy-related audit logs
    therapy_actions = ['allocate_therapy', 'update_therapy', 'cancel_therapy', 'resume_therapy', 'remove_item', 'view_therapy']
    audit_logs = AuditLog.objects.filter(action__in=therapy_actions)
    
    # Apply filters
    if action_filter:
        audit_logs = audit_logs.filter(action=action_filter)
    
    if status_filter:
        audit_logs = audit_logs.filter(status=status_filter)
    
    if user_filter:
        audit_logs = audit_logs.filter(user__username__icontains=user_filter)
    
    if search_query:
        audit_logs = audit_logs.filter(
            models.Q(description__icontains=search_query) |
            models.Q(user__username__icontains=search_query) |
            models.Q(object_type__icontains=search_query) |
            models.Q(additional_data__icontains=search_query)
        )
    
    if date_from:
        try:
            from datetime import datetime
            date_from_obj = datetime.strptime(date_from, '%Y-%m-%d')
            audit_logs = audit_logs.filter(timestamp__date__gte=date_from_obj.date())
        except ValueError:
            pass
    
    if date_to:
        try:
            from datetime import datetime
            date_to_obj = datetime.strptime(date_to, '%Y-%m-%d')
            audit_logs = audit_logs.filter(timestamp__date__lte=date_to_obj.date())
        except ValueError:
            pass
    
    # Pagination
    paginator = Paginator(audit_logs, 50)  # Show 50 logs per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Get filter options for dropdowns
    therapy_actions_choices = [choice for choice in AuditLog.ACTION_CHOICES if choice[0] in therapy_actions]
    statuses = AuditLog.STATUS_CHOICES
    users = CustomUser.objects.filter(auth_audit_logs__action__in=therapy_actions).distinct().order_by('username')
    
    # Statistics
    total_logs = audit_logs.count()
    allocate_count = audit_logs.filter(action='allocate_therapy').count()
    cancel_count = audit_logs.filter(action='cancel_therapy').count()
    resume_count = audit_logs.filter(action='resume_therapy').count()
    update_count = audit_logs.filter(action='update_therapy').count()
    remove_count = audit_logs.filter(action='remove_item').count()
    
    context = {
        'audit_logs': page_obj,
        'actions': therapy_actions_choices,
        'statuses': statuses,
        'users': users,
        'total_logs': total_logs,
        'allocate_count': allocate_count,
        'cancel_count': cancel_count,
        'resume_count': resume_count,
        'update_count': update_count,
        'remove_count': remove_count,
        'action_filter': action_filter,
        'status_filter': status_filter,
        'user_filter': user_filter,
        'search_query': search_query,
        'date_from': date_from,
        'date_to': date_to,
    }
    
    return render(request, 'dashboards/superadmin/Therapy_Audit_Log.html', context)

@login_required
def view_patient_details(request):
    """View patient details"""
    return render(request, 'dashboards/therapist/view_patient_details.html')

@login_required
def therapist_feedback_form(request):
    """Therapist feedback form"""
    return render(request, 'dashboards/therapist/therapist_feedback_form.html')

@login_required
def Therapy_Report(request):
    """Reports & Analytics view with therapy and prescription insights"""
    from Sheduling.models import TherapyAllocation, PrescriptionAllocation, Booking
    from Patient.models import TherapistBooking, RoomBooking
    from django.db.models import Count, Q, Sum, Avg
    from django.utils import timezone
    from datetime import timedelta, datetime
    import json
    
    # Get date range from request (default to last 30 days)
    end_date = timezone.now().date()
    start_date = end_date - timedelta(days=30)
    
    if request.GET.get('start_date'):
        try:
            start_date = datetime.strptime(request.GET.get('start_date'), '%Y-%m-%d').date()
        except:
            pass
    
    if request.GET.get('end_date'):
        try:
            end_date = datetime.strptime(request.GET.get('end_date'), '%Y-%m-%d').date()
        except:
            pass
    
    # Therapy Allocation Statistics
    therapy_allocations = TherapyAllocation.objects.filter(
        from_date__lte=end_date,
        to_date__gte=start_date
    )
    
    total_therapies = therapy_allocations.count()
    active_therapies = therapy_allocations.filter(status='allocated').count()
    cancelled_therapies = therapy_allocations.filter(status='cancelled').count()
    
    # Therapy by status
    therapy_by_status = therapy_allocations.values('status').annotate(count=Count('id')).order_by('status')
    therapy_status_data = {item['status']: item['count'] for item in therapy_by_status}
    
    # Top therapies
    top_therapies = therapy_allocations.values('therapy_name').annotate(
        count=Count('id')
    ).order_by('-count')[:10]
    
    # Therapy bookings statistics
    bookings = Booking.objects.filter(
        date__gte=start_date,
        date__lte=end_date
    )
    total_bookings = bookings.count()
    completed_bookings = bookings.filter(status='completed').count()
    cancelled_bookings = bookings.filter(status__in=['cancelled', 'partially_cancelled']).count()
    
    # Daily therapy bookings trend
    daily_bookings = bookings.values('date').annotate(count=Count('id')).order_by('date')
    daily_bookings_data = {
        'dates': [str(item['date']) for item in daily_bookings],
        'counts': [item['count'] for item in daily_bookings]
    }
    
    # Prescription Allocation Statistics
    prescription_allocations = PrescriptionAllocation.objects.filter(
        from_date__lte=end_date,
        to_date__gte=start_date
    )
    
    total_prescriptions = prescription_allocations.count()
    active_prescriptions = prescription_allocations.filter(status='active').count()
    cancelled_prescriptions = prescription_allocations.filter(status='cancelled').count()
    
    # Prescription by status
    prescription_by_status = prescription_allocations.values('status').annotate(count=Count('id')).order_by('status')
    prescription_status_data = {item['status']: item['count'] for item in prescription_by_status}
    
    # Therapist utilization
    therapist_bookings = TherapistBooking.objects.filter(
        date__gte=start_date,
        date__lte=end_date,
        status='BOOKED'
    )
    therapist_utilization = therapist_bookings.values('therapist__therapist_name').annotate(
        count=Count('id')
    ).order_by('-count')[:10]
    
    # Room utilization
    room_bookings = RoomBooking.objects.filter(
        date__gte=start_date,
        date__lte=end_date,
        status='BOOKED'
    )
    room_utilization = room_bookings.values('room__room_no').annotate(
        count=Count('id')
    ).order_by('-count')[:10]
    
    # Monthly trends (using Django's date truncation)
    from django.db.models.functions import TruncMonth
    monthly_therapy = therapy_allocations.annotate(
        month=TruncMonth('from_date')
    ).values('month').annotate(count=Count('id')).order_by('month')
    
    monthly_prescription = prescription_allocations.annotate(
        month=TruncMonth('from_date')
    ).values('month').annotate(count=Count('id')).order_by('month')
    
    # Average therapy duration
    avg_therapy_duration = therapy_allocations.aggregate(
        avg_days=Avg('days')
    )['avg_days'] or 0
    
    # Average prescription duration
    avg_prescription_duration = prescription_allocations.aggregate(
        avg_days=Avg('days')
    )['avg_days'] or 0
    
    # Convert QuerySets to lists for JSON serialization
    top_therapies_list = [{'therapy_name': t['therapy_name'], 'count': t['count']} for t in top_therapies]
    therapist_util_list = [{'therapist__therapist_name': t['therapist__therapist_name'] or 'Unknown', 'count': t['count']} for t in therapist_utilization]
    room_util_list = [{'room__room_no': r['room__room_no'] or 'Unknown', 'count': r['count']} for r in room_utilization]
    
    context = {
        'start_date': start_date,
        'end_date': end_date,
        'total_therapies': total_therapies,
        'active_therapies': active_therapies,
        'cancelled_therapies': cancelled_therapies,
        'therapy_status_data': json.dumps(therapy_status_data),
        'top_therapies': json.dumps(top_therapies_list),
        'total_bookings': total_bookings,
        'completed_bookings': completed_bookings,
        'cancelled_bookings': cancelled_bookings,
        'daily_bookings_data': json.dumps(daily_bookings_data),
        'total_prescriptions': total_prescriptions,
        'active_prescriptions': active_prescriptions,
        'cancelled_prescriptions': cancelled_prescriptions,
        'prescription_status_data': json.dumps(prescription_status_data),
        'therapist_utilization': json.dumps(therapist_util_list),
        'room_utilization': json.dumps(room_util_list),
        'avg_therapy_duration': round(avg_therapy_duration, 1),
        'avg_prescription_duration': round(avg_prescription_duration, 1),
    }
    
    return render(request, 'dashboards/reports/therapy_report.html', context)

@login_required
@role_required(['housekeeping_staff'])
def housekeepingdash(request):
    """Housekeeping dashboard"""
    return render(request, 'dashboards/Housekeeping Staff/housekeepingdash.html')

@login_required
def Patient_feedback_review(request):
    """Patient feedback review"""
    return render(request, 'dashboards/gm_hr/Patient_feedback_review.html')

@login_required
@role_required(['nurse'])
def nurse_dash(request):
    """Nurse dashboard"""
    return render(request, 'dashboards/Nurse/nurse_dash.html')

@login_required
@role_required(['ip_pharmacy_staff'])
def ip_pharmacy(request):
    """IP pharmacy dashboard"""
    return render(request, 'dashboards/ip_pharmacy/ip_pharmacy.html')

@login_required
def prescription_dash(request):
    """Prescription dashboard"""
    return render(request, 'dashboards/prescriptions/prescription_dash.html')

@login_required
def patient_profile(request):
    """Patient profile"""
    return render(request, 'dashboards/patient/patient_profile.html')

@login_required
def user_profile(request):
    """User Profile Dashboard: view and edit basic profile details"""
    user = request.user
    validation_errors = {}
    
    if request.method == 'POST':
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        email = request.POST.get('email', '').strip()
        mobile = request.POST.get('mobile', '').strip()
        # Only set to None if mobile is empty string, otherwise keep the value
        mobile = mobile if mobile else None

        profile_picture_updated = False
        profile_picture_valid = False
        
        # Handle profile picture upload (process separately so it can be saved even if other validations fail)
        if 'profile_picture' in request.FILES:
            profile_picture = request.FILES['profile_picture']
            # Validate file size (max 5MB)
            if profile_picture.size > 5 * 1024 * 1024:
                messages.error(request, 'Profile picture size should be less than 5MB.')
            else:
                # Validate file type
                allowed_types = ['image/jpeg', 'image/jpg', 'image/png', 'image/gif']
                if profile_picture.content_type not in allowed_types:
                    messages.error(request, 'Invalid file type. Please upload a JPEG, PNG, or GIF image.')
                else:
                    # Delete old profile picture if exists
                    if user.profile_picture:
                        try:
                            import os
                            if os.path.isfile(user.profile_picture.path):
                                os.remove(user.profile_picture.path)
                        except Exception:
                            pass  # Ignore errors when deleting old file
                    user.profile_picture = profile_picture
                    profile_picture_updated = True
                    profile_picture_valid = True

        # Basic validations
        if not email:
            validation_errors['email'] = 'Email is required.'
            # If profile picture was uploaded, save it separately
            if profile_picture_valid:
                try:
                    user.save(update_fields=['profile_picture'])
                    messages.success(request, 'Profile picture updated successfully.')
                except Exception as e:
                    messages.error(request, f'Error saving profile picture: {str(e)}')
        else:
            # Check if email is being changed and if it already exists
            if email != user.email:
                from django.contrib.auth import get_user_model
                User = get_user_model()
                if User.objects.filter(email=email).exclude(pk=user.pk).exists():
                    validation_errors['email'] = 'A user with this email already exists.'
            
            # Check if mobile is being changed and if it already exists (only if mobile is provided)
            if mobile and mobile != user.mobile:
                from django.contrib.auth import get_user_model
                User = get_user_model()
                if User.objects.filter(mobile=mobile).exclude(pk=user.pk).exists():
                    validation_errors['mobile'] = 'A user with this mobile number already exists.'
            
            # If there are validation errors, show them
            if validation_errors:
                for field, error_msg in validation_errors.items():
                    messages.error(request, f"{field.capitalize()}: {error_msg}")
                
                # If profile picture was updated but other validations failed, save just the picture
                if profile_picture_valid:
                    try:
                        user.save(update_fields=['profile_picture'])
                        messages.warning(request, 'Profile picture updated, but other fields have errors.')
                    except Exception as pic_error:
                        messages.error(request, f'Error saving profile picture: {str(pic_error)}')
            else:
                # Assign and save with model-level validation for unique mobile
                user.first_name = first_name
                user.last_name = last_name
                user.email = email
                user.mobile = mobile
                try:
                    user.full_clean()
                    user.save()
                    if profile_picture_updated:
                        messages.success(request, 'Profile and picture updated successfully.')
                    else:
                        messages.success(request, 'Profile updated successfully.')
                except ValidationError as e:
                    # If profile picture was updated but other validations failed, save just the picture
                    if profile_picture_valid:
                        try:
                            # Save only the profile picture
                            user.save(update_fields=['profile_picture'])
                            messages.warning(request, 'Profile picture updated, but other fields have errors.')
                        except Exception as pic_error:
                            messages.error(request, f'Error saving profile picture: {str(pic_error)}')
                    
                    # Show validation errors
                    for field, errors in e.message_dict.items():
                        for err in errors:
                            validation_errors[field] = err
                            messages.error(request, f"{field.capitalize()}: {err}")

    # Refresh user from database to ensure we have the latest data including profile picture
    user.refresh_from_db()
    
    context = {
        'user_obj': user,
        'validation_errors': validation_errors,
    }
    return render(request, 'dashboards/account/user_profile.html', context)

@login_required
@role_required(['doctor', 'scheduling_staff'])
def add_therapy_with_autofill(request):
    """Add therapy dashboard with auto-fill patient details"""
    try:
        from masters.models import ItemMaster, TherapyMaster, SlotMaster
        all_therapy_items = ItemMaster.objects.filter(is_active=True).all()[:100]  # Use local master table
        all_therapies = TherapyMaster.objects.filter(is_active=True).all()[:100]  # Use local therapy master
        all_slots = SlotMaster.objects.filter(is_active=True).all()[:100]  # Use local slot master
    except Exception as e:
        print(f"Error loading master data: {e}")
        all_therapy_items = []
        all_therapies = []
        all_slots = []
    
    context = {
        'all_therapy_items': all_therapy_items,
        'all_therapies': all_therapies,
        'all_slots': all_slots
    }
    return render(request, 'dashboards/prescriptions/therapy_entry.html', context)

@login_required
def search_patients(request):
    """API endpoint to search patients by registration number"""
    if request.method != 'GET':
        return JsonResponse({'error': 'Only GET method allowed'}, status=405)
    
    query = request.GET.get('q', '').strip()
    is_initial_load = request.GET.get('initial', 'false').lower() == 'true'
    
    print(f"[DEBUG] search_patients called - query: '{query}', is_initial_load: {is_initial_load}")
    
    try:
        from MySql_Data_pull.models import Registration, OPMaster
        from Patient.models import Repeated_Visitors
        from datetime import datetime, timedelta
        from django.utils import timezone
        
        patients = []
        
        # Search in IP patients (Registration table)
        # SQL Server doesn't support regex, so we filter in Python after fetching
        try:
            from django.db.models import Q
            ip_patients_list = []
            
            if is_initial_load:
                # Fetch patients and filter by registration number length in Python
                try:
                    # Fetch with status filter first
                    all_patients = Registration.objects.using('therapy_db').filter(
                        pat_status='Y'
                    ).values(
                        'pat_reg_no', 'pat_name', 'pat_sex', 'pat_age', 'pat_room_no', 'pat_ref_id', 'pat_visit_date'
                    ).order_by('-pat_visit_date')[:20]  # Fetch 20, filter to 5 IP patients
                    
                    for p in all_patients:
                        reg_no_str = str(p['pat_reg_no']).strip() if p['pat_reg_no'] else ''
                        digits_only = ''.join(ch for ch in reg_no_str if ch.isdigit())
                        # IP patients: NOT 5 digits (OP patients have exactly 5 digits)
                        if len(digits_only) != 5:
                            ip_patients_list.append(p)
                            if len(ip_patients_list) >= 5:
                                break
                    
                    if not ip_patients_list:
                        # Try without status filter
                        all_patients = Registration.objects.using('therapy_db').all().values(
                            'pat_reg_no', 'pat_name', 'pat_sex', 'pat_age', 'pat_room_no', 'pat_ref_id', 'pat_visit_date'
                        ).order_by('-pat_visit_date')[:20]
                        for p in all_patients:
                            reg_no_str = str(p['pat_reg_no']).strip() if p['pat_reg_no'] else ''
                            digits_only = ''.join(ch for ch in reg_no_str if ch.isdigit())
                            if len(digits_only) != 5:
                                ip_patients_list.append(p)
                                if len(ip_patients_list) >= 5:
                                    break
                    
                    print(f"[DEBUG] Initial load - Found {len(ip_patients_list)} IP patients")
                except Exception as e:
                    print(f"[DEBUG] Error in IP query: {e}")
                    import traceback
                    traceback.print_exc()
            elif query:
                # If query is provided, search by registration number and patient name only
                try:
                    # Build Q object for search - only search by name and reg no
                    search_q = Q(pat_reg_no__icontains=query) | Q(pat_name__icontains=query)
                    
                    all_patients = Registration.objects.using('therapy_db').filter(
                        search_q,
                        pat_status='Y'
                    ).values(
                        'pat_reg_no', 'pat_name', 'pat_sex', 'pat_age', 'pat_room_no', 'pat_ref_id', 'pat_visit_date'
                    ).order_by('-pat_visit_date')[:100]
                    
                    for p in all_patients:
                        reg_no_str = str(p['pat_reg_no']).strip() if p['pat_reg_no'] else ''
                        digits_only = ''.join(ch for ch in reg_no_str if ch.isdigit())
                        if len(digits_only) != 5:  # Not OP (5 digits)
                            ip_patients_list.append(p)
                    
                    if not ip_patients_list:
                        # Try without status filter
                        # Build Q object for search - only search by name and reg no
                        search_q = Q(pat_reg_no__icontains=query) | Q(pat_name__icontains=query)
                        
                        all_patients = Registration.objects.using('therapy_db').filter(
                            search_q
                        ).values(
                            'pat_reg_no', 'pat_name', 'pat_sex', 'pat_age', 'pat_room_no', 'pat_ref_id', 'pat_visit_date'
                        ).order_by('-pat_visit_date')[:100]
                        for p in all_patients:
                            reg_no_str = str(p['pat_reg_no']).strip() if p['pat_reg_no'] else ''
                            digits_only = ''.join(ch for ch in reg_no_str if ch.isdigit())
                            if len(digits_only) != 5:
                                ip_patients_list.append(p)
                    
                    print(f"[DEBUG] Query search - Found {len(ip_patients_list)} IP patients for query: '{query}'")
                except Exception as e:
                    print(f"[DEBUG] Error in IP query search: {e}")
                    import traceback
                    traceback.print_exc()
            else:
                ip_patients_list = []
            
            for patient in ip_patients_list:
                # Check VIP status
                vip_status = False
                try:
                    repeated_visitor = Repeated_Visitors.objects.get(
                        register_number=patient['pat_reg_no']
                    )
                    vip_status = repeated_visitor.total_visits > 2
                except (Repeated_Visitors.DoesNotExist, Exception):
                    vip_status = False
                
                try:
                    mapped_room = get_staying_room_display_number(patient['pat_room_no'])
                except Exception:
                    mapped_room = patient['pat_room_no'] if patient.get('pat_room_no') else None
                
                patients.append({
                    'registration_number': patient['pat_reg_no'],
                    'patient_name': patient['pat_name'],
                    'sex': patient['pat_sex'],
                    'age': patient['pat_age'],
                    'room_number': mapped_room,
                    'ip_number': patient['pat_reg_no'],
                    'pat_ref_id': patient.get('pat_ref_id'),
                    'phone': None,  # Not fetched
                    'email': None,  # Not fetched
                    'registration_date': None,  # Not fetched
                    'patient_type': 'IP',
                    'is_vip': vip_status,
                    'source': 'IP'
                })
        except Exception as e:
            print(f"Error searching IP patients: {e}")
            import traceback
            traceback.print_exc()
        
        # Search in OP patients (OPMaster table)
        # Note: OPMaster uses Reg_Date as registration date
        try:
            from django.db.models import Q
            # If initial load (clicking search bar), show 10 most recent OP patients
            if is_initial_load:
                op_patients = OPMaster.objects.using('hospital_db').all().values(
                    'NPat_Reg_No', 'NPat_Name', 'NPat_Sex', 'Reg_Date'
                ).order_by('-Reg_Date')[:5]  # Limit to 5 OP patients for initial load (will combine with IP)
                print(f"[DEBUG] Initial load - Found {len(list(op_patients))} OP patients")
            elif query:
                # If query is provided (any length), search by both registration number and patient name
                op_patients = OPMaster.objects.using('hospital_db').filter(
                    Q(NPat_Reg_No__icontains=query) | Q(NPat_Name__icontains=query)
                ).values(
                    'NPat_Reg_No', 'NPat_Name', 'NPat_Sex', 'Reg_Date'
                ).order_by('-Reg_Date')[:100]  # Order by most recent, limit to 100
                print(f"[DEBUG] Query search - Found {len(list(op_patients))} OP patients for query: '{query}'")
            else:
                # Empty query (not initial load), return empty
                op_patients = []
                print(f"[DEBUG] Empty query (not initial load) - returning empty OP patients")
            
            for patient in op_patients:
                # Check VIP status
                vip_status = False
                try:
                    repeated_visitor = Repeated_Visitors.objects.get(
                        register_number=patient['NPat_Reg_No']
                    )
                    vip_status = repeated_visitor.total_visits > 2
                except Repeated_Visitors.DoesNotExist:
                    vip_status = False
                
                # Determine patient type: OP patients have 5-digit registration numbers
                reg_no_str = str(patient['NPat_Reg_No']).strip()
                # Remove any non-digit characters to check length
                digits_only = ''.join(ch for ch in reg_no_str if ch.isdigit())
                # OP patients have exactly 5 digits
                patient_type = 'OP' if len(digits_only) == 5 else 'IP'
                
                # Only add OP patients (exclude any IP patients that might be in OPMaster table)
                if patient_type == 'OP':
                    patients.append({
                        'registration_number': patient['NPat_Reg_No'],
                        'patient_name': patient['NPat_Name'],
                        'sex': patient['NPat_Sex'],
                        'age': None,  # OP patients don't have age in this table
                        'room_number': None,  # OP patients don't have room number
                        'ip_number': None,  # OP patients don't have IP number
                        'pat_ref_id': None,  # OP patients don't have pat_ref_id
                        'phone': None,  # OP patients don't have phone in this table
                        'email': None,  # OP patients don't have email in this table
                        'registration_date': patient['Reg_Date'].strftime('%Y-%m-%d') if patient['Reg_Date'] else None,
                        'patient_type': 'OP',
                        'is_vip': vip_status,
                        'source': 'OP'
                    })
        except Exception as e:
            print(f"Error searching OP patients: {e}")
        
        # Remove duplicates based on registration number
        seen_reg_nos = set()
        unique_patients = []
        for patient in patients:
            if patient['registration_number'] not in seen_reg_nos:
                seen_reg_nos.add(patient['registration_number'])
                unique_patients.append(patient)
        
        # Sort combined results by date (most recent first)
        # Use registration_date or visit_date for sorting
        def get_sort_date(patient):
            # Try to get a date for sorting
            if patient.get('registration_date'):
                try:
                    from datetime import datetime
                    return datetime.strptime(patient['registration_date'], '%Y-%m-%d')
                except:
                    pass
            # Fallback to current date if no date available
            from datetime import datetime
            return datetime.now()
        
        unique_patients.sort(key=get_sort_date, reverse=True)
        
        # For initial load, return exactly 10 patients; otherwise return up to 20
        limit = 10 if is_initial_load else 20
        
        print(f"[DEBUG] Returning {len(unique_patients[:limit])} patients (limit: {limit}, total found: {len(unique_patients)})")
        
        return JsonResponse({
            'patients': unique_patients[:limit],
            'total_found': len(unique_patients)
        })
        
    except Exception as e:
        return JsonResponse({
            'error': f'Search failed: {str(e)}',
            'patients': []
        }, status=500)

@login_required
def search_patients_by_room(request):
    """API endpoint to search patients by room number"""
    if request.method != 'GET':
        return JsonResponse({'error': 'Only GET method allowed'}, status=405)
    
    room_query = request.GET.get('room', '').strip()
    
    if not room_query:
        return JsonResponse({
            'error': 'Room number required',
            'patients': []
        }, status=400)
    
    print(f"[DEBUG] search_patients_by_room called - room: '{room_query}'")
    
    try:
        from MySql_Data_pull.models import Registration, OPMaster, Treatment
        from Patient.models import Repeated_Visitors
        from masters.models import get_staying_room_display_number, StayingRoom
        
        patients = []
        
        # Try to convert room query to integer for direct match
        room_query_int = None
        try:
            room_query_int = int(room_query)
        except (ValueError, TypeError):
            pass
        
        # Get current date for filtering active patients only
        from datetime import date
        today = date.today()
        
        # Search in Treatment table first (handles both IP and OP patients with room numbers like "CT-16", "OP-1")
        treatment_patients = []
        try:
            from django.db.models import Q
            
            # Search Treatment table by Pat_Room_No (CharField - can store "CT-16", "OP-1" directly)
            # Treatment table is in iptherapy_db, not therapy_db
            # Filter only active patients for current date:
            # - Pat_DoD (Date of Discharge) is null (not discharged) OR Pat_DoD >= today (discharged today or future)
            # - DOA (Date of Admission) <= today (admitted today or earlier)
            from datetime import datetime
            today_start = datetime.combine(today, datetime.min.time())
            
            treatment_records = Treatment.objects.using('iptherapy_db').filter(
                Pat_Room_No__iexact=room_query
            ).filter(
                Q(Pat_DoD__isnull=True) | Q(Pat_DoD__date__gte=today)
            ).filter(
                Q(DOA__isnull=True) | Q(DOA__date__lte=today)
            ).values('Pat_Reg_No', 'Pat_Room_No', 'Pat_Name', 'Pat_Sex', 'Pat_Age', 'DOA', 'Pat_DoD').distinct()[:100]
            
            print(f"[DEBUG] Found {len(list(treatment_records))} treatment records for room: '{room_query}'")
            
            for treatment in treatment_records:
                reg_no = treatment['Pat_Reg_No']
                treatment_patients.append({
                    'reg_no': reg_no,
                    'room_no': treatment.get('Pat_Room_No'),
                    'name': treatment.get('Pat_Name'),
                    'sex': treatment.get('Pat_Sex'),
                    'age': treatment.get('Pat_Age'),
                    'source': 'treatment'
                })
        except Exception as e:
            print(f"[DEBUG] Error searching Treatment table: {e}")
            import traceback
            traceback.print_exc()
        
        # Also search PatientSnapshot table (has room numbers stored directly as CharField)
        snapshot_patients = []
        snapshot_room_numbers_to_search = [room_query]  # Start with the original query
        
        # Check if StayingRoom has a mapping (e.g., "OP-1" -> "76")
        try:
            staying_room = StayingRoom.objects.filter(
                room_no__iexact=room_query
            ).first()
            
            if staying_room and staying_room.number:
                # Add the mapped number to search list
                snapshot_room_numbers_to_search.append(staying_room.number)
                print(f"[DEBUG] StayingRoom mapping found: {room_query} -> {staying_room.number}")
        except Exception:
            pass
        
        try:
            from Sheduling.models import PatientSnapshot
            from django.db.models import Q
            
            # Search PatientSnapshot by pat_room_no (can store "CT-16", "OP-1" directly or mapped numbers)
            snapshot_q = Q()
            for room_num in snapshot_room_numbers_to_search:
                snapshot_q |= Q(pat_room_no__iexact=room_num)
            
            snapshot_records_list = list(PatientSnapshot.objects.filter(
                snapshot_q
            ).values('pat_reg_no', 'pat_room_no', 'pat_name', 'pat_sex', 'pat_age')[:100])
            
            # Filter snapshot records to include patients currently in room
            # by cross-referencing with Registration table (IP) or OPMaster (OP)
            active_snapshot_records = []
            from datetime import timedelta
            thirty_days_ago = today - timedelta(days=30)
            
            for snapshot in snapshot_records_list:
                reg_no = snapshot['pat_reg_no']
                is_active = False
                
                # Determine if patient is OP (5-digit registration number) or IP
                reg_no_str = str(reg_no).strip()
                digits_only = ''.join(ch for ch in reg_no_str if ch.isdigit())
                is_op_patient = len(digits_only) == 5
                
                try:
                    if is_op_patient:
                        # OP patient - check OPMaster table
                        # OP patients don't have visit dates, so check if they exist and have recent registration
                        op_patient = OPMaster.objects.using('hospital_db').filter(
                            NPat_Reg_No=reg_no
                        ).first()
                        
                        if op_patient:
                            # Check if registration date is within last 30 days (recent OP patient)
                            if op_patient.Reg_Date:
                                reg_date = op_patient.Reg_Date.date() if hasattr(op_patient.Reg_Date, 'date') else op_patient.Reg_Date
                                if reg_date >= thirty_days_ago:
                                    is_active = True
                            else:
                                # If no registration date, include them (they might be active)
                                is_active = True
                    else:
                        # IP patient - check Registration table
                        active_reg = Registration.objects.using('therapy_db').filter(
                            pat_reg_no=reg_no,
                            pat_status='Y',
                            pat_visit_date__date__gte=thirty_days_ago  # Patients who visited within last 30 days
                        ).exists()
                        if active_reg:
                            is_active = True
                except Exception as e:
                    # If can't check, skip it (only show active patients)
                    print(f"[DEBUG] Error checking patient {reg_no}: {e}")
                    pass
                
                if is_active:
                    active_snapshot_records.append(snapshot)
            
            print(f"[DEBUG] Found {len(active_snapshot_records)} active PatientSnapshot records for room: '{room_query}' (filtered for recent visits - includes OP and IP)")
            
            for snapshot in active_snapshot_records:
                reg_no = snapshot['pat_reg_no']
                # Skip if already in treatment_patients
                if not any(tp['reg_no'] == reg_no for tp in treatment_patients):
                    snapshot_patients.append({
                        'reg_no': reg_no,
                        'room_no': snapshot.get('pat_room_no'),
                        'name': snapshot.get('pat_name'),
                        'sex': snapshot.get('pat_sex'),
                        'age': snapshot.get('pat_age'),
                        'source': 'snapshot'
                    })
        except Exception as e:
            print(f"[DEBUG] Error searching PatientSnapshot table: {e}")
            import traceback
            traceback.print_exc()
        
        # Search in IP patients (Registration table) by room number
        try:
            from django.db.models import Q
            
            ip_patients_list = []
            room_numbers_to_search = []
            
            # First, try to find StayingRoom by display format (e.g., "CT-16", "OP-1")
            # This handles searches like "CT-16", "OP-1", etc.
            staying_room = StayingRoom.objects.filter(
                room_no__iexact=room_query
            ).first()
            
            if staying_room:
                # Found a match in StayingRoom, get the number field (stored in DB)
                try:
                    room_db_number = int(staying_room.number)
                    room_numbers_to_search.append(room_db_number)
                    print(f"[DEBUG] Found StayingRoom: {staying_room.room_no} -> number: {staying_room.number}")
                except (ValueError, TypeError):
                    pass
            
            # Also try to find by number field directly (in case user searches by the stored number)
            staying_room_by_number = StayingRoom.objects.filter(
                number__iexact=room_query
            ).first()
            
            if staying_room_by_number:
                try:
                    room_db_number = int(staying_room_by_number.number)
                    if room_db_number not in room_numbers_to_search:
                        room_numbers_to_search.append(room_db_number)
                    print(f"[DEBUG] Found StayingRoom by number: {staying_room_by_number.number}")
                except (ValueError, TypeError):
                    pass
            
            # If it's a pure integer and not found in StayingRoom, search directly
            if room_query_int is not None and not room_numbers_to_search:
                room_numbers_to_search.append(room_query_int)
            
            # Build search query
            if room_numbers_to_search:
                # Search by all found room numbers - show patients currently in the room
                search_q = Q(pat_room_no__in=room_numbers_to_search)
                
                # Show patients who are currently in the room (not just visited today)
                # Criteria: 
                # 1. Has room number assigned
                # 2. Visit date is within last 30 days (reasonable stay period) OR
                # 3. Has active therapies/bookings for today or future
                from datetime import datetime, timedelta
                from django.db.models import Q
                
                # Get date range for recent visits (last 30 days to cover current stays)
                thirty_days_ago = today - timedelta(days=30)
                
                # Filter: visit date within last 30 days (covers patients currently staying)
                search_q &= Q(pat_visit_date__date__gte=thirty_days_ago)
                
                ip_patients_list = Registration.objects.using('therapy_db').filter(
                    search_q,
                    pat_status='Y'
                ).values(
                    'pat_reg_no', 'pat_name', 'pat_sex', 'pat_age', 'pat_room_no', 'pat_ref_id', 'pat_visit_date', 'pat_room_date'
                ).order_by('-pat_visit_date', '-pat_room_date')[:100]
                
                # Further filter: Check if patients have active therapies/bookings for today or future
                # This ensures we show patients who are actively being treated
                from Sheduling.models import TherapyAllocation, Booking
                active_patient_reg_nos = set()
                
                # Check TherapyAllocation for active therapies (covering today or future)
                try:
                    active_therapies = TherapyAllocation.objects.filter(
                        from_date__lte=today,  # Therapy started on or before today
                        to_date__gte=today,    # Therapy ends on or after today
                        status__in=['allocated', 'draft']  # Active statuses
                    ).select_related('patient')
                    
                    for therapy in active_therapies:
                        if therapy.patient and therapy.patient.pat_reg_no:
                            # Add both as string and as-is to handle different formats
                            reg_no_str = str(therapy.patient.pat_reg_no)
                            active_patient_reg_nos.add(reg_no_str)
                            # Also add the original value in case it's stored differently
                            try:
                                if hasattr(therapy.patient.pat_reg_no, '__str__'):
                                    active_patient_reg_nos.add(therapy.patient.pat_reg_no)
                            except:
                                pass
                except Exception as e:
                    print(f"[DEBUG] Error checking active therapies: {e}")
                    pass
                
                # Check Booking for active bookings (today or future)
                try:
                    active_bookings = Booking.objects.filter(
                        date__gte=today,
                        status__in=['scheduled', 'draft']
                    ).select_related('allocation__patient')
                    
                    for booking in active_bookings:
                        if booking.allocation and booking.allocation.patient and booking.allocation.patient.pat_reg_no:
                            # Add both as string and as-is to handle different formats
                            reg_no_str = str(booking.allocation.patient.pat_reg_no)
                            active_patient_reg_nos.add(reg_no_str)
                            # Also add the original value in case it's stored differently
                            try:
                                if hasattr(booking.allocation.patient.pat_reg_no, '__str__'):
                                    active_patient_reg_nos.add(booking.allocation.patient.pat_reg_no)
                            except:
                                pass
                except Exception as e:
                    print(f"[DEBUG] Error checking active bookings: {e}")
                    pass
                
                # Convert ip_patients_list to list for manipulation
                ip_patients_list = list(ip_patients_list)
                
                # Prioritize patients with active therapies/bookings, then show most recent
                if active_patient_reg_nos:
                    # Separate into active and others
                    active_patients = [p for p in ip_patients_list if str(p['pat_reg_no']) in active_patient_reg_nos]
                    other_patients = [p for p in ip_patients_list if str(p['pat_reg_no']) not in active_patient_reg_nos]
                    # Show active patients first, then most recent others
                    ip_patients_list = active_patients + other_patients[:50]
                else:
                    # No active therapies found, show most recent patients in room (already ordered by -pat_visit_date)
                    ip_patients_list = ip_patients_list[:50]
            else:
                # No valid room number found
                ip_patients_list = []
                print(f"[DEBUG] No matching room found for query: '{room_query}'")
            
            for patient in ip_patients_list:
                # Check VIP status
                vip_status = False
                try:
                    repeated_visitor = Repeated_Visitors.objects.get(
                        register_number=patient['pat_reg_no']
                    )
                    vip_status = repeated_visitor.total_visits > 2
                except (Repeated_Visitors.DoesNotExist, Exception):
                    vip_status = False
                
                # Get mapped room number for display
                try:
                    mapped_room = get_staying_room_display_number(patient['pat_room_no'])
                except Exception:
                    mapped_room = patient['pat_room_no'] if patient.get('pat_room_no') else None
                
                patients.append({
                    'registration_number': patient['pat_reg_no'],
                    'patient_name': patient['pat_name'],
                    'sex': patient['pat_sex'],
                    'age': patient['pat_age'],
                    'room_number': mapped_room,
                    'ip_number': patient['pat_reg_no'],
                    'pat_ref_id': patient.get('pat_ref_id'),
                    'phone': None,
                    'email': None,
                    'registration_date': None,
                    'patient_type': 'IP',
                    'is_vip': vip_status,
                    'source': 'IP'
                })
        except Exception as e:
            print(f"Error searching IP patients by room: {e}")
            import traceback
            traceback.print_exc()
        
        # Process patients from Treatment table and PatientSnapshot (includes both IP and OP)
        # Get unique registration numbers to avoid duplicates
        all_patient_sources = treatment_patients + snapshot_patients
        treatment_reg_nos = set()
        for tp in all_patient_sources:
            treatment_reg_nos.add(tp['reg_no'])
        
        # Fetch patient details from Registration or OPMaster
        for reg_no in treatment_reg_nos:
            # Skip if already added from IP search
            if any(p.get('registration_number') == reg_no for p in patients):
                continue
            
            try:
                # Try to find in IP patients (Registration table) - show patients currently in room
                ip_patient = None
                try:
                    from datetime import timedelta
                    thirty_days_ago = today - timedelta(days=30)
                    
                    # Show patients with visit date within last 30 days (currently staying)
                    ip_patient = Registration.objects.using('therapy_db').filter(
                        pat_reg_no=reg_no,
                        pat_visit_date__date__gte=thirty_days_ago  # Patients who visited within last 30 days
                    ).values(
                        'pat_reg_no', 'pat_name', 'pat_sex', 'pat_age', 'pat_room_no', 'pat_ref_id', 'pat_visit_date'
                    ).order_by('-pat_visit_date').first()
                except Exception:
                    pass
                
                if ip_patient:
                    # IP patient found
                    vip_status = False
                    try:
                        repeated_visitor = Repeated_Visitors.objects.get(
                            register_number=ip_patient['pat_reg_no']
                        )
                        vip_status = repeated_visitor.total_visits > 2
                    except (Repeated_Visitors.DoesNotExist, Exception):
                        vip_status = False
                    
                    # Get room number from treatment, snapshot, or registration
                    room_no = None
                    for tp in all_patient_sources:
                        if tp['reg_no'] == reg_no:
                            room_no = tp.get('room_no')
                            break
                    
                    if not room_no:
                        room_no = ip_patient.get('pat_room_no')
                    
                    # Get mapped room number for display
                    try:
                        if room_no:
                            mapped_room = get_staying_room_display_number(room_no)
                        else:
                            mapped_room = None
                    except Exception:
                        mapped_room = room_no
                    
                    patients.append({
                        'registration_number': ip_patient['pat_reg_no'],
                        'patient_name': ip_patient['pat_name'],
                        'sex': ip_patient['pat_sex'],
                        'age': ip_patient['pat_age'],
                        'room_number': mapped_room or room_no,
                        'ip_number': ip_patient['pat_reg_no'],
                        'pat_ref_id': ip_patient.get('pat_ref_id'),
                        'phone': None,
                        'email': None,
                        'registration_date': None,
                        'patient_type': 'IP',
                        'is_vip': vip_status,
                        'source': 'IP'
                    })
                else:
                    # Try to find in OP patients (OPMaster table)
                    op_patient = None
                    try:
                        op_patient = OPMaster.objects.using('hospital_db').filter(
                            NPat_Reg_No=reg_no
                        ).values(
                            'NPat_Reg_No', 'NPat_Name', 'NPat_Sex', 'Reg_Date'
                        ).first()
                    except Exception:
                        pass
                    
                    if op_patient:
                        # OP patient found
                        vip_status = False
                        try:
                            repeated_visitor = Repeated_Visitors.objects.get(
                                register_number=op_patient['NPat_Reg_No']
                            )
                            vip_status = repeated_visitor.total_visits > 2
                        except (Repeated_Visitors.DoesNotExist, Exception):
                            vip_status = False
                        
                        # Get room number from treatment or snapshot
                        room_no = None
                        for tp in all_patient_sources:
                            if tp['reg_no'] == reg_no:
                                room_no = tp.get('room_no')
                                break
                        
                        patients.append({
                            'registration_number': op_patient['NPat_Reg_No'],
                            'patient_name': op_patient['NPat_Name'],
                            'sex': op_patient['NPat_Sex'],
                            'age': None,
                            'room_number': room_no,
                            'ip_number': None,
                            'pat_ref_id': None,
                            'phone': None,
                            'email': None,
                            'registration_date': op_patient['Reg_Date'].strftime('%Y-%m-%d') if op_patient.get('Reg_Date') else None,
                            'patient_type': 'OP',
                            'is_vip': vip_status,
                            'source': 'OP'
                        })
            except Exception as e:
                print(f"[DEBUG] Error processing treatment patient {reg_no}: {e}")
                import traceback
                traceback.print_exc()
        
        # Sort by visit date (most recent first)
        def get_sort_date(patient):
            from datetime import datetime
            return datetime.now()  # Use current date as fallback
        
        patients.sort(key=get_sort_date, reverse=True)
        
        print(f"[DEBUG] Returning {len(patients)} patients for room: '{room_query}'")
        
        return JsonResponse({
            'patients': patients[:20],  # Limit to 20 results
            'total_found': len(patients)
        })
        
    except Exception as e:
        return JsonResponse({
            'error': f'Search failed: {str(e)}',
            'patients': []
        }, status=500)

@login_required
def get_patient_details(request):
    """API endpoint to get detailed patient information by registration number"""
    if request.method != 'GET':
        return JsonResponse({'error': 'Only GET method allowed'}, status=405)
    
    reg_no = request.GET.get('reg_no', '').strip()
    if not reg_no:
        return JsonResponse({'error': 'Registration number required'}, status=400)
    
    try:
        from MySql_Data_pull.models import Registration, OPMaster
        from Patient.models import Repeated_Visitors
        
        patient_details = None
        
        # Try to find in IP patients first
        try:
            print(reg_no)
            ip_patient = Registration.objects.using('therapy_db').get(pat_reg_no=reg_no)
            
            # Check VIP status
            vip_status = False
            try:
                repeated_visitor = Repeated_Visitors.objects.get(register_number=reg_no)
                vip_status = repeated_visitor.total_visits > 2
            except Repeated_Visitors.DoesNotExist:
                vip_status = False
            
            # Determine patient type
            patient_type = 'IP' if len(str(reg_no)) != 5 else 'OP'
            
            display_room_no = get_staying_room_display_number(ip_patient.pat_room_no)
            patient_details = {
                'registration_number': ip_patient.pat_reg_no,
                'patient_name': ip_patient.pat_name,
                'sex': ip_patient.pat_sex,
                'age': ip_patient.pat_age,
                'room_number': display_room_no,
                'ip_number': ip_patient.pat_reg_no,  # IP number same as registration
                'pat_ref_id': ip_patient.pat_ref_id,
                'phone': ip_patient.pat_ph_no,
                'email': ip_patient.pat_email,
                'registration_date': ip_patient.pat_reg_date.strftime('%Y-%m-%d') if ip_patient.pat_reg_date else None,
                'patient_type': patient_type,
                'is_vip': vip_status,
                'source': 'IP',
                'address': {
                    'add1': ip_patient.pat_add1,
                    'add2': ip_patient.pat_add2,
                    'add3': ip_patient.pat_add3,
                    'add4': ip_patient.pat_add4,
                    'add5': ip_patient.pat_add5,
                    'add6': ip_patient.pat_add6,
                },
                'marital_status': ip_patient.pat_marital_status,
                'occupation': ip_patient.pat_occup,
                'blood_group': ip_patient.pat_bgroup,
                'emergency_contact_name': ip_patient.e_contact_name,
                'emergency_contact_no': ip_patient.e_contact_no,
            }
        except Registration.DoesNotExist:
            pass
        
        # If not found in IP, try OP patients
        if not patient_details:
            try:
                
                op_patient = OPMaster.objects.using('hospital_db').filter(NPat_Reg_No=reg_no).first()
                
                if op_patient:
                    # Check VIP status
                    vip_status = False
                    try:
                        repeated_visitor = Repeated_Visitors.objects.get(register_number=reg_no)
                        vip_status = repeated_visitor.total_visits > 2
                    except Repeated_Visitors.DoesNotExist:
                        vip_status = False
                    
                    # Determine patient type
                    patient_type = 'OP' if len(str(reg_no)) == 5 else 'IP'
                    
                    # Fetch room number and age from Treatment model for OP patients
                    op_room_no = ''
                    op_age = None
                    try:
                        from MySql_Data_pull.models import Treatment
                        # Try to find treatment record - Pat_Reg_No is primary key (CharField)
                        # Only fetch Pat_Room_No and Pat_Age to avoid errors with other columns
                        reg_no_str = str(reg_no)
                        treatment = Treatment.objects.using('iptherapy_db').filter(
                            Pat_Reg_No=reg_no_str
                        ).only('Pat_Reg_No', 'Pat_Room_No', 'Pat_Age').first()
                        
                        if treatment:
                            if treatment.Pat_Room_No:
                                op_room_no = str(treatment.Pat_Room_No).strip()
                                print(f"[DEBUG] OP patient {reg_no} room number from Treatment: {op_room_no}")
                            if treatment.Pat_Age:
                                op_age = str(treatment.Pat_Age).strip()
                                print(f"[DEBUG] OP patient {reg_no} age from Treatment: {op_age}")
                        else:
                            print(f"[DEBUG] No Treatment record found for OP patient {reg_no}")
                    except Exception as e:
                        print(f"Error fetching OP patient details from Treatment model: {e}")
                        import traceback
                        traceback.print_exc()
                    
                    patient_details = {
                        'registration_number': op_patient.NPat_Reg_No,
                        'patient_name': op_patient.NPat_Name,
                        'sex': op_patient.NPat_Sex,
                        'age': op_age,  # Fetch from Treatment model
                        'room_number': op_room_no,  # Fetch from Treatment model
                        'ip_number': None,  # OP patients don't have IP number
                        'pat_ref_id': None,  # OP patients don't have pat_ref_id
                        'phone': None,  # OP patients don't have phone in this table
                        'email': None,  # OP patients don't have email in this table
                        'registration_date': op_patient.Reg_Date.strftime('%Y-%m-%d') if op_patient.Reg_Date else None,
                        'patient_type': patient_type,
                        'is_vip': vip_status,
                        'source': 'OP',
                        'address': {
                            'add1': op_patient.NPat_Add1,
                            'add2': op_patient.NPat_Add2,
                            'add3': op_patient.NPat_Add3,
                            'city': op_patient.NPat_City,
                        },
                    }
            except Exception as e:
                print(f"Error searching OP patients: {e}")
        
        if patient_details:
            return JsonResponse({'patient': patient_details})
        else:
            return JsonResponse({'error': 'Patient not found'}, status=404)
        
    except Exception as e:
        return JsonResponse({
            'error': f'Failed to get patient details: {str(e)}'
        }, status=500)

def _get_department_for_role(role):
    """Get department name based on role"""
    department_mapping = {
        'scheduling_staff': 'Scheduling',
        'ip_pharmacy_staff': 'Pharmacy',
        'imu_staff': 'IMU',
        'finance_staff': 'Finance',
        'hr': 'Human Resources',
        'housekeeping_staff': 'Housekeeping'
    }
    return department_mapping.get(role, 'General')

def _get_designation_for_role(role):
    """Get designation based on role"""
    designation_mapping = {
        'scheduling_staff': 'Scheduling Staff',
        'ip_pharmacy_staff': 'Pharmacy Staff',
        'imu_staff': 'IMU Staff',
        'finance_staff': 'Finance Staff',
        'hr': 'HR Staff',
        'housekeeping_staff': 'Housekeeping Staff'
    }
    return designation_mapping.get(role, 'Staff')

@super_admin_required
def confirm_role_change(request, user_id):
    """Show role change confirmation page with mandatory fields"""
    user = get_object_or_404(CustomUser, id=user_id)
    new_role = request.GET.get('new_role')
    
    if not new_role:
        messages.error(request, 'New role not specified.')
        return redirect('authentication:Manage_user')
    
    # Role display names
    role_display_names = {
        'patient': 'Patient',
        'therapist': 'Therapist',
        'doctor': 'Doctor',
        'admin': 'Admin',
        'super_admin': 'Super Admin',
        'nurse': 'Nurse',
        'scheduling_staff': 'Scheduling Staff',
        'ip_pharmacy_staff': 'IP Pharmacy Staff',
        'imu_staff': 'IMU Staff',
        'finance_staff': 'Finance Staff',
        'hr': 'HR Staff',
        'housekeeping_staff': 'Housekeeping Staff'
    }
    
    new_role_display = role_display_names.get(new_role, new_role)
    
    context = {
        'user': user,
        'new_role': new_role,
        'new_role_display': new_role_display
    }
    
    return render(request, 'authentication/role_change_confirmation.html', context)

@super_admin_required
def execute_role_change(request):
    """Execute the role change after confirmation"""
    if request.method != 'POST':
        messages.error(request, 'Invalid request method.')
        return redirect('authentication:Manage_user')
    
    user_id = request.POST.get('user_id')
    new_role = request.POST.get('new_role')
    
    if not user_id or not new_role:
        messages.error(request, f'Invalid request parameters. user_id: {user_id}, new_role: {new_role}')
        return redirect('authentication:Manage_user')
    
    user = get_object_or_404(CustomUser, id=user_id)
    
    # Update user role
    user.role = new_role
    user.save()
    
    # Delete all existing profiles and create new one
    from authentication.role_change_utils import delete_all_user_profiles, create_minimal_profile
    
    # Delete all existing profiles
    delete_all_user_profiles(user)
    
    # Prepare profile data for new role
    profile_data = {}
    
    if new_role == 'patient':
        profile_data['patient_reg_no'] = request.POST.get('patient_reg_no', f"PAT{user.id:06d}")
    elif new_role == 'therapist':
        profile_data['therapist_code'] = request.POST.get('therapist_code', f"TH{user.id:06d}")
        profile_data['employee_code'] = request.POST.get('employee_code', f"EMP{user.id:06d}")
    elif new_role == 'doctor':
        profile_data['doctor_id'] = request.POST.get('doctor_id', f"DOC{user.id:06d}")
        profile_data['specialization'] = request.POST.get('specialization', 'General Medicine')
        profile_data['department'] = request.POST.get('department', 'Medical')
        profile_data['qualification'] = request.POST.get('qualification', 'MBBS')
        profile_data['experience_years'] = request.POST.get('experience_years', 0)
    elif new_role in ['admin', 'super_admin']:
        profile_data['admin_id'] = request.POST.get('admin_id', f"ADM{user.id:06d}")
        profile_data['department'] = request.POST.get('department', 'Administration')
        profile_data['designation'] = request.POST.get('designation', 
            'Administrator' if new_role == 'admin' else 'Super Administrator')
    elif new_role == 'nurse':
        profile_data['nurse_id'] = request.POST.get('nurse_id', f"NUR{user.id:06d}")
        profile_data['department'] = request.POST.get('department', 'Nursing')
        profile_data['qualification'] = request.POST.get('qualification', 'B.Sc Nursing')
    elif new_role in ['scheduling_staff', 'ip_pharmacy_staff', 'imu_staff', 'finance_staff', 'hr', 'housekeeping_staff']:
        profile_data['staff_id'] = request.POST.get('staff_id', f"STF{user.id:06d}")
        profile_data['department'] = request.POST.get('department', 'General')
        profile_data['designation'] = request.POST.get('designation', 'Staff')
    
    # Create new profile
    try:
        print(f"DEBUG: Creating profile for user {user.id}, role {new_role}, data: {profile_data}")
        new_profile = create_minimal_profile(user, new_role, profile_data)
        if new_profile:
            messages.success(request, f'User role successfully changed to {new_role}. All previous data has been deleted.')
            print(f"DEBUG: Profile created successfully: {new_profile}")
        else:
            messages.error(request, 'Failed to create new profile.')
            print("DEBUG: Profile creation returned None")
    except Exception as e:
        messages.error(request, f'Error creating new profile: {str(e)}')
        print(f"DEBUG: Exception in profile creation: {str(e)}")
        import traceback
        traceback.print_exc()
    
    return redirect('authentication:Manage_user')