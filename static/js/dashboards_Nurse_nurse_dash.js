// Simple function to simulate validation
        function validateTherapy(button, status) {
            const row = button.closest('tr');
            const statusCell = row.children[4];
            const actionsCell = row.children[5];
            
            row.classList.remove('action-needed');
            
            if (status === 'Done') {
                statusCell.innerHTML = '<span class="badge rounded-pill text-bg-success status-badge">Validated (Done)</span>';
            } else {
                statusCell.innerHTML = '<span class="badge rounded-pill text-bg-secondary status-badge">Validated (Not Done)</span>';
            }
            
            actionsCell.innerHTML = '<button class="btn btn-outline-secondary btn-sm" data-bs-toggle="modal" data-bs-target="#notesModal"><i class="bi bi-eye"></i> View Note</button>';
        }