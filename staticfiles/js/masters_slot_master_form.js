// Form validation
        (function() {
            'use strict';
            window.addEventListener('load', function() {
                var forms = document.getElementsByClassName('needs-validation');
                var validation = Array.prototype.filter.call(forms, function(form) {
                    form.addEventListener('submit', function(event) {
                        if (form.checkValidity() === false) {
                            event.preventDefault();
                            event.stopPropagation();
                        }
                        form.classList.add('was-validated');
                    }, false);
                });
            }, false);
        })();
        
        // Convert 24-hour time to 12-hour format for preview
        function formatTime12Hour(time24) {
            if (!time24) return '-';
            const [hours, minutes] = time24.split(':');
            const hour = parseInt(hours, 10);
            const ampm = hour >= 12 ? 'PM' : 'AM';
            const hour12 = hour % 12 || 12;
            return `${hour12}:${minutes} ${ampm}`;
        }
        
        // Update time preview
        const slotTimeField = document.getElementById('id_slot_time');
        const timePreview = document.getElementById('timePreview');
        
        if (slotTimeField) {
            slotTimeField.addEventListener('change', function() {
                const time24 = this.value;
                if (time24) {
                    timePreview.textContent = formatTime12Hour(time24);
                } else {
                    timePreview.textContent = '-';
                }
            });
            
            // Set initial preview
            if (slotTimeField.value) {
                timePreview.textContent = formatTime12Hour(slotTimeField.value);
            }
        }