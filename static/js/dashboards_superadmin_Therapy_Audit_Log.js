function exportLogs() {
      // Get current URL parameters
      const urlParams = new URLSearchParams(window.location.search);
      const base = window.THERAPY_AUDIT_LOG_EXPORT_BASE || '/authentication/Therapy_Audit_Log/dashboard/';
      let exportUrl = base;
      const query = urlParams.toString();
      if (query) {
        exportUrl += '?' + query + '&export=csv';
      } else {
        exportUrl += '?export=csv';
      }
      window.open(exportUrl, '_blank');
    }

    function refreshLogs() {
      window.location.reload();
    }

    // Auto-refresh every 30 seconds
    setInterval(function() {
      // Only refresh if no filters are applied (to avoid disrupting user's current view)
      if (!window.location.search) {
        window.location.reload();
      }
    }, 30000);