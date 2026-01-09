// Initialize Filter Handler
document.addEventListener('DOMContentLoaded', function () {
    MasterFilterHandler.init({
        filterFormId: 'filterForm',
        searchInputId: 'searchInput',
        filterButtonId: 'filterButton'
    });
});

// We can keep the filterTable function if we want to support client-side filtering without reload,
// but for masters with pagination, form submission is preferred.
// If we want to use client-side filtering, we would pass onFilter: () => MasterFilterHandler.handleClientSide('ingredientTable', [0, 1], 3) to init().
