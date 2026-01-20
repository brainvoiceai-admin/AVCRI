// Auto-dismiss messages after 5 seconds (exclude alerts inside modals)
        document.addEventListener('DOMContentLoaded', function() {
            const alerts = document.querySelectorAll('.alert');
            alerts.forEach(function(alert) {
                // Skip alerts inside modals or with data-no-auto-dismiss attribute
                const modal = alert.closest('.modal');
                const noAutoDismiss = alert.hasAttribute('data-no-auto-dismiss');
                if (modal || noAutoDismiss) {
                    return;
                }
                setTimeout(function() {
                    const bsAlert = new bootstrap.Alert(alert);
                    bsAlert.close();
                }, 5000);
            });
        });

        // Auto-submit form on filter change
        document.getElementById('statusFilter').addEventListener('change', function() {
            document.getElementById('filterForm').submit();
        });

        // Optional: Auto-submit on search after debounce
        let searchTimeout;
        document.getElementById('searchInput').addEventListener('input', function() {
            clearTimeout(searchTimeout);
            searchTimeout = setTimeout(function() {
                document.getElementById('filterForm').submit();
            }, 500); // Submit after 500ms of no typing
        });