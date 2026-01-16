// Auto-dismiss messages after 5 seconds (exclude alerts inside modals)
document.addEventListener('DOMContentLoaded', function () {
    const alerts = document.querySelectorAll('.alert');
    alerts.forEach(function (alert) {
        // Skip alerts inside modals or with data-no-auto-dismiss attribute
        const modal = alert.closest('.modal');
        const noAutoDismiss = alert.hasAttribute('data-no-auto-dismiss');
        if (modal || noAutoDismiss) {
            return;
        }
        setTimeout(function () {
            const bsAlert = new bootstrap.Alert(alert);
            bsAlert.close();
        }, 5000);
    });
});

// Initialize Filter Handler
document.addEventListener('DOMContentLoaded', function () {
    MasterFilterHandler.init({
        filterFormId: 'filterForm',
        searchInputId: 'searchInput',
        filterButtonId: 'filterButton'
    });
});