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
            const searchTerm = document.getElementById('searchInput').value.toLowerCase();
            const statusFilter = document.getElementById('statusFilter').value;
            const timeFilter = document.getElementById('timeFilter').value;
            const table = document.getElementById('slotTable');
            const rows = table.getElementsByTagName('tbody')[0].getElementsByTagName('tr');
            
            let visibleCount = 0;
            
            for (let i = 0; i < rows.length; i++) {
                const row = rows[i];
                const cells = row.getElementsByTagName('td');
                
                if (cells.length === 0) continue; // Skip empty rows
                
                const slotNumber = cells[0].textContent.toLowerCase();
                const slotName = cells[1].textContent.toLowerCase();
                const slotTime = cells[2].textContent.toLowerCase();
                const status = cells[3].textContent.toLowerCase();
                
                let showRow = true;
                
                // Search filter
                if (searchTerm && !slotNumber.includes(searchTerm) && !slotName.includes(searchTerm)) {
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
                
                // Time filter (convert 24hr to 12hr for comparison)
                if (timeFilter) {
                    const time24 = timeFilter;
                    const [hours, minutes] = time24.split(':');
                    const hour = parseInt(hours, 10);
                    const ampm = hour >= 12 ? 'PM' : 'AM';
                    const hour12 = hour % 12 || 12;
                    const time12 = `${hour12}:${minutes} ${ampm}`.toLowerCase();
                    if (!slotTime.includes(time12)) {
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
            document.getElementById('timeFilter').value = '';
            filterTable();
        }