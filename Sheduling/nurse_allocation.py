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
    Simple nurse allocation - allocate required number of nurses for the day.
    Uses round-robin distribution for equal work distribution (not strict).
    Ensures all nurse treatments get nurses assigned - no blank assignments.
    
    Args:
        booking: Booking instance
        target_date: Date of the booking
        number_required: Number of nurses required for this treatment
        
    Returns:
        list: List of BookingNurseAssignment instances created
    """
    from masters.models import NurseMaster
    from .models import BookingNurseAssignment
    
    # Ensure number_required is valid (at least 1, but respect the actual requirement)
    if number_required <= 0:
        # Only default to 1 if the value is invalid/not set
        # This is a safety fallback - normally number_required should come from NurseTreatmentMaster
        number_required = 1
    
    # Get all active nurses
    active_nurses = list(NurseMaster.objects.filter(is_active=True).order_by('nurse_code'))
    
    if not active_nurses:
        print(f"No active nurses found for allocation")
        return []
    
    # Get nurses already assigned to this specific booking (to avoid duplicates)
    already_assigned_nurse_ids = set(
        BookingNurseAssignment.objects.filter(
            booking=booking,
            status='assigned'
        ).values_list('nurse_id', flat=True)
    )
    
    # Get available nurses (not already assigned to this booking)
    available_nurses = [
        nurse for nurse in active_nurses
        if nurse.id not in already_assigned_nurse_ids
    ]
    
    if not available_nurses:
        # If all nurses are already assigned to this booking, return existing assignments
        existing = list(BookingNurseAssignment.objects.filter(
            booking=booking,
            status='assigned'
        ))
        return existing if existing else []
    
    # Get current workload for each available nurse (for soft balancing, not strict)
    nurse_workloads = {}
    for nurse in available_nurses:
        workload = get_nurse_daily_workload(nurse, target_date)
        nurse_workloads[nurse.id] = workload
    
    # Sort by workload (ascending) for soft balancing, but ensure we always assign
    # This gives preference to nurses with fewer assignments but doesn't strictly enforce it
    available_nurses.sort(key=lambda n: nurse_workloads.get(n.id, 0))
    
    # Determine how many nurses to actually assign
    # Respect the number_required value - assign exactly that many if available
    # If we need more than available, assign all available (no blank assignments)
    nurses_to_assign = min(number_required, len(available_nurses))
    
    # Only ensure at least one if number_required was invalid (0 or negative)
    # Otherwise, respect the actual requirement (even if it means assigning fewer than required)
    if nurses_to_assign == 0 and len(available_nurses) > 0:
        # This should only happen if number_required was 0 or negative
        # In that case, assign at least 1 as a safety measure
        nurses_to_assign = 1
    
    # Allocate nurses - assign exactly the number required
    allocated = []
    assigned_nurse_ids = set()  # Track which nurse IDs we've successfully assigned
    
    # Keep trying until we assign the required number or run out of nurses
    for nurse in available_nurses:
        if len(allocated) >= nurses_to_assign:
            break
        
        # Skip if this nurse is already assigned
        if nurse.id in assigned_nurse_ids:
            continue
        
        try:
            assignment = BookingNurseAssignment.objects.create(
                booking=booking,
                nurse=nurse,
                status='assigned',
                booking_date=target_date,
                booking_timeslot=None  # No timeslot for nurses - allocated for entire day
            )
            allocated.append(assignment)
            assigned_nurse_ids.add(nurse.id)
        except Exception as e:
            # If there's a duplicate constraint error, skip this nurse
            if 'unique' in str(e).lower() or 'duplicate' in str(e).lower():
                print(f"Nurse {nurse.nurse_code} already assigned to this booking, skipping")
            else:
                print(f"Error creating nurse assignment for {nurse.nurse_code}: {e}")
            continue
    
    # Last resort: if we have no assignments but nurses are available, assign at least one
    if not allocated and available_nurses:
        try:
            assignment = BookingNurseAssignment.objects.create(
                booking=booking,
                nurse=available_nurses[0],
                status='assigned',
                booking_date=target_date,
                booking_timeslot=None
            )
            allocated.append(assignment)
        except Exception as e:
            print(f"Critical error: Could not assign any nurse: {e}")
    
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
    
    # Get number of nurses required from the nurse treatment master
    number_required = nurse_treatment.number_of_nurse_required
    
    # Validate the number_required value
    # The field should have a default of 1, but ensure it's valid
    if number_required is None or number_required <= 0:
        # Only default to 1 if the value is invalid
        # This should not happen if the database is properly configured
        print(f"Warning: Invalid number_of_nurse_required ({number_required}) for treatment {nurse_treatment.treatment_code}. Defaulting to 1.")
        number_required = 1
    
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
    
    # Get all bookings for this date (including draft and scheduled)
    # This ensures we catch all nurse treatments, even if they're still in draft status
    scheduled_bookings = Booking.objects.filter(
        date=target_date,
        status__in=['scheduled', 'draft', 'in_progress']  # Include all statuses to catch all nurse treatments
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
                
                # Allocate nurses - ensure we always get at least one
                assignments = allocate_nurses_for_booking(booking)
                if assignments:
                    total_allocated += len(assignments)
                else:
                    # Log warning if no nurses were allocated (should not happen)
                    errors.append(f"Warning: No nurses allocated for booking {booking.id} (nurse treatment: {booking.allocation.therapy_name})")
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

