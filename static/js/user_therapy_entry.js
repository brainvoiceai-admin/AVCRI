// User Therapy Entry Dashboard JavaScript
document.addEventListener('DOMContentLoaded', function () {
    // Tab switching
    setupEventListeners();
});

function setupEventListeners() {
    // Tab switching
    document.querySelectorAll('.tab').forEach(tab => {
        tab.addEventListener('click', function () {
            // Remove active class from all tabs and contents
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));

            // Add active class to clicked tab and corresponding content
            this.classList.add('active');
            document.getElementById(this.dataset.tab).classList.add('active');
        });
    });

    // Apply filters button
    const applyFiltersBtn = document.getElementById('apply-filters-btn');
    if (applyFiltersBtn) {
        applyFiltersBtn.addEventListener('click', applyFilters);
    }

    // Clear filters button
    const clearFiltersBtn = document.getElementById('clear-filters-btn');
    if (clearFiltersBtn) {
        clearFiltersBtn.addEventListener('click', clearFilters);
    }

    // Allow Enter key on date filter
    const dateFilter = document.getElementById('date-filter');
    if (dateFilter) {
        dateFilter.addEventListener('keyup', function (event) {
            if (event.key === 'Enter') {
                applyFilters();
            }
        });
    }
}

function applyFilters() {
    const dateFilter = document.getElementById('date-filter').value;

    // Build URL with date filter only
    const params = new URLSearchParams();
    if (dateFilter) {
        params.append('date', dateFilter);
    }

    // Reload page with filter
    const url = window.location.pathname + (params.toString() ? '?' + params.toString() : '');
    window.location.href = url;
}

function clearFilters() {
    // Clear date filter input
    document.getElementById('date-filter').value = '';

    // Reload page without filters
    window.location.href = window.location.pathname;
}
