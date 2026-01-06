// Auto-dismiss messages after 5 seconds (exclude alerts inside modals)
        document.addEventListener('DOMContentLoaded', function() {
            const alerts = document.querySelectorAll('.alert');
            alerts.forEach(function(alert) {
                // Skip alerts inside modals or with data-no-auto-dismiss attribute
                const modal = alert.closest('.modal');
                const noAutoDismiss = alert.hasAttribute('data-no-auto-dismiss');
                if (modal || noAutoDismiss) {
                    return;
                }
                setTimeout(function() {
                    const bsAlert = new bootstrap.Alert(alert);
                    bsAlert.close();
                }, 5000);
            });
        });

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
            const table = document.getElementById('timeTable');
            
            if (!table) return;
            
            const rows = table.getElementsByTagName('tbody')[0].getElementsByTagName('tr');
            
            let visibleCount = 0;
            
            for (let i = 0; i < rows.length; i++) {
                const row = rows[i];
                const cells = row.getElementsByTagName('td');
                
                if (cells.length === 0) continue; // Skip empty rows
                
                const timeName = cells[0].textContent.toLowerCase();
                const status = cells[1].textContent.toLowerCase();
                
                let showRow = true;
                
                // Search filter
                if (searchTerm && !timeName.includes(searchTerm)) {
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
            
            // Update count badge
            const countBadge = document.getElementById('totalCount');
            if (countBadge) {
                countBadge.textContent = visibleCount;
            }
        }

        function clearFilters() {
            document.getElementById('searchInput').value = '';
            document.getElementById('statusFilter').value = '';
            filterTable();
        }