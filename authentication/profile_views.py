"""
Views for managing user profiles
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.contrib.auth import get_user_model
from django.core.paginator import Paginator
from django.db import transaction
from .models import (
    PatientProfile, TherapistProfile, DoctorProfile, 
    AdminProfile, NurseProfile, StaffProfile
)
from .profile_utils import get_user_profile, get_profile_display_name
from .decorators import super_admin_required, role_required
import json

User = get_user_model()

@login_required
@super_admin_required
def profile_management_dashboard(request):
    """Dashboard for managing all user profiles"""
    # Get counts for each profile type
    profile_counts = {
        'patients': PatientProfile.objects.count(),
        'therapists': TherapistProfile.objects.count(),
        'doctors': DoctorProfile.objects.count(),
        'admins': AdminProfile.objects.count(),
        'nurses': NurseProfile.objects.count(),
        'staff': StaffProfile.objects.count(),
    }
    
    # Get recent profiles
    recent_profiles = []
    for profile_model in [PatientProfile, TherapistProfile, DoctorProfile, AdminProfile, NurseProfile, StaffProfile]:
        recent_profiles.extend(profile_model.objects.select_related('user').order_by('-created_at')[:5])
    
    # Sort by creation date
    recent_profiles.sort(key=lambda x: x.created_at, reverse=True)
    
    context = {
        'profile_counts': profile_counts,
        'recent_profiles': recent_profiles[:10],  # Show only 10 most recent
    }
    
    return render(request, 'authentication/profile_management_dashboard.html', context)

@login_required
@super_admin_required
def patient_profiles_list(request):
    """List all patient profiles"""
    patients = PatientProfile.objects.select_related('user').order_by('-created_at')
    
    # Pagination
    paginator = Paginator(patients, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'page_obj': page_obj,
        'profile_type': 'Patient',
    }
    
    return render(request, 'authentication/profiles_list.html', context)

@login_required
@super_admin_required
def therapist_profiles_list(request):
    """List all therapist profiles"""
    therapists = TherapistProfile.objects.select_related('user').order_by('-created_at')
    
    # Pagination
    paginator = Paginator(therapists, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'page_obj': page_obj,
        'profile_type': 'Therapist',
    }
    
    return render(request, 'authentication/profiles_list.html', context)

@login_required
@super_admin_required
def doctor_profiles_list(request):
    """List all doctor profiles"""
    doctors = DoctorProfile.objects.select_related('user').order_by('-created_at')
    
    # Pagination
    paginator = Paginator(doctors, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'page_obj': page_obj,
        'profile_type': 'Doctor',
    }
    
    return render(request, 'authentication/profiles_list.html', context)

@login_required
@super_admin_required
def admin_profiles_list(request):
    """List all admin profiles"""
    admins = AdminProfile.objects.select_related('user').order_by('-created_at')
    
    # Pagination
    paginator = Paginator(admins, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'page_obj': page_obj,
        'profile_type': 'Admin',
    }
    
    return render(request, 'authentication/profiles_list.html', context)

@login_required
@super_admin_required
def nurse_profiles_list(request):
    """List all nurse profiles"""
    nurses = NurseProfile.objects.select_related('user').order_by('-created_at')
    
    # Pagination
    paginator = Paginator(nurses, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'page_obj': page_obj,
        'profile_type': 'Nurse',
    }
    
    return render(request, 'authentication/profiles_list.html', context)

@login_required
@super_admin_required
def staff_profiles_list(request):
    """List all staff profiles"""
    staff = StaffProfile.objects.select_related('user').order_by('-created_at')
    
    # Pagination
    paginator = Paginator(staff, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'page_obj': page_obj,
        'profile_type': 'Staff',
    }
    
    return render(request, 'authentication/profiles_list.html', context)

@login_required
@super_admin_required
def patient_profile_detail(request, pk):
    """View patient profile details"""
    profile = get_object_or_404(PatientProfile, pk=pk)
    
    context = {
        'profile': profile,
        'user': profile.user,
        'profile_type': 'Patient',
    }
    
    return render(request, 'authentication/profile_detail.html', context)

@login_required
@super_admin_required
def therapist_profile_detail(request, pk):
    """View therapist profile details"""
    profile = get_object_or_404(TherapistProfile, pk=pk)
    
    context = {
        'profile': profile,
        'user': profile.user,
        'profile_type': 'Therapist',
    }
    
    return render(request, 'authentication/profile_detail.html', context)

@login_required
@super_admin_required
def doctor_profile_detail(request, pk):
    """View doctor profile details"""
    profile = get_object_or_404(DoctorProfile, pk=pk)
    
    context = {
        'profile': profile,
        'user': profile.user,
        'profile_type': 'Doctor',
    }
    
    return render(request, 'authentication/profile_detail.html', context)

@login_required
@super_admin_required
def admin_profile_detail(request, pk):
    """View admin profile details"""
    profile = get_object_or_404(AdminProfile, pk=pk)
    
    context = {
        'profile': profile,
        'user': profile.user,
        'profile_type': 'Admin',
    }
    
    return render(request, 'authentication/profile_detail.html', context)

@login_required
@super_admin_required
def nurse_profile_detail(request, pk):
    """View nurse profile details"""
    profile = get_object_or_404(NurseProfile, pk=pk)
    
    context = {
        'profile': profile,
        'user': profile.user,
        'profile_type': 'Nurse',
    }
    
    return render(request, 'authentication/profile_detail.html', context)

@login_required
@super_admin_required
def staff_profile_detail(request, pk):
    """View staff profile details"""
    profile = get_object_or_404(StaffProfile, pk=pk)
    
    context = {
        'profile': profile,
        'user': profile.user,
        'profile_type': 'Staff',
    }
    
    return render(request, 'authentication/profile_detail.html', context)

@login_required
@super_admin_required
def patient_profile_edit(request, pk):
    """Edit patient profile"""
    profile = get_object_or_404(PatientProfile, pk=pk)
    
    if request.method == 'POST':
        # Update profile fields
        profile.patient_reg_no = request.POST.get('patient_reg_no', profile.patient_reg_no)
        profile.date_of_birth = request.POST.get('date_of_birth') or None
        profile.gender = request.POST.get('gender', profile.gender)
        profile.address = request.POST.get('address', profile.address)
        profile.emergency_contact = request.POST.get('emergency_contact', profile.emergency_contact)
        profile.emergency_phone = request.POST.get('emergency_phone', profile.emergency_phone)
        profile.medical_history = request.POST.get('medical_history', profile.medical_history)
        profile.allergies = request.POST.get('allergies', profile.allergies)
        profile.is_vip = request.POST.get('is_vip') == 'on'
        
        profile.save()
        messages.success(request, 'Patient profile updated successfully.')
        return redirect('patient_profile_detail', pk=profile.pk)
    
    context = {
        'profile': profile,
        'user': profile.user,
        'profile_type': 'Patient',
    }
    
    return render(request, 'authentication/profile_edit.html', context)

@login_required
@super_admin_required
def therapist_profile_edit(request, pk):
    """Edit therapist profile"""
    profile = get_object_or_404(TherapistProfile, pk=pk)
    
    if request.method == 'POST':
        # Update profile fields
        profile.therapist_code = request.POST.get('therapist_code', profile.therapist_code)
        profile.employee_code = request.POST.get('employee_code', profile.employee_code)
        profile.therapist_grade = request.POST.get('therapist_grade', profile.therapist_grade)
        profile.department = request.POST.get('department', profile.department)
        profile.specialization = request.POST.get('specialization', profile.specialization)
        profile.is_bathing_therapist = request.POST.get('is_bathing_therapist') == 'on'
        profile.joining_date = request.POST.get('joining_date') or None
        profile.qualification = request.POST.get('qualification', profile.qualification)
        profile.experience_years = request.POST.get('experience_years') or None
        
        profile.save()
        messages.success(request, 'Therapist profile updated successfully.')
        return redirect('therapist_profile_detail', pk=profile.pk)
    
    context = {
        'profile': profile,
        'user': profile.user,
        'profile_type': 'Therapist',
    }
    
    return render(request, 'authentication/profile_edit.html', context)

@login_required
@super_admin_required
def doctor_profile_edit(request, pk):
    """Edit doctor profile"""
    profile = get_object_or_404(DoctorProfile, pk=pk)
    
    if request.method == 'POST':
        # Update profile fields
        profile.doctor_id = request.POST.get('doctor_id', profile.doctor_id)
        profile.specialization = request.POST.get('specialization', profile.specialization)
        profile.department = request.POST.get('department', profile.department)
        profile.qualification = request.POST.get('qualification', profile.qualification)
        profile.experience_years = request.POST.get('experience_years', profile.experience_years)
        profile.license_number = request.POST.get('license_number', profile.license_number)
        profile.consultation_fee = request.POST.get('consultation_fee') or None
        
        profile.save()
        messages.success(request, 'Doctor profile updated successfully.')
        return redirect('doctor_profile_detail', pk=profile.pk)
    
    context = {
        'profile': profile,
        'user': profile.user,
        'profile_type': 'Doctor',
    }
    
    return render(request, 'authentication/profile_edit.html', context)

@login_required
@super_admin_required
def admin_profile_edit(request, pk):
    """Edit admin profile"""
    profile = get_object_or_404(AdminProfile, pk=pk)
    
    if request.method == 'POST':
        # Update profile fields
        profile.admin_id = request.POST.get('admin_id', profile.admin_id)
        profile.department = request.POST.get('department', profile.department)
        profile.designation = request.POST.get('designation', profile.designation)
        profile.reporting_manager = request.POST.get('reporting_manager', profile.reporting_manager)
        
        profile.save()
        messages.success(request, 'Admin profile updated successfully.')
        return redirect('admin_profile_detail', pk=profile.pk)
    
    context = {
        'profile': profile,
        'user': profile.user,
        'profile_type': 'Admin',
    }
    
    return render(request, 'authentication/profile_edit.html', context)

@login_required
@super_admin_required
def nurse_profile_edit(request, pk):
    """Edit nurse profile"""
    profile = get_object_or_404(NurseProfile, pk=pk)
    
    if request.method == 'POST':
        # Update profile fields
        profile.nurse_id = request.POST.get('nurse_id', profile.nurse_id)
        profile.department = request.POST.get('department', profile.department)
        profile.qualification = request.POST.get('qualification', profile.qualification)
        profile.experience_years = request.POST.get('experience_years') or None
        profile.shift = request.POST.get('shift', profile.shift)
        
        profile.save()
        messages.success(request, 'Nurse profile updated successfully.')
        return redirect('nurse_profile_detail', pk=profile.pk)
    
    context = {
        'profile': profile,
        'user': profile.user,
        'profile_type': 'Nurse',
    }
    
    return render(request, 'authentication/profile_edit.html', context)

@login_required
@super_admin_required
def staff_profile_edit(request, pk):
    """Edit staff profile"""
    profile = get_object_or_404(StaffProfile, pk=pk)
    
    if request.method == 'POST':
        # Update profile fields
        profile.staff_id = request.POST.get('staff_id', profile.staff_id)
        profile.department = request.POST.get('department', profile.department)
        profile.designation = request.POST.get('designation', profile.designation)
        profile.reporting_manager = request.POST.get('reporting_manager', profile.reporting_manager)
        
        profile.save()
        messages.success(request, 'Staff profile updated successfully.')
        return redirect('staff_profile_detail', pk=profile.pk)
    
    context = {
        'profile': profile,
        'user': profile.user,
        'profile_type': 'Staff',
    }
    
    return render(request, 'authentication/profile_edit.html', context)
