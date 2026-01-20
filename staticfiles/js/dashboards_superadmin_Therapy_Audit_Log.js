function exportLogs() {
      // Get current URL parameters
      const urlParams = new URLSearchParams(window.location.search);
      const exportUrl = '{% url "authentication:Therapy_Audit_Log" %}' + '?' + urlParams.toString() + '&export=csv';
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