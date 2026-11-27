"""Pure staying-room to treatment-room mapping primitive (Layer 1A, zero DB queries)."""
import re


def get_treatment_rooms_for_staying_room(patient_staying_room):
    """
    Returns ordered list of treatment room numbers to check based on patient staying room.
    Returns empty list if no match found or for OP-* prefixes.

    Rules:
    - DS-1 to DS-6: TR-1/TR-2 -> TR-3/TR-4 -> TR-7/TR-8
    - NR-7 to NR-14: TR-3/TR-4 -> TR-7/TR-8 -> TR-11/TR-12
    - NR-15 to NR-21: TR-5/TR-6 -> TR-7/TR-8 -> TR-11/TR-12 -> TR-9/TR-10/TR-13/TR-14
    - NR-22 to NR-27: TR-7/TR-8 -> TR-5/TR-6 -> TR-11/TR-12 -> TR-9/TR-10/TR-13/TR-14
    - NR-28 to NR-33: TR-15/TR-16
    - MG-1 to MG-10, CB-1/CB-2, FG-1 to FG-12: TR-9 to TR-14 -> TR-7/TR-8
    - CT-1, CT-2, etc.: TRC-1, TRC-2, etc. (same number)
    """
    if not patient_staying_room:
        return []

    staying_room = str(patient_staying_room).strip().upper()
    match = re.match(r'([A-Z]+)-?(\d+)', staying_room)
    if not match:
        return []

    prefix = match.group(1)
    try:
        room_num = int(match.group(2))
    except ValueError:
        return []

    if prefix == 'DS' and 1 <= room_num <= 6:
        return ['TR-1', 'TR-2', 'TR-3', 'TR-4', 'TR-7', 'TR-8']

    if prefix == 'NR' and 7 <= room_num <= 14:
        return ['TR-3', 'TR-4', 'TR-7', 'TR-8', 'TR-11', 'TR-12']

    if prefix == 'NR' and 15 <= room_num <= 21:
        return ['TR-5', 'TR-6', 'TR-7', 'TR-8', 'TR-11', 'TR-12', 'TR-9', 'TR-10', 'TR-13', 'TR-14']

    if prefix == 'NR' and 22 <= room_num <= 27:
        return ['TR-7', 'TR-8', 'TR-5', 'TR-6', 'TR-11', 'TR-12', 'TR-9', 'TR-10', 'TR-13', 'TR-14']

    if prefix == 'NR' and 28 <= room_num <= 33:
        return ['TR-15', 'TR-16']

    if prefix == 'MG' and 1 <= room_num <= 10:
        return ['TR-9', 'TR-10', 'TR-11', 'TR-12', 'TR-13', 'TR-14', 'TR-7', 'TR-8']
    if prefix == 'CB' and room_num in [1, 2]:
        return ['TR-9', 'TR-10', 'TR-11', 'TR-12', 'TR-13', 'TR-14', 'TR-7', 'TR-8']
    if prefix == 'FG' and 1 <= room_num <= 12:
        return ['TR-9', 'TR-10', 'TR-11', 'TR-12', 'TR-13', 'TR-14', 'TR-7', 'TR-8']

    if prefix == 'CT':
        return [f'TRC-{room_num}']

    if prefix == 'OP':
        return []

    return []
