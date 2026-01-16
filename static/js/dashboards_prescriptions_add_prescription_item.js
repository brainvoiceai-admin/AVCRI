$(function(){
      // When item selection changes, fetch details and autofill procured_from and item_uom (only)
      $('#item_select').on('change', function(){
        const code = $(this).val();
        if (!code) {
          $('#item_uom').val('');
          $('#procured_from').val('');
          return;
        }
        fetch(`/get-item-details/?item_code=${encodeURIComponent(code)}`)
          .then(r => r.json())
          .then(data => {
            // Only autofill procured_from and item_uom as requested
            $('#item_uom').val(data.item_uom || '');
            $('#procured_from').val(data.procured_from || '');
            // do NOT auto-fill dates; do NOT auto-fill internal/external
          })
          .catch(err => {
            console.error('failed to fetch item details', err);
          });
      });

      // Compute days when from/to changed (keeps days in sync but doesn't auto-fill dates)
      $('#from_date, #to_date').on('change', function(){
        const f = $('#from_date').val();
        const t = $('#to_date').val();
        if (!f || !t) {
          $('#days').val(0);
          return;
        }
        const from = new Date(f);
        const to = new Date(t);
        if (from <= to) {
          const diffMs = to - from;
          const diffDays = Math.floor(diffMs / (1000*60*60*24)) + 1;
          $('#days').val(diffDays);
        } else {
          $('#days').val(0);
        }
      });

      // Set today's date as default for from_date
      const today = new Date().toISOString().split('T')[0];
      $('#from_date').val(today);
      
      // Set to_date to 7 days from today as default
      const nextWeek = new Date();
      nextWeek.setDate(nextWeek.getDate() + 7);
      $('#to_date').val(nextWeek.toISOString().split('T')[0]);
      
      // Trigger days calculation on page load
      $('#from_date, #to_date').trigger('change');
    });