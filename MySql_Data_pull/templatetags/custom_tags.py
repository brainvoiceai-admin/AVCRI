from django import template
from datetime import datetime

register = template.Library()

@register.filter
def get_attr(obj, attr):
    """Get dynamic attribute from model instance"""
    return getattr(obj, attr, None)

@register.filter
def get_staying_room_display(room_number):
    """Get staying room display number from StayingRoom model"""
    if room_number in (None, ''):
        return room_number
    try:
        from masters.models import get_staying_room_display_number
        return get_staying_room_display_number(room_number)
    except Exception:
        return room_number

@register.filter
def get_therapist_bathing_flag(assignment, booking):
    """Check if therapist has is_bathing=True in TherapistBooking for this booking using visit (TherapyAllocation), date, and time_slot"""
    try:
        from Patient.models import TherapistBooking
        from masters.models import TherapistMaster
        # Get allocation (visit) for this booking
        allocation = booking.allocation if booking else None
        if not allocation:
            return False
        # Get booking date and time_slot
        booking_date = getattr(booking, 'date', None)
        booking_timeslot = getattr(booking, 'timeslot', None)
        if not booking_date or not booking_timeslot:
            return False
        # Find TherapistMaster by therapist_code
        therapist_master = TherapistMaster.objects.filter(
            therapist_code=assignment.therapist.therapist_code
        ).first()
        if therapist_master:
            # Find TherapistBooking for this visit, therapist, date, and time_slot
            # IMPORTANT: Must filter by date and time_slot to get the correct record
            tb = TherapistBooking.objects.filter(
                visit=allocation,
                therapist=therapist_master,
                date=booking_date,
                time_slot=booking_timeslot,
                status='BOOKED'
            ).first()
            if tb:
                # ONLY use TherapistBooking.is_bathing field from Patient module
                return tb.is_bathing  # Direct access to is_bathing field
    except Exception as e:
        print(f"Error in get_therapist_bathing_flag: {e}")
        import traceback
        traceback.print_exc()
    return False

def _is_treatment_requiring_senior_tag(therapy_name):
    """
    Check if a treatment requires special senior tag handling.
    Returns True ONLY if the therapy name exactly matches one of the specified treatments.
    (Duplicated from Sheduling.views to avoid circular imports)
    """
    if not therapy_name:
        return False
    
    # List of treatments that require senior tag (only one senior, not bathing)
    # ONLY these exact treatments should show the senior tag
    special_treatments = [
        'dhara & abh(3)',
        'dhara& pizhichil (4)',
        'dhara & pizhichil (5)',
        'dhara & pizhichil (6)',
        'dhara & pizhichil (7)',
        'dhara & abyangam ( 3 t)',
        'dhara & sudhikalpana dhara (5t)',
        'dhara ( 2 t)',
        'thakradhara & abhyangam (4)',
        'thakradhara & pizichil(6)',
        'thakradhara ( 2 t)',
        'thakradhara&fbkadee kizhi (5 t)',
        'thakradhara& thakrapizhichil(7)',
    ]
    
    # Normalize therapy name: lowercase, remove extra spaces, keep structure
    therapy_normalized = ' '.join(str(therapy_name).lower().strip().split())
    
    # Check for exact match (case-insensitive, ignoring extra spaces)
    for special_treatment in special_treatments:
        special_normalized = ' '.join(special_treatment.lower().strip().split())
        if therapy_normalized == special_normalized:
            return True
    
    return False

@register.filter
def is_senior_therapist_for_dhara(assignment, booking):
    """
    Check if therapist is senior and should show senior tag for special treatments.
    Only returns True for ONE senior therapist who is NOT a bathing person.
    """
    try:
        allocation = booking.allocation if booking else None
        if not allocation or not allocation.therapy_name:
            return False
        
        # Check if this treatment requires special senior tag handling
        requires_senior_tag = _is_treatment_requiring_senior_tag(allocation.therapy_name)
        
        if not requires_senior_tag:
            return False
        
        # Check if therapist is senior using TherapistMaster (not Patient.models.Therapist)
        if not assignment.therapist:
            return False
        
        try:
            from masters.models import TherapistMaster
            
            # Get all assignments for this booking to find the first senior non-bathing therapist
            all_assignments = list(booking.assignments.all()) if booking else []
            senior_non_bathing_code = None
            
            # First pass: find the first senior non-bathing therapist
            for assgn in all_assignments:
                if not assgn.therapist:
                    continue
                
                therapist_master = TherapistMaster.objects.filter(
                    therapist_code=assgn.therapist.therapist_code
                ).first()
                
                if not therapist_master or not therapist_master.therapist_grade:
                    continue
                
                grade_name = getattr(therapist_master.therapist_grade, 'name', '')
                if not grade_name or 'Senior' not in grade_name:
                    continue
                
                # Check if this therapist is NOT a bathing person
                is_bathing = get_therapist_bathing_flag(assgn, booking)
                if not is_bathing:
                    # Found the first senior non-bathing therapist
                    senior_non_bathing_code = assgn.therapist.therapist_code
                    break
            
            # Only return True if this assignment is the identified senior non-bathing therapist
            if senior_non_bathing_code and assignment.therapist.therapist_code == senior_non_bathing_code:
                return True
            
        except Exception as e:
            print(f"Error checking TherapistMaster in is_senior_therapist_for_dhara: {e}")
            import traceback
            traceback.print_exc()
    except Exception as e:
        print(f"Error in is_senior_therapist_for_dhara: {e}")
        import traceback
        traceback.print_exc()
    return False

@register.filter
def format_12hour(time_value):
    """Convert 24-hour time to 12-hour format (e.g., 14:30 -> 2:30 PM)"""
    if not time_value:
        return '—'
    
    try:
        # Handle TimeField objects
        if hasattr(time_value, 'strftime'):
            time_str = time_value.strftime('%H:%M')
        else:
            time_str = str(time_value)
        
        # Parse time string (HH:MM format)
        parts = time_str.split(':')
        if len(parts) != 2:
            return time_str
        
        hours = int(parts[0])
        minutes = parts[1]
        
        period = 'PM' if hours >= 12 else 'AM'
        hours_12 = hours % 12
        if hours_12 == 0:
            hours_12 = 12
        
        # Remove leading zero from hours if needed
        return f"{hours_12}:{minutes} {period}"
    except (ValueError, AttributeError, TypeError):
        return str(time_value) if time_value else '—'