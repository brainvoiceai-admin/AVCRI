"""
Utility functions for handling user role changes with data preservation
"""
from django.contrib.auth import get_user_model
from authentication.models import (
    PatientProfile, TherapistProfile, DoctorProfile, 
    AdminProfile, NurseProfile, StaffProfile
)

User = get_user_model()

def change_user_role(user, new_role, profile_data=None):
    """
    Change user role by deleting all existing data and creating new profile with only mandatory fields
    
    Args:
        user: User instance
        new_role: New role to assign
        profile_data: Dict with mandatory fields for new role
    
    Returns:
        tuple: (success: bool, message: str, new_profile: object)
    """
    if profile_data is None:
        profile_data = {}
    
    old_profile = get_existing_profile(user)
    old_role = user.role
    
    try:
        # Delete all existing profile data and dependent records
        # Pass old_role to only delete TherapistMaster if role is changing away from therapist
        delete_all_user_profiles(user, old_role=old_role, new_role=new_role)
        
        # Update user role
        user.role = new_role
        user.save()
        
        # Create new profile with only mandatory fields
        new_profile = create_minimal_profile(user, new_role, profile_data)
        
        return True, f"User role changed from {old_role} to {new_role}. All previous data deleted.", new_profile
        
    except Exception as e:
        return False, f"Error changing role: {str(e)}", None

def delete_all_user_profiles(user, old_role=None, new_role=None):
    """
    Delete all existing profiles and dependent records for a user
    Only deletes TherapistMaster if role is changing away from 'therapist'
    """
    # Delete all possible profile types
    if hasattr(user, 'patient_profile'):
        user.patient_profile.delete()
    if hasattr(user, 'therapist_profile'):
        # Only delete TherapistMaster if role is changing away from 'therapist'
        # This prevents accidental deletion when just updating password or other fields
        should_delete_therapist_master = (old_role != 'therapist' or new_role != 'therapist')
        
        if should_delete_therapist_master:
            # Delete therapist master record first
            from masters.models import TherapistMaster, TherapistLeaveMaster
            try:
                therapist_master = TherapistMaster.objects.get(user=user)
                # Delete therapist leave records first
                TherapistLeaveMaster.objects.filter(therapist=therapist_master).delete()
                therapist_master.delete()
            except TherapistMaster.DoesNotExist:
                pass
        user.therapist_profile.delete()
    if hasattr(user, 'doctor_profile'):
        user.doctor_profile.delete()
    if hasattr(user, 'admin_profile'):
        user.admin_profile.delete()
    if hasattr(user, 'nurse_profile'):
        user.nurse_profile.delete()
    if hasattr(user, 'staff_profile'):
        user.staff_profile.delete()

def get_existing_profile(user):
    """Get the existing profile for a user"""
    if hasattr(user, 'patient_profile'):
        return user.patient_profile
    elif hasattr(user, 'therapist_profile'):
        return user.therapist_profile
    elif hasattr(user, 'doctor_profile'):
        return user.doctor_profile
    elif hasattr(user, 'admin_profile'):
        return user.admin_profile
    elif hasattr(user, 'nurse_profile'):
        return user.nurse_profile
    elif hasattr(user, 'staff_profile'):
        return user.staff_profile
    return None

def create_minimal_profile(user, new_role, profile_data):
    """Create new profile with only mandatory fields - no preserved data"""
    
    if new_role == 'patient':
        # Only mandatory field is patient_reg_no
        return PatientProfile.objects.create(
            user=user,
            patient_reg_no=profile_data.get('patient_reg_no', f"PAT{user.id:06d}")
        )
    
    elif new_role == 'therapist':
        # Retrieve existing TherapistMaster record
        from masters.models import TherapistMaster
        try:
            t_master = TherapistMaster.objects.get(therapist_code=profile_data.get('therapist_code'))
            
            # Create therapist profile based on master data
            therapist_profile = TherapistProfile.objects.create(
                user=user,
                therapist_code=t_master.therapist_code,
                employee_code=t_master.employee_code,
                therapist_grade=t_master.therapist_grade.name if t_master.therapist_grade else 'Junior'
            )
            
            # Map user to therapist master
            t_master.user = user
            t_master.therapist_profile = therapist_profile
            t_master.save()
            return therapist_profile
        except TherapistMaster.DoesNotExist:
            raise Exception("Active Therapist with provided Therapist Code does not exist in Therapist Master.")
    
    elif new_role == 'doctor':
        # Mandatory fields: doctor_id, specialization, department, qualification, experience_years
        return DoctorProfile.objects.create(
            user=user,
            doctor_id=profile_data.get('doctor_id', f"DOC{user.id:06d}"),
            specialization=profile_data.get('specialization', 'General Medicine'),
            department=profile_data.get('department', 'Medical'),
            qualification=profile_data.get('qualification', 'MBBS'),
            experience_years=profile_data.get('experience_years', 0)
        )
    
    elif new_role in ['admin', 'super_admin']:
        # Mandatory fields: admin_id, department, designation
        return AdminProfile.objects.create(
            user=user,
            admin_id=profile_data.get('admin_id', f"ADM{user.id:06d}"),
            department=profile_data.get('department', 'Administration'),
            designation=profile_data.get('designation', 
                'Administrator' if new_role == 'admin' else 'Super Administrator')
        )
    
    elif new_role == 'nurse':
        # Mandatory fields: nurse_id, department, qualification
        return NurseProfile.objects.create(
            user=user,
            nurse_id=profile_data.get('nurse_id', f"NUR{user.id:06d}"),
            department=profile_data.get('department', 'Nursing'),
            qualification=profile_data.get('qualification', 'B.Sc Nursing')
        )
    
    elif new_role in ['scheduling_staff', 'ip_pharmacy_staff', 'imu_staff', 
                      'finance_staff', 'hr', 'housekeeping_staff']:
        # Mandatory fields: staff_id, department, designation
        return StaffProfile.objects.create(
            user=user,
            staff_id=profile_data.get('staff_id', f"STF{user.id:06d}"),
            department=profile_data.get('department', get_department_for_role(new_role)),
            designation=profile_data.get('designation', get_designation_for_role(new_role))
        )
    
    return None

def get_department_for_role(role):
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

def get_designation_for_role(role):
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

def get_mandatory_fields_for_role(role):
    """
    Get the mandatory fields required for each role
    """
    mandatory_fields = {
        'patient': ['patient_reg_no'],
        'therapist': ['therapist_code', 'employee_code'],
        'doctor': ['doctor_id', 'specialization', 'department', 'qualification', 'experience_years'],
        'admin': ['admin_id', 'department', 'designation'],
        'super_admin': ['admin_id', 'department', 'designation'],
        'nurse': ['nurse_id', 'department', 'qualification'],
        'scheduling_staff': ['staff_id', 'department', 'designation'],
        'ip_pharmacy_staff': ['staff_id', 'department', 'designation'],
        'imu_staff': ['staff_id', 'department', 'designation'],
        'finance_staff': ['staff_id', 'department', 'designation'],
        'hr': ['staff_id', 'department', 'designation'],
        'housekeeping_staff': ['staff_id', 'department', 'designation'],
    }
    return mandatory_fields.get(role, [])
