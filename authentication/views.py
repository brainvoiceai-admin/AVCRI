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
import json

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
    modules = Module.objects.filter(is_active=True).order_by('order', 'name')
    
    context = {
        'roles': roles,
        'modules': modules,
    }
    return render(request, 'authentication/role_management.html', context)

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
            return redirect('role_management')
        
        if Role.objects.filter(name=name).exists():
            messages.error(request, 'A role with this name already exists.')
            return redirect('role_management')
        
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
        return redirect('role_management')
    
    # GET request - show create role form
    modules = Module.objects.filter(is_active=True).order_by('order', 'name')
    context = {
        'modules': modules,
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
        return redirect('role_management')
    
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
        return redirect('role_management')
    
    role.delete()
    messages.success(request, f'Role "{role.display_name}" deleted successfully.')
    return redirect('role_management')

@login_required
@super_admin_required
def user_role_assignment(request):
    """View for Super Admin to assign custom roles to users"""
    users = CustomUser.objects.filter(is_active=True).order_by('username')
    roles = Role.objects.filter(is_active=True).order_by('name')
    
    if request.method == 'POST':
        user_id = request.POST.get('user_id')
        role_id = request.POST.get('role_id')
        
        user = get_object_or_404(CustomUser, id=user_id)
        role = get_object_or_404(Role, id=role_id) if role_id else None
        
        user.custom_role = role
        user.save()
        
        messages.success(request, f'Role assignment updated for {user.username}.')
        return redirect('user_role_assignment')
    
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
        
        return redirect('module_management')
    
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
    """Get the appropriate dashboard URL based on user role"""
    role_dashboard_mapping = {
        'super_admin': 'superadmindash',
        'admin': 'gmdash',  # Admin uses GM/HR dashboard
        'doctor': 'doctordash',
        'scheduling_staff': 'therapistadmindash',  # Scheduling staff dashboard
        'therapist': 'therapistdash',
        'nurse': 'nurse_dash',
        'patient': 'patientdash',
        'ip_pharmacy_staff': 'ip_pharmacy',
        'imu_staff': 'therapistadmindash',  # IMU staff uses scheduling dashboard
        'finance_staff': 'gmdash',  # Finance uses GM dashboard for reports
        'hr': 'gmdash',
        'housekeeping_staff': 'housekeepingdash',
    }
    
    # Get the dashboard URL for the user's role
    dashboard_name = role_dashboard_mapping.get(user.role, 'patientdash')  # Default to patient dashboard
    
    return dashboard_name

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
def superadmin_dashboard(request):
    """Super admin dashboard view"""
    return render(request, 'dashboards/superadmin/superadmin_dashboard.html')

@login_required
@role_required(['doctor'])
def medicin_prescription(request):
    """Medicine prescription view"""
    return render(request, 'dashboards/doctorsAndHelpDesk/medicin_prescription.html')

@login_required
@role_required(['patient'])
def Patient_dashboard(request):
    """Patient dashboard view"""
    return render(request, 'dashboards/patient/Patient_dashboard.html')

@login_required
def Tenants_dashboard(request):
    """Tenants dashboard view"""
    return render(request, 'dashboards/tenants/tenants_dashboard.html')

@login_required
def Helpdeskadmindash(request):
    """Helpdesk admin dashboard view"""
    return render(request, 'dashboards/helpdesk/helpdesk_dashboard.html')

@login_required
def medicin_prescription_table(request):
    """Medicine prescription table view"""
    return render(request, 'dashboards/doctorsAndHelpDesk/medicin_prescription_table.html')

@login_required
@super_admin_required
def Manage_user(request):
    """Enhanced user management view with module permissions"""
    users = CustomUser.objects.filter(is_active=True).order_by('username')
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
                        return redirect('Manage_user')
                elif role == 'therapist' and therapist_code:
                    from authentication.models import TherapistProfile
                    if TherapistProfile.objects.filter(therapist_code=therapist_code).exists():
                        messages.error(request, f'Therapist code "{therapist_code}" already exists.')
                        return redirect('Manage_user')
                
                user = CustomUser.objects.create_user(
                    username=username,
                    email=email,
                    password=password,
                    first_name=first_name,
                    last_name=last_name,
                    role=role,
                    mobile=mobile if mobile else None
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
                    StaffProfile.objects.create(
                        user=user,
                        staff_id=f"STF{user.id:06d}",
                        department=self._get_department_for_role(role),
                        designation=self._get_designation_for_role(role)
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
            
            user.first_name = request.POST.get('first_name')
            user.last_name = request.POST.get('last_name')
            user.email = request.POST.get('email')
            user.role = request.POST.get('role')
            mobile = request.POST.get('mobile')
            user.mobile = mobile if mobile else None
            user.is_active = request.POST.get('is_active') == 'on'
            
            # Update role-specific fields
            patient_registration_number = request.POST.get('patient_registration_number')
            therapist_code = request.POST.get('therapist_code')
            employee_code = request.POST.get('employee_code')
            
            # Update profile based on role - delete all existing data
            from authentication.role_change_utils import change_user_role, get_mandatory_fields_for_role
            
            # Prepare profile data for new role with only mandatory fields
            profile_data = {}
            mandatory_fields = get_mandatory_fields_for_role(user.role)
            
            if user.role == 'patient' and patient_registration_number:
                profile_data['patient_reg_no'] = patient_registration_number
            elif user.role == 'therapist' and therapist_code:
                profile_data['therapist_code'] = therapist_code
                profile_data['employee_code'] = employee_code or f"EMP{user.id:06d}"
            elif user.role == 'doctor':
                profile_data['doctor_id'] = request.POST.get('doctor_id', f"DOC{user.id:06d}")
                profile_data['specialization'] = request.POST.get('specialization', 'General Medicine')
                profile_data['department'] = request.POST.get('department', 'Medical')
                profile_data['qualification'] = request.POST.get('qualification', 'MBBS')
                profile_data['experience_years'] = request.POST.get('experience_years', 0)
            elif user.role in ['admin', 'super_admin']:
                profile_data['admin_id'] = request.POST.get('admin_id', f"ADM{user.id:06d}")
                profile_data['department'] = request.POST.get('department', 'Administration')
                profile_data['designation'] = request.POST.get('designation', 
                    'Administrator' if user.role == 'admin' else 'Super Administrator')
            elif user.role == 'nurse':
                profile_data['nurse_id'] = request.POST.get('nurse_id', f"NUR{user.id:06d}")
                profile_data['department'] = request.POST.get('department', 'Nursing')
                profile_data['qualification'] = request.POST.get('qualification', 'B.Sc Nursing')
            elif user.role in ['scheduling_staff', 'ip_pharmacy_staff', 'imu_staff', 'finance_staff', 'hr', 'housekeeping_staff']:
                profile_data['staff_id'] = request.POST.get('staff_id', f"STF{user.id:06d}")
                profile_data['department'] = request.POST.get('department', _get_department_for_role(user.role))
                profile_data['designation'] = request.POST.get('designation', _get_designation_for_role(user.role))
            
            # Change user role - this will delete all existing data
            success, message, new_profile = change_user_role(user, user.role, profile_data)
            
            if not success:
                messages.error(request, message)
                return redirect('Manage_user')
            else:
                # Update therapist master if role is therapist
                if user.role == 'therapist' and new_profile:
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
                
                messages.warning(request, f"Role changed to {user.role}. All previous profile data has been deleted.")
            
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
        
        return redirect('Manage_user')
    
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
    
    # Start with all audit logs
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
    """Therapy report view"""
    return render(request, 'dashboards/reports/therapy_report.html')

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
    return render(request, 'dashboards/doctorsAndHelpDesk/therapy_entry.html', context)

@login_required
def search_patients(request):
    """API endpoint to search patients by registration number"""
    if request.method != 'GET':
        return JsonResponse({'error': 'Only GET method allowed'}, status=405)
    
    query = request.GET.get('q', '').strip()
    if not query or len(query) < 3:
        return JsonResponse({'patients': []})
    
    try:
        from MySql_Data_pull.models import Registration, OPMaster
        from Patient.models import Repeated_Visitors
        
        patients = []
        
        # Search in IP patients (Registration table)
        try:
            ip_patients = Registration.objects.using('therapy_db').filter(
                pat_reg_no__icontains=query
            ).values(
                'pat_reg_no', 'pat_name', 'pat_sex', 'pat_age', 'pat_room_no', 
                'pat_ref_id', 'pat_ph_no', 'pat_email', 'pat_reg_date'
            )[:10]  # Limit to 10 results
            
            for patient in ip_patients:
                # Check VIP status
                vip_status = False
                try:
                    repeated_visitor = Repeated_Visitors.objects.get(
                        register_number=patient['pat_reg_no']
                    )
                    vip_status = repeated_visitor.total_visits > 2
                except Repeated_Visitors.DoesNotExist:
                    vip_status = False
                
                # Determine patient type (IP if not 5 digits)
                patient_type = 'IP' if len(str(patient['pat_reg_no'])) != 5 else 'OP'
                
                patients.append({
                    'registration_number': patient['pat_reg_no'],
                    'patient_name': patient['pat_name'],
                    'sex': patient['pat_sex'],
                    'age': patient['pat_age'],
                    'room_number': patient['pat_room_no'],
                    'ip_number': patient['pat_reg_no'],  # IP number same as registration
                    'pat_ref_id': patient['pat_ref_id'],
                    'phone': patient['pat_ph_no'],
                    'email': patient['pat_email'],
                    'registration_date': patient['pat_reg_date'].strftime('%Y-%m-%d') if patient['pat_reg_date'] else None,
                    'patient_type': patient_type,
                    'is_vip': vip_status,
                    'source': 'IP'
                })
        except Exception as e:
            print(f"Error searching IP patients: {e}")
        
        # Search in OP patients (OPMaster table)
        try:
            op_patients = OPMaster.objects.using('hospital_db').filter(
                NPat_Reg_No__icontains=query
            ).values(
                'NPat_Reg_No', 'NPat_Name', 'NPat_Sex', 'Reg_Date'
            )[:10]  # Limit to 10 results
            
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
                
                # Determine patient type (OP if 5 digits)
                patient_type = 'OP' if len(str(patient['NPat_Reg_No'])) == 5 else 'IP'
                
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
                    'patient_type': patient_type,
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
        
        return JsonResponse({
            'patients': unique_patients[:20],  # Limit total results to 20
            'total_found': len(unique_patients)
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
            
            patient_details = {
                'registration_number': ip_patient.pat_reg_no,
                'patient_name': ip_patient.pat_name,
                'sex': ip_patient.pat_sex,
                'age': ip_patient.pat_age,
                'room_number': ip_patient.pat_room_no,
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
                    
                    patient_details = {
                        'registration_number': op_patient.NPat_Reg_No,
                        'patient_name': op_patient.NPat_Name,
                        'sex': op_patient.NPat_Sex,
                        'age': None,  # OP patients don't have age in this table
                        'room_number': None,  # OP patients don't have room number
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
        return redirect('Manage_user')
    
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
        return redirect('Manage_user')
    
    user_id = request.POST.get('user_id')
    new_role = request.POST.get('new_role')
    
    if not user_id or not new_role:
        messages.error(request, f'Invalid request parameters. user_id: {user_id}, new_role: {new_role}')
        return redirect('Manage_user')
    
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
    
    return redirect('Manage_user')