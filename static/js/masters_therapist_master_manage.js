// Auto-submit form on filter change (server-side filtering)
document.addEventListener('DOMContentLoaded', function() {
    const statusFilter = document.getElementById('statusFilter');
    const gradeFilter = document.getElementById('gradeFilter');
    const searchInput = document.getElementById('searchInput');
    const filterForm = document.getElementById('filterForm');
    
    if (statusFilter && filterForm) {
        statusFilter.addEventListener('change', function() {
            filterForm.submit();
        });
    }
    
    if (gradeFilter && filterForm) {
        gradeFilter.addEventListener('change', function() {
            filterForm.submit();
        });
    }
    
    // Search input - submit on Enter key or after typing stops
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