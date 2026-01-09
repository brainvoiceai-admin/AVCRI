// Initialize Filter Handler
document.addEventListener('DOMContentLoaded', function () {
    MasterFilterHandler.init({
        filterFormId: 'filterForm',
        searchInputId: 'searchInput',
        filterButtonId: 'filterButton'
    });

    // Auto-dismiss messages after 5 seconds
    const alerts = document.querySelectorAll('.alert');
    alerts.forEach(function (alert) {
        const modal = alert.closest('.modal');
        const noAutoDismiss = alert.hasAttribute('data-no-auto-dismiss');
        if (modal || noAutoDismiss) return;
        setTimeout(function () {
            const bsAlert = new bootstrap.Alert(alert);
            bsAlert.close();
        }, 5000);
    });
});
