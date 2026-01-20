// Auto-calculate days when dates change
    document.addEventListener('DOMContentLoaded', function() {
      const fromDate = document.querySelector('input[name="from_date"]');
      const toDate = document.querySelector('input[name="to_date"]');

      function validateDates() {
        if (fromDate.value && toDate.value) {
          const from = new Date(fromDate.value);
          const to = new Date(toDate.value);
          
          if (from > to) {
            alert('To date cannot be earlier than from date');
            toDate.value = fromDate.value;
          }
        }
      }

      fromDate.addEventListener('change', validateDates);
      toDate.addEventListener('change', validateDates);
    });