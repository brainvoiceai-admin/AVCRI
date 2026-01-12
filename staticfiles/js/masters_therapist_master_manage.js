// Auto-submit form on filter change (optional - can be removed if you prefer manual submit)
        document.getElementById('statusFilter').addEventListener('change', function() {
            document.getElementById('filterForm').submit();
        });

        document.getElementById('gradeFilter').addEventListener('change', function() {
            document.getElementById('filterForm').submit();
        });