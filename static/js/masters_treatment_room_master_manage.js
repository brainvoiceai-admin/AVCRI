// Auto-submit form on filter change
        document.getElementById('statusFilter').addEventListener('change', function() {
            document.getElementById('filterForm').submit();
        });

        // Optional: Auto-submit on search after debounce
        let searchTimeout;
        document.getElementById('searchInput').addEventListener('input', function() {
            clearTimeout(searchTimeout);
            searchTimeout = setTimeout(function() {
                document.getElementById('filterForm').submit();
            }, 500); // Submit after 500ms of no typing
        });

        function filterTable() {
            const searchTerm = document.getElementById('searchInput').value.toLowerCase();
            const statusFilter = document.getElementById('statusFilter').value;
            const table = document.getElementById('roomTable');
            const rows = table.getElementsByTagName('tbody')[0].getElementsByTagName('tr');
            
            let visibleCount = 0;
            
            for (let i = 0; i < rows.length; i++) {
                const row = rows[i];
                const cells = row.getElementsByTagName('td');
                
                if (cells.length === 0) continue; // Skip empty rows
                
                const roomNo = cells[0].textContent.toLowerCase();
                const trCode = cells[1].textContent.toLowerCase();
                const floor = cells[2].textContent.toLowerCase();
                const description = cells[3].textContent.toLowerCase();
                const status = cells[4].textContent.toLowerCase();
                
                let showRow = true;
                
                // Search filter
                if (searchTerm && !roomNo.includes(searchTerm) && !trCode.includes(searchTerm) && 
                    !floor.includes(searchTerm) && !description.includes(searchTerm)) {
                    showRow = false;
                }
                
                // Status filter
                if (statusFilter) {
                    if (statusFilter === 'active' && !status.includes('active')) {
                        showRow = false;
                    } else if (statusFilter === 'inactive' && !status.includes('inactive')) {
                        showRow = false;
                    }
                }
                
                if (showRow) {
                    row.style.display = '';
                    visibleCount++;
                } else {
                    row.style.display = 'none';
                }
            }
            
            document.getElementById('totalCount').textContent = visibleCount;
        }

        function clearFilters() {
            document.getElementById('searchInput').value = '';
            document.getElementById('statusFilter').value = '';
            filterTable();
        }