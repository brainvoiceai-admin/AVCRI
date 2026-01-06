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

        // Auto-generate therapist code if not provided
        document.getElementById('id_therapist_name').addEventListener('blur', function() {
            const therapistCodeField = document.getElementById('id_therapist_code');
            if (!therapistCodeField.value && this.value) {
                const name = this.value.trim();
                const initials = name.split(' ').map(word => word.charAt(0)).join('').toUpperCase();
                const code = 'TH' + initials + Math.floor(Math.random() * 1000).toString().padStart(3, '0');
                therapistCodeField.value = code;
            }
        });

        // Auto-generate employee code if not provided
        document.getElementById('id_therapist_code').addEventListener('blur', function() {
            const employeeCodeField = document.getElementById('id_employee_code');
            if (!employeeCodeField.value && this.value) {
                employeeCodeField.value = 'EMP' + this.value;
            }
        });