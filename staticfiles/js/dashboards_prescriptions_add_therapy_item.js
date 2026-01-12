(function($){
      $(function(){
        const $therapy = $('#therapy_select');
        const $item = $('#item_select');
        const $from = $('#from_date');
        const $to = $('#to_date');
        const $days = $('#days');
        const $proc = $('#procured');
        const $oil = $('#oil_class');

        // When therapy changes, set from/to/days from data- attributes
        $therapy.on('change', function(){
          const opt = $(this).find('option:selected');
          const from = opt.data('from') || '';
          const to = opt.data('to') || '';
          const days = opt.data('days') || '';

          // put into inputs (HTML date expects YYYY-MM-DD)
          $from.val(from);
          $to.val(to);
          $days.val(days !== undefined ? days : '');

          // If no item is selected yet, attempt to prefill item-related fields if item present on option
        });

        // When item changes, autofill procured_from, oil and (uom if needed)
        $('#item_select').on('change', function(){
          const opt = $(this).find('option:selected');
          const procured_from = opt.attr('data-procured-from') || '';
          const oil = opt.attr('data-oil') || '';

          $('#procured').val(procured_from);
          $('#oil_class').val(oil);
        });

        // recompute days if dates edited manually
        function recomputeDays(){
          const f = $from.val();
          const t = $to.val();
          if (!f || !t) {
            $days.val('');
            return;
          }
          const fromDt = new Date(f);
          const toDt = new Date(t);
          if (fromDt <= toDt) {
            const diff = Math.floor((toDt - fromDt) / (1000*60*60*24)) + 1;
            $days.val(diff);
          } else {
            $days.val(0);
          }
        }
        $from.add($to).on('change', recomputeDays);

        // Pre-select first therapy option on load for convenience and trigger change to fill dates
        // (skip index 0 because that's the placeholder)
        const firstTherOpt = $therapy.find('option').eq(1);
        if (firstTherOpt.length && !$therapy.val()) {
          firstTherOpt.prop('selected', true);
          $therapy.trigger('change');
        }

        // Optionally pre-select first item too (not required)
        const firstItemOpt = $item.find('option').eq(1);
        if (firstItemOpt.length && !$item.val()) {
          firstItemOpt.prop('selected', true);
          $item.trigger('change');
        }
      });
    })(jQuery);