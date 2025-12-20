function deleteUser(userId, username) {
      if (confirm(`Are you sure you want to delete user "${username}"? This action cannot be undone.`)) {
        const form = document.createElement('form');
        form.method = 'POST';
        form.innerHTML = `
          {% csrf_token %}
          <input type="hidden" name="action" value="delete_user">
          <input type="hidden" name="user_id" value="${userId}">
        `;
        document.body.appendChild(form);
        form.submit();
      }
    }

    function toggleUserStatus(userId, username, activate) {
      const action = activate ? 'activate' : 'deactivate';
      const confirmMsg = activate 
        ? `Are you sure you want to activate user "${username}"?`
        : `Are you sure you want to deactivate user "${username}"?`;
      
      if (confirm(confirmMsg)) {
        const form = document.createElement('form');
        form.method = 'POST';
        form.innerHTML = `
          {% csrf_token %}
          <input type="hidden" name="action" value="toggle_user_status">
          <input type="hidden" name="user_id" value="${userId}">
          <input type="hidden" name="is_active" value="${activate ? 'true' : 'false'}">
        `;
        document.body.appendChild(form);
        form.submit();
      }
    }

    // Validation for add user form
    let usernameCheckTimeout;
    let emailCheckTimeout;
    
    document.addEventListener('DOMContentLoaded', function() {
      const usernameInput = document.getElementById('username');
      const emailInput = document.getElementById('email');
      const usernameError = document.getElementById('username-error');
      const emailError = document.getElementById('email-error');
      const addUserForm = document.querySelector('#addUserModal form');
      
      // Check username availability
      if (usernameInput) {
        usernameInput.addEventListener('input', function() {
          clearTimeout(usernameCheckTimeout);
          const username = this.value.trim();
          
          if (username.length < 3) {
            usernameError.style.display = 'none';
            return;
          }
          
          usernameCheckTimeout = setTimeout(function() {
            checkUsernameExists(username);
          }, 500); // Debounce for 500ms
        });
      }
      
      // Check email availability
      if (emailInput) {
        emailInput.addEventListener('blur', function() {
          const email = this.value.trim();
          if (email) {
            checkEmailExists(email);
          }
        });
        
        emailInput.addEventListener('input', function() {
          clearTimeout(emailCheckTimeout);
          const email = this.value.trim();
          
          if (!email) {
            emailError.style.display = 'none';
            return;
          }
          
          // Basic email validation
          const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
          if (!emailRegex.test(email)) {
            emailError.textContent = 'Please enter a valid email address.';
            emailError.style.display = 'block';
            emailInput.classList.add('is-invalid');
            return;
          } else {
            emailError.style.display = 'none';
            emailInput.classList.remove('is-invalid');
          }
          
          emailCheckTimeout = setTimeout(function() {
            checkEmailExists(email);
          }, 500); // Debounce for 500ms
        });
      }
      
      // Prevent form submission if validation fails
      if (addUserForm) {
        addUserForm.addEventListener('submit', function(e) {
          const username = usernameInput.value.trim();
          const email = emailInput.value.trim();
          
          // Check if there are any visible errors
          if (usernameError.style.display === 'block' || emailError.style.display === 'block') {
            e.preventDefault();
            alert('Please fix the errors before submitting the form.');
            return false;
          }
          
          // Final synchronous check before submission
          if (username && email) {
            e.preventDefault();
            
            // Show loading state
            const submitBtn = addUserForm.querySelector('button[type="submit"]');
            const originalText = submitBtn.innerHTML;
            submitBtn.disabled = true;
            submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Checking...';
            
            checkUserExistsSync(username, email, function(result) {
              submitBtn.disabled = false;
              submitBtn.innerHTML = originalText;
              
              if (result.username_exists || result.email_exists) {
                if (result.username_exists) {
                  usernameError.textContent = result.username_message;
                  usernameError.style.display = 'block';
                  usernameInput.classList.add('is-invalid');
                }
                if (result.email_exists) {
                  emailError.textContent = result.email_message;
                  emailError.style.display = 'block';
                  emailInput.classList.add('is-invalid');
                }
                alert('Username or email already exists. Please use different values.');
                return false;
              } else {
                // No errors, allow submission
                addUserForm.submit();
              }
            });
            return false;
          }
        });
      }
    });
    
    function checkUsernameExists(username) {
      if (!username || username.length < 3) return;
      
      fetch(`{% url 'authentication:Manage_user' %}?action=check_user_exists&username=${encodeURIComponent(username)}`)
        .then(response => response.json())
        .then(data => {
          const usernameInput = document.getElementById('username');
          const usernameError = document.getElementById('username-error');
          
          if (data.username_exists) {
            usernameError.textContent = data.username_message;
            usernameError.style.display = 'block';
            usernameInput.classList.add('is-invalid');
          } else {
            usernameError.style.display = 'none';
            usernameInput.classList.remove('is-invalid');
          }
        })
        .catch(error => {
          console.error('Error checking username:', error);
        });
    }
    
    function checkEmailExists(email) {
      if (!email) return;
      
      // Basic email validation
      const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
      if (!emailRegex.test(email)) {
        return;
      }
      
      fetch(`{% url 'authentication:Manage_user' %}?action=check_user_exists&email=${encodeURIComponent(email)}`)
        .then(response => response.json())
        .then(data => {
          const emailInput = document.getElementById('email');
          const emailError = document.getElementById('email-error');
          
          if (data.email_exists) {
            emailError.textContent = data.email_message;
            emailError.style.display = 'block';
            emailInput.classList.add('is-invalid');
          } else {
            emailError.style.display = 'none';
            emailInput.classList.remove('is-invalid');
          }
        })
        .catch(error => {
          console.error('Error checking email:', error);
        });
    }
    
    function checkUserExistsSync(username, email, callback) {
      fetch(`{% url 'authentication:Manage_user' %}?action=check_user_exists&username=${encodeURIComponent(username)}&email=${encodeURIComponent(email)}`)
        .then(response => response.json())
        .then(data => {
          callback(data);
        })
        .catch(error => {
          console.error('Error checking user exists:', error);
          callback({username_exists: false, email_exists: false});
        });
    }
    
    // Clear errors when modal is closed
    document.addEventListener('DOMContentLoaded', function() {
      const addUserModal = document.getElementById('addUserModal');
      if (addUserModal) {
        addUserModal.addEventListener('hidden.bs.modal', function() {
          // Clear form and errors
          const form = this.querySelector('form');
          if (form) {
            form.reset();
          }
          document.getElementById('username-error').style.display = 'none';
          document.getElementById('email-error').style.display = 'none';
          document.getElementById('username').classList.remove('is-invalid');
          document.getElementById('email').classList.remove('is-invalid');
        });
      }
    });

    // Handle role-specific fields
    function toggleRoleSpecificFields(roleSelectId) {
      const roleSelect = document.getElementById(roleSelectId);
      const roleSpecificFields = document.getElementById('roleSpecificFields');
      const patientField = document.getElementById('patientRegistrationField');
      const therapistField = document.getElementById('therapistCodeField');
      const employeeField = document.getElementById('employeeCodeField');
      const pharmacyField = document.getElementById('pharmacyDepartmentField');
      
      if (roleSelect.value === 'patient') {
        roleSpecificFields.style.display = 'block';
        patientField.style.display = 'block';
        therapistField.style.display = 'none';
        employeeField.style.display = 'none';
        if (pharmacyField) pharmacyField.style.display = 'none';
        document.getElementById('patient_registration_number').required = true;
        document.getElementById('therapist_code').required = false;
        document.getElementById('employee_code').required = false;
        if (document.getElementById('department')) document.getElementById('department').required = false;
      } else if (roleSelect.value === 'therapist') {
        roleSpecificFields.style.display = 'block';
        patientField.style.display = 'none';
        therapistField.style.display = 'block';
        employeeField.style.display = 'block';
        if (pharmacyField) pharmacyField.style.display = 'none';
        document.getElementById('patient_registration_number').required = false;
        document.getElementById('therapist_code').required = true;
        document.getElementById('employee_code').required = true;
        if (document.getElementById('department')) document.getElementById('department').required = false;
      } else if (roleSelect.value === 'ip_pharmacy_staff') {
        roleSpecificFields.style.display = 'block';
        patientField.style.display = 'none';
        therapistField.style.display = 'none';
        employeeField.style.display = 'none';
        if (pharmacyField) pharmacyField.style.display = 'block';
        document.getElementById('patient_registration_number').required = false;
        document.getElementById('therapist_code').required = false;
        document.getElementById('employee_code').required = false;
        if (document.getElementById('department')) document.getElementById('department').required = true;
      } else {
        roleSpecificFields.style.display = 'none';
        patientField.style.display = 'none';
        therapistField.style.display = 'none';
        employeeField.style.display = 'none';
        if (pharmacyField) pharmacyField.style.display = 'none';
        document.getElementById('patient_registration_number').required = false;
        document.getElementById('therapist_code').required = false;
        document.getElementById('employee_code').required = false;
        if (document.getElementById('department')) document.getElementById('department').required = false;
      }
    }

    // Add event listeners when page loads
    document.addEventListener('DOMContentLoaded', function() {
      const roleSelect = document.getElementById('role');
      if (roleSelect) {
        roleSelect.addEventListener('change', function() {
          toggleRoleSpecificFields('role');
        });
      }
      
      // Handle edit modals
      {% for user in users %}
      const editRoleSelect{{ user.id }} = document.getElementById('edit_role{{ user.id }}');
      if (editRoleSelect{{ user.id }}) {
        editRoleSelect{{ user.id }}.addEventListener('change', function() {
          toggleEditRoleSpecificFields('edit_role{{ user.id }}', {{ user.id }});
        });
        // Initialize on page load
        toggleEditRoleSpecificFields('edit_role{{ user.id }}', {{ user.id }});
      }
      {% endfor %}
    });

    // Handle edit role-specific fields
    function toggleEditRoleSpecificFields(roleSelectId, userId) {
      const roleSelect = document.getElementById(roleSelectId);
      const roleSpecificFields = document.getElementById('editRoleSpecificFields' + userId);
      const patientField = document.getElementById('editPatientRegistrationField' + userId);
      const therapistField = document.getElementById('editTherapistCodeField' + userId);
      const employeeField = document.getElementById('editEmployeeCodeField' + userId);
      const pharmacyField = document.getElementById('editPharmacyDepartmentField' + userId);
      
      if (roleSelect.value === 'patient') {
        roleSpecificFields.style.display = 'block';
        patientField.style.display = 'block';
        therapistField.style.display = 'none';
        if (employeeField) employeeField.style.display = 'none';
        if (pharmacyField) pharmacyField.style.display = 'none';
        document.getElementById('edit_patient_registration_number' + userId).required = true;
        document.getElementById('edit_therapist_code' + userId).required = false;
        if (document.getElementById('edit_employee_code' + userId)) document.getElementById('edit_employee_code' + userId).required = false;
        if (document.getElementById('edit_department' + userId)) document.getElementById('edit_department' + userId).required = false;
      } else if (roleSelect.value === 'therapist') {
        roleSpecificFields.style.display = 'block';
        patientField.style.display = 'none';
        therapistField.style.display = 'block';
        if (employeeField) employeeField.style.display = 'block';
        if (pharmacyField) pharmacyField.style.display = 'none';
        document.getElementById('edit_patient_registration_number' + userId).required = false;
        document.getElementById('edit_therapist_code' + userId).required = true;
        if (document.getElementById('edit_employee_code' + userId)) document.getElementById('edit_employee_code' + userId).required = true;
        if (document.getElementById('edit_department' + userId)) document.getElementById('edit_department' + userId).required = false;
      } else if (roleSelect.value === 'ip_pharmacy_staff') {
        roleSpecificFields.style.display = 'block';
        patientField.style.display = 'none';
        therapistField.style.display = 'none';
        if (employeeField) employeeField.style.display = 'none';
        if (pharmacyField) pharmacyField.style.display = 'block';
        document.getElementById('edit_patient_registration_number' + userId).required = false;
        document.getElementById('edit_therapist_code' + userId).required = false;
        if (document.getElementById('edit_employee_code' + userId)) document.getElementById('edit_employee_code' + userId).required = false;
        if (document.getElementById('edit_department' + userId)) document.getElementById('edit_department' + userId).required = true;
      } else {
        roleSpecificFields.style.display = 'none';
        patientField.style.display = 'none';
        therapistField.style.display = 'none';
        if (employeeField) employeeField.style.display = 'none';
        if (pharmacyField) pharmacyField.style.display = 'none';
        document.getElementById('edit_patient_registration_number' + userId).required = false;
        document.getElementById('edit_therapist_code' + userId).required = false;
        if (document.getElementById('edit_employee_code' + userId)) document.getElementById('edit_employee_code' + userId).required = false;
        if (document.getElementById('edit_department' + userId)) document.getElementById('edit_department' + userId).required = false;
      }
    }

    function changeRole(userId, username, currentRole) {
      // Show role change modal
      const modal = new bootstrap.Modal(document.getElementById('roleChangeModal'));
      document.getElementById('roleChangeUserId').value = userId;
      document.getElementById('roleChangeUsername').textContent = username;
      document.getElementById('roleChangeCurrentRole').textContent = currentRole;
      modal.show();
    }

    function confirmRoleChange() {
      const userId = document.getElementById('roleChangeUserId').value;
      const newRole = document.getElementById('newRole').value;
      
      if (!newRole) {
        alert('Please select a new role');
        return;
      }
      
      if (newRole === document.getElementById('roleChangeCurrentRole').textContent) {
        alert('Please select a different role');
        return;
      }
      
      // Redirect to role change confirmation page
      window.location.href = `/authentication/confirm-role-change/${userId}/?new_role=${newRole}`;
    }