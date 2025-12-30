// Get CSRF token from meta tag or cookie
function getCsrfToken() {
  // Try to get from meta tag first
  const metaTag = document.querySelector('meta[name="csrf-token"]');
  if (metaTag) {
    return metaTag.getAttribute('content');
  }
  // Fallback: try to get from cookie
  const name = 'csrftoken';
  let cookieValue = null;
  if (document.cookie && document.cookie !== '') {
    const cookies = document.cookie.split(';');
    for (let i = 0; i < cookies.length; i++) {
      const cookie = cookies[i].trim();
      if (cookie.substring(0, name.length + 1) === (name + '=')) {
        cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
        break;
      }
    }
  }
  return cookieValue;
}

function deleteUser(userId, username) {
  if (confirm(`Are you sure you want to delete user "${username}"? This action cannot be undone.`)) {
    const csrfToken = getCsrfToken();
    if (!csrfToken) {
      alert('Error: CSRF token not found. Please refresh the page and try again.');
      return;
    }
    const form = document.createElement('form');
    form.method = 'POST';
    form.action = window.location.pathname;
    form.innerHTML = `
      <input type="hidden" name="csrfmiddlewaretoken" value="${csrfToken}">
      <input type="hidden" name="action" value="delete_user">
      <input type="hidden" name="user_id" value="${userId}">
    `;
    document.body.appendChild(form);
    form.submit();
  }
}

function toggleUserStatus(userId, username, activate) {
  console.log('toggleUserStatus called with:', { userId, username, activate });
  try {
    // Ensure username is a string and escape it for display
    const safeUsername = String(username || 'Unknown');
    const action = activate ? 'activate' : 'deactivate';
    const confirmMsg = activate 
      ? `Are you sure you want to activate user "${safeUsername}"?`
      : `Are you sure you want to deactivate user "${safeUsername}"?`;
    
    if (confirm(confirmMsg)) {
      const csrfToken = getCsrfToken();
      if (!csrfToken) {
        alert('Error: CSRF token not found. Please refresh the page and try again.');
        console.error('CSRF token not found');
        return false;
      }
      
      // Create form element
      const form = document.createElement('form');
      form.method = 'POST';
      form.action = window.location.pathname + window.location.search; // Preserve query parameters
      form.style.display = 'none';
      
      // Create CSRF token input
      const csrfInput = document.createElement('input');
      csrfInput.type = 'hidden';
      csrfInput.name = 'csrfmiddlewaretoken';
      csrfInput.value = csrfToken;
      form.appendChild(csrfInput);
      
      // Create action input
      const actionInput = document.createElement('input');
      actionInput.type = 'hidden';
      actionInput.name = 'action';
      actionInput.value = 'toggle_user_status';
      form.appendChild(actionInput);
      
      // Create user_id input
      const userIdInput = document.createElement('input');
      userIdInput.type = 'hidden';
      userIdInput.name = 'user_id';
      userIdInput.value = String(userId);
      form.appendChild(userIdInput);
      
      // Create is_active input
      const isActiveInput = document.createElement('input');
      isActiveInput.type = 'hidden';
      isActiveInput.name = 'is_active';
      isActiveInput.value = activate ? 'true' : 'false';
      form.appendChild(isActiveInput);
      
      // Append form to body and submit
      document.body.appendChild(form);
      console.log('Submitting toggle user status form:', {
        user_id: userId,
        username: safeUsername,
        is_active: activate ? 'true' : 'false'
      });
      form.submit();
    }
  } catch (error) {
    console.error('Error in toggleUserStatus:', error);
    alert('An error occurred. Please check the console for details.');
  }
  return false;
}

// Make sure function is globally accessible
window.toggleUserStatus = toggleUserStatus;

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
      
      // Handle toggle status buttons using event delegation
      // Use event delegation on the document body to catch all clicks
      document.body.addEventListener('click', function(e) {
        // Check if clicked element or its parent has the toggle-status-btn class
        let button = e.target;
        while (button && !button.classList.contains('toggle-status-btn')) {
          button = button.parentElement;
        }
        
        if (button && button.classList.contains('toggle-status-btn')) {
          e.preventDefault();
          e.stopPropagation();
          
          console.log('Toggle status button clicked:', button);
          
          const userId = button.getAttribute('data-user-id');
          const username = button.getAttribute('data-username');
          const activate = button.getAttribute('data-activate') === 'true';
          
          console.log('Button data:', { userId, username, activate });
          
          if (userId && username !== null) {
            // Verify function exists
            if (typeof toggleUserStatus === 'function') {
              console.log('Calling toggleUserStatus function');
              toggleUserStatus(parseInt(userId), username, activate);
            } else {
              console.error('toggleUserStatus function not found!');
              alert('Error: Function not loaded. Please refresh the page.');
            }
          } else {
            console.error('Missing data attributes on toggle button:', button);
            alert('Error: Missing user information. Please refresh the page.');
          }
          return false;
        }
      });
      
      // Also add direct event listeners to all existing toggle buttons as backup
      const toggleButtons = document.querySelectorAll('.toggle-status-btn');
      console.log('Found toggle buttons:', toggleButtons.length);
      toggleButtons.forEach(function(button) {
        button.addEventListener('click', function(e) {
          e.preventDefault();
          e.stopPropagation();
          console.log('Direct click handler triggered on button:', this);
          const userId = this.getAttribute('data-user-id');
          const username = this.getAttribute('data-username');
          const activate = this.getAttribute('data-activate') === 'true';
          
          console.log('Button data:', { userId, username, activate });
          console.log('toggleUserStatus function exists:', typeof toggleUserStatus);
          
          if (userId && username !== null) {
            if (typeof toggleUserStatus === 'function') {
              toggleUserStatus(parseInt(userId), username, activate);
            } else {
              console.error('toggleUserStatus is not a function!');
              alert('Error: Function not loaded. Please refresh the page.');
            }
          } else {
            console.error('Missing data on button:', { userId, username });
          }
          return false;
        }, true); // Use capture phase to catch event early
      });
      
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