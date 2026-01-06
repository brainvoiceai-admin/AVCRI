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

        // Form submission only on button click - no auto-filtering
        document.addEventListener('DOMContentLoaded', function() {
            const searchInput = document.getElementById('searchInput');
            const filterForm = document.getElementById('filterForm');
            
            // Allow Enter key to submit the form
            if (searchInput && filterForm) {
                searchInput.addEventListener('keypress', function(e) {
                    if (e.key === 'Enter') {
                        e.preventDefault();
                        filterForm.submit();
                    }
                });
            }
        });

        function clearFilters() {
            // Redirect to the page without any filters (server-side)
            window.location.href = window.location.pathname;
        }