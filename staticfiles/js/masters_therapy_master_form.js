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

        // Auto-calculate total therapists
        function calculateTotalTherapists() {
            const superSenior = parseInt(document.getElementById('id_no_of_super_senior_therapist').value) || 0;
            const senior = parseInt(document.getElementById('id_no_of_senior_therapist').value) || 0;
            const junior = parseInt(document.getElementById('id_no_of_junior_therapist').value) || 0;
            const trainee = parseInt(document.getElementById('id_no_of_trainee_therapist').value) || 0;
            const total = superSenior + senior + junior + trainee;
            document.getElementById('id_total_no_of_therapist').value = total;
        }
        
        // Add event listeners to all therapist count fields
        document.getElementById('id_no_of_super_senior_therapist').addEventListener('input', calculateTotalTherapists);
        document.getElementById('id_no_of_senior_therapist').addEventListener('input', calculateTotalTherapists);
        document.getElementById('id_no_of_junior_therapist').addEventListener('input', calculateTotalTherapists);
        document.getElementById('id_no_of_trainee_therapist').addEventListener('input', calculateTotalTherapists);
        
        // Calculate on page load
        calculateTotalTherapists();