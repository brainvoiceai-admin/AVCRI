// Auto-calculate days when dates change
    document.addEventListener('DOMContentLoaded', function() {
      const fromDate = document.querySelector('input[name="from_date"]');
      const toDate = document.querySelector('input[name="to_date"]');
      const days = document.querySelector('input[name="days"]');

      function calculateDays() {
        if (fromDate.value && toDate.value) {
          const from = new Date(fromDate.value);
          const to = new Date(toDate.value);
          
          if (from <= to) {
            const diffTime = Math.abs(to - from);
            const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24)) + 1;
            days.value = diffDays;
          } else {
            days.value = 0;
          }
        }
      }

      fromDate.addEventListener('change', calculateDays);
      toDate.addEventListener('change', calculateDays);
    });