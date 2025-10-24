"""
Utility functions for working with user profiles
"""
from django.contrib.auth import get_user_model
from authentication.models import (
    PatientProfile, TherapistProfile, DoctorProfile, 
    AdminProfile, NurseProfile, StaffProfile
)

User = get_user_model()

def get_user_profile(user):
    """
    Get the appropriate profile for a user based on their role
    """
    if not user or not user.is_authenticated:
        return None
    
    role = user.role
    
    if role == 'patient':
        return getattr(user, 'patient_profile', None)
    elif role == 'therapist':
        return getattr(user, 'therapist_profile', None)
    elif role == 'doctor':
        return getattr(user, 'doctor_profile', None)
    elif role in ['admin', 'super_admin']:
        return getattr(user, 'admin_profile', None)
    elif role == 'nurse':
        return getattr(user, 'nurse_profile', None)
    elif role in ['scheduling_staff', 'ip_pharmacy_staff', 'imu_staff', 
                  'finance_staff', 'hr', 'housekeeping_staff']:
        return getattr(user, 'staff_profile', None)
    
    return None

def get_profile_display_name(user):
    """
    Get display name for a user based on their profile
    """
    profile = get_user_profile(user)
    if not profile:
        return user.get_full_name() or user.username
    
    if hasattr(profile, 'patient_reg_no'):
        return f"{user.get_full_name()} ({profile.patient_reg_no})"
    elif hasattr(profile, 'therapist_code'):
        return f"{user.get_full_name()} ({profile.therapist_code})"
    elif hasattr(profile, 'doctor_id'):
        return f"Dr. {user.get_full_name()} ({profile.doctor_id})"
    elif hasattr(profile, 'admin_id'):
        return f"{user.get_full_name()} ({profile.admin_id})"
    elif hasattr(profile, 'nurse_id'):
        return f"{user.get_full_name()} ({profile.nurse_id})"
    elif hasattr(profile, 'staff_id'):
        return f"{user.get_full_name()} ({profile.staff_id})"
    
    return user.get_full_name() or user.username

def create_user_with_profile(role, username, email, password, profile_data=None):
    """
    Create a user with the appropriate profile
    """
    user = User.objects.create_user(
        username=username,
        email=email,
        password=password,
        role=role
    )
    
    if profile_data is None:
        profile_data = {}
    
    if role == 'patient':
        PatientProfile.objects.create(user=user, **profile_data)
    elif role == 'therapist':
        TherapistProfile.objects.create(user=user, **profile_data)
    elif role == 'doctor':
        DoctorProfile.objects.create(user=user, **profile_data)
    elif role in ['admin', 'super_admin']:
        AdminProfile.objects.create(user=user, **profile_data)
    elif role == 'nurse':
        NurseProfile.objects.create(user=user, **profile_data)
    elif role in ['scheduling_staff', 'ip_pharmacy_staff', 'imu_staff', 
                  'finance_staff', 'hr', 'housekeeping_staff']:
        StaffProfile.objects.create(user=user, **profile_data)
    
    return user

def get_users_by_role(role):
    """
    Get all users with a specific role
    """
    return User.objects.filter(role=role)

def get_profile_model_for_role(role):
    """
    Get the profile model class for a specific role
    """
    model_mapping = {
        'patient': PatientProfile,
        'therapist': TherapistProfile,
        'doctor': DoctorProfile,
        'admin': AdminProfile,
        'super_admin': AdminProfile,
        'nurse': NurseProfile,
        'scheduling_staff': StaffProfile,
        'ip_pharmacy_staff': StaffProfile,
        'imu_staff': StaffProfile,
        'finance_staff': StaffProfile,
        'hr': StaffProfile,
        'housekeeping_staff': StaffProfile,
    }
    return model_mapping.get(role)

def get_profile_related_name(role):
    """
    Get the related_name for the profile relationship
    """
    related_name_mapping = {
        'patient': 'patient_profile',
        'therapist': 'therapist_profile',
        'doctor': 'doctor_profile',
        'admin': 'admin_profile',
        'super_admin': 'admin_profile',
        'nurse': 'nurse_profile',
        'scheduling_staff': 'staff_profile',
        'ip_pharmacy_staff': 'staff_profile',
        'imu_staff': 'staff_profile',
        'finance_staff': 'staff_profile',
        'hr': 'staff_profile',
        'housekeeping_staff': 'staff_profile',
    }
    return related_name_mapping.get(role)
