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
    """Check if therapist has is_bathing=True in TherapistBooking for this booking using visit (TherapyAllocation)"""
    try:
        from Patient.models import TherapistBooking
        from masters.models import TherapistMaster
        # Get allocation (visit) for this booking
        allocation = booking.allocation if booking else None
        if not allocation:
            return False
        # Find TherapistMaster by therapist_code
        therapist_master = TherapistMaster.objects.filter(
            therapist_code=assignment.therapist.therapist_code
        ).first()
        if therapist_master:
            # Find TherapistBooking for this visit and therapist
            tb = TherapistBooking.objects.filter(
                visit=allocation,
                therapist=therapist_master,
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

@register.filter
def is_senior_therapist_for_dhara(assignment, booking):
    """Check if therapist is senior and therapy is Dhara & Pizichil for highlighting"""
    try:
        allocation = booking.allocation if booking else None
        if not allocation or not allocation.therapy_name:
            return False
        
        # Check if this is Dhara & Pizichil therapy
        # Handle variations: "Dhara & Pizichil", "Dhara and Pizichil", "Dhara Pizichil", etc.
        therapy_lower = str(allocation.therapy_name).lower()
        has_dhara = 'dhara' in therapy_lower
        has_pizichil = 'pizichil' in therapy_lower or 'pizhichil' in therapy_lower
        is_dhara_pizichil = has_dhara and has_pizichil
        
        if not is_dhara_pizichil:
            return False
        
        # Check if therapist is senior using TherapistMaster (not Patient.models.Therapist)
        if assignment.therapist:
            try:
                from masters.models import TherapistMaster
                therapist_master = TherapistMaster.objects.filter(
                    therapist_code=assignment.therapist.therapist_code
                ).first()
                
                if therapist_master and therapist_master.therapist_grade:
                    # TherapistMaster has ForeignKey to TherapistGrade
                    grade_name = getattr(therapist_master.therapist_grade, 'name', '')
                    if grade_name and 'Senior' in grade_name:
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