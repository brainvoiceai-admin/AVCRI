import sys
import io

# Redirect stdout to a file with utf-8 encoding
log_file = open('reshedule_out.txt', 'w', encoding='utf-8')
sys.stdout = log_file
sys.stderr = log_file

from reshedule import expand_therapies_for_visit
try:
    res = expand_therapies_for_visit(3068, '2026-03-11', create_bookings=True)
    print("RESULT:", res)
except Exception as e:
    import traceback
    traceback.print_exc()

log_file.close()
