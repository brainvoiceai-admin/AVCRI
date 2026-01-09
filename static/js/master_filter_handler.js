/**
 * Shared Filter Handler for Master Screens
 * This script enforces consistent filter behavior across all master modules.
 * Behavior: Trigger filtering ONLY on Enter keypress (in search input) or Filter button click.
 */

const MasterFilterHandler = (function () {
    // Private configuration
    let config = {
        searchInputId: 'searchInput',
        filterButtonId: 'filterButton',
        filterFormId: 'filterForm',
        clearButtonId: 'clearFilters',
        onFilter: null // Optional callback for client-side filtering
    };

    /**
     * Initialize the filter handler
     * @param {Object} options - Configuration overrides
     */
    function init(options) {
        config = { ...config, ...options };

        let searchInput = document.getElementById(config.searchInputId);
        const filterButton = document.getElementById(config.filterButtonId) || document.querySelector('button[type="submit"]');
        const clearButton = document.getElementById(config.clearButtonId);
        const filterForm = document.getElementById(config.filterFormId);

        if (searchInput) {
            // Clone the element to definitively remove any direct listeners
            const newSearchInput = searchInput.cloneNode(true);
            newSearchInput.value = searchInput.value; // Ensure value is preserved
            searchInput.parentNode.replaceChild(newSearchInput, searchInput);
            searchInput = newSearchInput;

            // Handle Enter key for filtering
            searchInput.addEventListener('keydown', function (event) {
                if (event.key === 'Enter') {
                    event.preventDefault();
                    event.stopPropagation(); // Stop bubbling
                    triggerFilter();
                }
            });

            // Explicitly prevent any unintentional input-based filtering from bubbling up
            // This blocks delegated events (e.g., $(document).on('keyup', ...))
            const blockEvent = (e) => e.stopPropagation();

            searchInput.addEventListener('input', blockEvent);
            searchInput.addEventListener('keyup', function (e) {
                if (e.key !== 'Enter') e.stopPropagation();
            });
            searchInput.addEventListener('keypress', function (e) {
                if (e.key !== 'Enter') e.stopPropagation();
            });
            searchInput.addEventListener('change', blockEvent);
        }

        if (filterButton) {
            // Remove type="submit" if we want to handle it purely via JS, 
            // but keeping it as submit is fine if we have a form.
            filterButton.addEventListener('click', function (event) {
                if (!filterForm || filterButton.getAttribute('type') !== 'submit') {
                    event.preventDefault();
                    triggerFilter();
                }
            });
        }

        if (clearButton) {
            clearButton.addEventListener('click', function (event) {
                // If it's a link to the manage page, let it be.
                // If it's a button, handle clearing.
                if (clearButton.tagName === 'BUTTON' || clearButton.getAttribute('href') === '#') {
                    event.preventDefault();
                    clearFilters();
                }
            });
        }
    }

    /**
     * Execute the filter logic
     */
    function triggerFilter() {
        const filterForm = document.getElementById(config.filterFormId);

        if (config.onFilter && typeof config.onFilter === 'function') {
            // Custom client-side filtering callback
            config.onFilter();
        } else if (filterForm) {
            // Standard server-side filtering via form submission
            filterForm.submit();
        } else if (typeof window.filterTable === 'function') {
            // Fallback to legacy window-level filterTable if it exists
            window.filterTable();
        }
    }

    /**
     * Reset all filters
     */
    function clearFilters() {
        const searchInput = document.getElementById(config.searchInputId);
        const statusFilter = document.getElementById('statusFilter');
        const filterForm = document.getElementById(config.filterFormId);

        if (searchInput) searchInput.value = '';
        if (statusFilter) statusFilter.value = '';

        if (filterForm) {
            filterForm.submit();
        } else if (typeof window.filterTable === 'function') {
            window.filterTable();
        } else if (config.onFilter) {
            config.onFilter();
        }
    }

    /**
     * Generic Client-Side Table Filter 
     * Can be used as the onFilter callback
     */
    function genericTableFilter(tableId, searchableColumnIndices = null, statusColumnIndex = null) {
        const searchTerm = document.getElementById(config.searchInputId).value.toLowerCase();
        const statusFilter = document.getElementById('statusFilter') ? document.getElementById('statusFilter').value.toLowerCase() : '';
        const table = document.getElementById(tableId);

        if (!table) return;
        const tbody = table.querySelector('tbody');
        if (!tbody) return;
        const rows = tbody.querySelectorAll('tr');

        let visibleCount = 0;

        rows.forEach(row => {
            const cells = row.querySelectorAll('td');
            if (cells.length === 0) return;

            let showRow = true;

            // Search Filter (Partial match, Case-insensitive)
            if (searchTerm) {
                const indices = searchableColumnIndices || Array.from({ length: cells.length }, (_, i) => i);
                const matchesSearch = indices.some(index => {
                    const cell = cells[index];
                    return cell && cell.textContent.toLowerCase().includes(searchTerm);
                });
                if (!matchesSearch) showRow = false;
            }

            // Status Filter
            if (showRow && statusFilter && statusColumnIndex !== null) {
                const statusText = cells[statusColumnIndex].textContent.toLowerCase();
                if (statusFilter === 'active' && !statusText.includes('active')) {
                    showRow = false;
                } else if (statusFilter === 'inactive' && !statusText.includes('inactive')) {
                    showRow = false;
                }
            }

            if (showRow) {
                row.style.display = '';
                visibleCount++;
            } else {
                row.style.display = 'none';
            }
        });

        // Update count badge if exists
        const countBadge = document.getElementById('totalCount') || document.querySelector('.badge.bg-primary');
        if (countBadge) {
            countBadge.textContent = visibleCount;
        }
    }

    // Public API
    return {
        init: init,
        triggerFilter: triggerFilter,
        clearFilters: clearFilters,
        handleClientSide: genericTableFilter
    };
})();

// Export for use in other scripts
window.MasterFilterHandler = MasterFilterHandler;
