"""
Nurse Allocation Algorithm
Separate from therapist allocation - handles nurse treatment assignments.
Distributes work equally among nurses in a day.
"""
from datetime import datetime, date
from django.db.models import Count, Q
from django.db import transaction


def is_nurse_treatment(therapy_code, therapy_name=None):
    """
    Check if a therapy is a nurse treatment by checking NurseTreatmentMaster.
    
    Args:
        therapy_code: Therapy code to check
        therapy_name: Optional therapy name (for fallback)
        
    Returns:
        NurseTreatmentMaster instance if found, None otherwise
    """
    from masters.models import NurseTreatmentMaster
    
    try:
        # Try to find by treatment_code
        nurse_treatment = NurseTreatmentMaster.objects.filter(
            treatment_code=therapy_code,
            is_active=True
        ).first()
        
        if nurse_treatment:
            return nurse_treatment
        
        # Fallback: try to find by name if provided
        if therapy_name:
            nurse_treatment = NurseTreatmentMaster.objects.filter(
                name__iexact=therapy_name,
                is_active=True
            ).first()
            if nurse_treatment:
                return nurse_treatment
    except Exception as e:
        print(f"Error checking nurse treatment: {e}")
    
    return None


def get_nurse_daily_workload(nurse, target_date):
    """
    Get the number of assignments a nurse has on a given date.
    
    Args:
        nurse: NurseMaster instance
        target_date: Date to check
        
    Returns:
        int: Number of assignments for this nurse on this date
    """
    from .models import BookingNurseAssignment
    
    return BookingNurseAssignment.objects.filter(
        nurse=nurse,
        booking_date=target_date,
        status='assigned'
    ).count()


def allocate_nurses(booking, target_date, number_required):
    """
    Simple nurse allocation - just allocate required number of nurses for the day.
    Distributes work equally by prioritizing nurses with fewer assignments.
    
    Args:
        booking: Booking instance
        target_date: Date of the booking
        number_required: Number of nurses required for this treatment
        
    Returns:
        list: List of BookingNurseAssignment instances created
    """
    from masters.models import NurseMaster
    from .models import BookingNurseAssignment
    
    if number_required <= 0:
        return []
    
    # Get all active nurses
    active_nurses = list(NurseMaster.objects.filter(is_active=True).order_by('nurse_code'))
    
    if not active_nurses:
        print(f"No active nurses found for allocation")
        return []
    
    # Get current workload for each nurse on this date
    nurse_workloads = {}
    for nurse in active_nurses:
        workload = get_nurse_daily_workload(nurse, target_date)
        nurse_workloads[nurse.id] = workload
    
    # Get nurses already assigned to this specific booking (to avoid duplicates)
    already_assigned_nurse_ids = set(
        BookingNurseAssignment.objects.filter(
            booking=booking,
            status='assigned'
        ).values_list('nurse_id', flat=True)
    )
    
    # Simple logic: sort by workload (ascending) - nurses with fewer assignments first
    available_nurses = [
        (nurse, nurse_workloads.get(nurse.id, 0))
        for nurse in active_nurses
        if nurse.id not in already_assigned_nurse_ids
    ]
    available_nurses.sort(key=lambda x: x[1])  # Sort by workload
    
    # Allocate the required number of nurses
    allocated = []
    for nurse, workload in available_nurses[:number_required]:
        try:
            assignment = BookingNurseAssignment.objects.create(
                booking=booking,
                nurse=nurse,
                status='assigned',
                booking_date=target_date,
                booking_timeslot=None  # No timeslot for nurses - allocated for entire day
            )
            allocated.append(assignment)
        except Exception as e:
            print(f"Error creating nurse assignment for {nurse.nurse_code}: {e}")
            # Continue with next nurse if this one fails
    
    return allocated


def allocate_nurses_for_booking(booking):
    """
    Allocate nurses for a booking if it's a nurse treatment.
    This is the main entry point for nurse allocation.
    
    Args:
        booking: Booking instance
        
    Returns:
        list: List of BookingNurseAssignment instances created, or empty list if not a nurse treatment
    """
    from .models import TherapyAllocation
    
    # Get the allocation
    allocation = booking.allocation
    
    # Check if this is a nurse treatment
    nurse_treatment = is_nurse_treatment(
        allocation.therapy_code,
        allocation.therapy_name
    )
    
    if not nurse_treatment:
        return []  # Not a nurse treatment, no allocation needed
    
    # Get number of nurses required
    number_required = nurse_treatment.number_of_nurse_required
    
    if number_required <= 0:
        return []
    
    # Check if nurses are already assigned to this booking
    existing_assignments = booking.nurse_assignments.filter(status='assigned')
    if existing_assignments.exists():
        # Nurses already allocated, return existing
        return list(existing_assignments)
    
    # Allocate nurses (no timeslot constraint - allocated for entire day)
    return allocate_nurses(
        booking=booking,
        target_date=booking.date,
        number_required=number_required
    )


def allocate_nurses_for_date(target_date_str):
    """
    Allocate nurses for all nurse treatment bookings on a specific date.
    This is called after final schedule to allocate nurses for all nurse treatments.
    
    Args:
        target_date_str: Date string in YYYY-MM-DD format
        
    Returns:
        dict: Summary of nurse allocation results
    """
    from datetime import datetime
    from .models import Booking, TherapyAllocation
    
    try:
        target_date = datetime.strptime(target_date_str, '%Y-%m-%d').date()
    except ValueError:
        return {
            'success': False,
            'error': f'Invalid date format: {target_date_str}. Expected YYYY-MM-DD'
        }
    
    # Get all scheduled bookings for this date
    scheduled_bookings = Booking.objects.filter(
        date=target_date,
        status__in=['scheduled', 'draft']  # Include draft in case they get scheduled
    ).select_related('allocation', 'timeslot')
    
    total_allocated = 0
    total_bookings = 0
    errors = []
    
    for booking in scheduled_bookings:
        try:
            # Check if this is a nurse treatment
            nurse_treatment = is_nurse_treatment(
                booking.allocation.therapy_code,
                booking.allocation.therapy_name
            )
            
            if nurse_treatment:
                total_bookings += 1
                # Remove existing assignments if any (in case of re-allocation)
                booking.nurse_assignments.filter(status='assigned').update(status='released')
                
                # Allocate nurses
                assignments = allocate_nurses_for_booking(booking)
                if assignments:
                    total_allocated += len(assignments)
        except Exception as e:
            errors.append(f"Error allocating nurses for booking {booking.id}: {str(e)}")
    
    return {
        'success': True,
        'date': target_date_str,
        'total_nurse_treatments': total_bookings,
        'total_nurses_allocated': total_allocated,
        'errors': errors
    }


def reallocate_nurses_for_booking(booking):
    """
    Reallocate nurses for a booking (used when treatment is changed).
    Removes old assignments and creates new ones.
    
    Args:
        booking: Booking instance
        
    Returns:
        list: List of new BookingNurseAssignment instances
    """
    # Remove existing assignments
    booking.nurse_assignments.filter(status='assigned').update(status='released')
    
    # Allocate new nurses
    return allocate_nurses_for_booking(booking)

