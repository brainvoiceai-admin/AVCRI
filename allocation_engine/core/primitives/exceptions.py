"""Custom exceptions for therapy allocation."""


class IncompleteAssignmentError(Exception):
    """
    Raised when not all therapist assignments could be created for a booking.
    Handled so the booking is marked as failed with a user-friendly message
    (not shown as a site error).
    """
    pass
