// Auto-submit form on filter change
        document.getElementById('statusFilter').addEventListener('change', function() {
            document.getElementById('filterForm').submit();
        });

        document.getElementById('categoryFilter').addEventListener('change', function() {
            document.getElementById('filterForm').submit();
        });

        // Optional: Auto-submit on search after debounce (remove if you prefer manual submit)
        let searchTimeout;
        document.getElementById('searchInput').addEventListener('input', function() {
            clearTimeout(searchTimeout);
            searchTimeout = setTimeout(function() {
                document.getElementById('filterForm').submit();
            }, 500); // Submit after 500ms of no typing
        });