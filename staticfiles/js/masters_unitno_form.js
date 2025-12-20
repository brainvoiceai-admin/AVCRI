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

        // Auto-suggest common units
        document.getElementById('id_unit_name').addEventListener('input', function() {
            const value = this.value.toLowerCase();
            const commonUnits = ['kg', 'gram', 'liter', 'ml', 'piece', 'meter', 'cm', 'inch', 'pound', 'gallon'];
            
            if (commonUnits.includes(value)) {
                this.classList.add('is-valid');
            }
        });