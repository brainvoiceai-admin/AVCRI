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
    """Check if therapist has is_bathing=True in TherapistBooking for this booking"""
    try:
        from Patient.models import TherapistBooking
        from masters.models import TherapistMaster
        # Find TherapistMaster by therapist_code
        therapist_master = TherapistMaster.objects.filter(
            therapist_code=assignment.therapist.therapist_code
        ).first()
        if therapist_master and booking:
            # Find TherapistBooking for this therapist, date, and time slot
            tb = TherapistBooking.objects.filter(
                therapist=therapist_master,
                date=booking.date,
                time_slot=booking.timeslot,
                status='BOOKED'
            ).first()
            if tb:
                return getattr(tb, 'is_bathing', False)
    except Exception:
        pass
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