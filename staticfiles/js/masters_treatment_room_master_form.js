// Add form validation and styling
        document.addEventListener('DOMContentLoaded', function() {
            // Style form fields (excluding checkboxes)
            const formFields = document.querySelectorAll('input:not([type="checkbox"]), select, textarea');
            formFields.forEach(field => {
                field.classList.add('form-control');
            });
            
            // Style checkboxes properly
            const checkboxes = document.querySelectorAll('input[type="checkbox"]');
            checkboxes.forEach(checkbox => {
                checkbox.classList.add('form-check-input');
            });
            
            // Add required field indicators
            const requiredFields = document.querySelectorAll('input[required], select[required]');
            requiredFields.forEach(field => {
                field.classList.add('border-primary');
            });
        });