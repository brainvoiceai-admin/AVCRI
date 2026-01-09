// Search functionality
        document.getElementById('searchInput').addEventListener('input', function() {
            filterTable();
        });

        // Filter functionality
        document.getElementById('statusFilter').addEventListener('change', function() {
            filterTable();
        });

        function filterTable() {
            const searchTerm = document.getElementById('searchInput').value.toLowerCase();
            const statusFilter = document.getElementById('statusFilter').value;
            const table = document.getElementById('ingredientTable');
            const rows = table.getElementsByTagName('tbody')[0].getElementsByTagName('tr');
            
            let visibleCount = 0;
            
            for (let i = 0; i < rows.length; i++) {
                const row = rows[i];
                const cells = row.getElementsByTagName('td');
                
                if (cells.length === 0) continue; // Skip empty rows
                
                const ingredientCode = cells[0].textContent.toLowerCase();
                const ingredientName = cells[1].textContent.toLowerCase();
                const status = cells[3].textContent.toLowerCase();
                
                let showRow = true;
                
                // Search filter
                if (searchTerm && !ingredientCode.includes(searchTerm) && !ingredientName.includes(searchTerm)) {
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