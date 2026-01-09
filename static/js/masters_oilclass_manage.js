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

        // Auto-submit form on filter change (server-side filtering)
        document.addEventListener('DOMContentLoaded', function() {
            const statusFilter = document.getElementById('statusFilter');
            const searchInput = document.getElementById('searchInput');
            const filterForm = document.getElementById('filterForm');
            
            if (statusFilter && filterForm) {
                statusFilter.addEventListener('change', function() {
                    filterForm.submit();
                });
            }
            
            // Search functionality - server-side filtering
            if (searchInput && filterForm) {
                let searchTimeout;
                
                // Submit on Enter key
                searchInput.addEventListener('keypress', function(e) {
                    if (e.key === 'Enter') {
                        e.preventDefault();
                        clearTimeout(searchTimeout);
                        filterForm.submit();
                    }
                });
                
                // Auto-submit after user stops typing (500ms delay)
                searchInput.addEventListener('input', function() {
                    clearTimeout(searchTimeout);
                    searchTimeout = setTimeout(function() {
                        filterForm.submit();
                    }, 500);
                });
            }
        });

        function clearFilters() {
            // Redirect to the page without any filters (server-side)
            window.location.href = window.location.pathname;
        }