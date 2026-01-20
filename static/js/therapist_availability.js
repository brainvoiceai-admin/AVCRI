// Global variables
    let timeSlots = [];

    // Initialize the dashboard
    document.addEventListener('DOMContentLoaded', function() {
      // Set today's date as default
      const today = new Date().toISOString().split('T')[0];
      document.getElementById('date').value = today;
      document.getElementById('leaveDate').value = today;
      
      // Load time slots
      loadTimeSlots();
    });

    function loadTimeSlots() {
      fetch('/sheduling/therapist-availability/api/time-slots/')
        .then(response => response.json())
        .then(data => {
          if (data.success) {
            timeSlots = data.time_slots;
            populateTimeSlots();
          } else {
            console.error('Error loading time slots:', data.error);
            populateDefaultTimeSlots();
          }
        })
        .catch(error => {
          console.error('Error loading time slots:', error);
          populateDefaultTimeSlots();
        });
    }

    function populateTimeSlots() {
      const timeSelect = document.getElementById('time');
      timeSelect.innerHTML = '<option value="">-- Select Time Slot --</option>';
      
      timeSlots.forEach(slot => {
        const option = document.createElement('option');
        option.value = slot.start_time;
        option.textContent = slot.display_name;
        timeSelect.appendChild(option);
      });
    }

    function populateDefaultTimeSlots() {
      const timeSelect = document.getElementById('time');
      timeSelect.innerHTML = `
        <option value="">-- Select Time Slot --</option>
        <option value="09:00">09:00 AM - 10:00 AM</option>
        <option value="10:00">10:00 AM - 11:00 AM</option>
        <option value="14:00">02:00 PM - 03:00 PM</option>
        <option value="15:00">03:00 PM - 04:00 PM</option>
      `;
    }

    function findAvailability() {
      const date = document.getElementById('date').value;
      const time = document.getElementById('time').value;
      const gender = document.getElementById('gender').value;
      const resultDiv = document.getElementById('availableTherapists');
      const btn = document.getElementById('availabilityBtn');

      if (!date || !time || !gender) {
        alert('Please fill all filters');
        return;
      }

      // Show loading state
      btn.disabled = true;
      btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Checking...';
      
      resultDiv.innerHTML = `
        <h3><i class="fas fa-list"></i> Available Therapists</h3>
        <div class="loading">
          <i class="fas fa-spinner fa-spin"></i>
          <p>Searching for available therapists...</p>
        </div>
      `;

      // Build API URL
      const apiUrl = `/sheduling/therapist-availability/api/available-therapists/?date=${date}&time=${time}&gender=${gender}`;
      
      fetch(apiUrl)
        .then(response => response.json())
        .then(data => {
          if (data.success) {
            displayAvailableTherapists(data.therapists, data.total_count);
          } else {
            showError(resultDiv, data.error || 'Failed to fetch available therapists');
          }
        })
        .catch(error => {
          console.error('Error fetching available therapists:', error);
          showError(resultDiv, 'Error fetching available therapists');
        })
        .finally(() => {
          // Reset button state
          btn.disabled = false;
          btn.innerHTML = '<i class="fas fa-search"></i> Check Availability';
        });
    }

    function displayAvailableTherapists(therapists, totalCount) {
      const resultDiv = document.getElementById('availableTherapists');
      
      if (therapists.length > 0) {
        resultDiv.innerHTML = `
          <h3><i class="fas fa-list"></i> Available Therapists (${totalCount})</h3>
          <p style="font-size: 0.85rem; color: var(--gray); margin-bottom: 15px; font-style: italic;">
            <i class="fas fa-info-circle"></i> Results exclude therapists on Week Off and Emergency Leave
          </p>
          <ul class="therapist-list">
            ${therapists.map(t => {
              // Get gender from API response (should be 'Male', 'Female', or 'Unknown')
              const genderLower = (t.gender || '').toLowerCase();
              const isMale = genderLower === 'male' || genderLower === 'm';
              const isFemale = genderLower === 'female' || genderLower === 'f';
              const genderDisplay = isMale ? 'Male' : (isFemale ? 'Female' : (t.gender || 'Unknown'));
              const genderClass = isMale ? 'male' : (isFemale ? 'female' : 'male'); // Default to male for avatar
              const gradeDisplay = t.grade || 'N/A';
              
              return `
              <li class="therapist-item">
                <div class="therapist-avatar ${genderClass}">
                  ${isMale ? 'M' : 'F'}
                </div>
                <div class="therapist-info">
                  <div class="therapist-name">${t.name}</div>
                  <div class="therapist-details">
                    ${genderDisplay} Therapist • ${gradeDisplay}
                    ${t.is_bathing ? ' • <span class="therapist-badge">Bathing Specialist</span>' : ''}
                  </div>
                </div>
              </li>
            `;
            }).join('')}
          </ul>
        `;
        resultDiv.className = 'result success';
      } else {
        resultDiv.innerHTML = `
          <h3><i class="fas fa-list"></i> Available Therapists</h3>
          <div class="no-result">
            <i class="far fa-frown"></i>
            <p>No therapists available for selected filters.</p>
          </div>
        `;
        resultDiv.className = 'result';
      }
    }

    function checkLeaves() {
      const date = document.getElementById('leaveDate').value;
      const gender = document.getElementById('leaveGender').value;
      const resultDiv = document.getElementById('therapistLeaves');
      const btn = document.getElementById('leaveBtn');

      if (!date || !gender) {
        alert('Please select both filters');
        return;
      }

      // Show loading state
      btn.disabled = true;
      btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Checking...';
      
      resultDiv.innerHTML = `
        <h3><i class="fas fa-list"></i> Therapists on Leave</h3>
        <div class="loading">
          <i class="fas fa-spinner fa-spin"></i>
          <p>Checking leave schedules...</p>
        </div>
      `;

      // Build API URL
      const apiUrl = `/sheduling/therapist-availability/api/therapists-on-leave/?date=${date}&gender=${gender}`;
      
      fetch(apiUrl)
        .then(response => response.json())
        .then(data => {
          if (data.success) {
            displayTherapistsOnLeave(data.leaves, data.total_count);
          } else {
            showError(resultDiv, data.error || 'Failed to fetch leave information');
          }
        })
        .catch(error => {
          console.error('Error fetching leave information:', error);
          showError(resultDiv, 'Error fetching leave information');
        })
        .finally(() => {
          // Reset button state
          btn.disabled = false;
          btn.innerHTML = '<i class="fas fa-search"></i> Check Leaves';
        });
    }

    function displayTherapistsOnLeave(leaves, totalCount) {
      const resultDiv = document.getElementById('therapistLeaves');
      
      if (leaves.length > 0) {
        resultDiv.innerHTML = `
          <h3><i class="fas fa-list"></i> Therapists on Leave (${totalCount})</h3>
          <ul class="therapist-list">
            ${leaves.map(t => {
              // Get gender from API response (should be 'Male', 'Female', or 'Unknown')
              const genderLower = (t.gender || '').toLowerCase();
              const isMale = genderLower === 'male' || genderLower === 'm';
              const isFemale = genderLower === 'female' || genderLower === 'f';
              const genderDisplay = isMale ? 'Male' : (isFemale ? 'Female' : (t.gender || 'Unknown'));
              const genderClass = isMale ? 'male' : (isFemale ? 'female' : 'male'); // Default to male for avatar
              const gradeDisplay = t.grade || 'N/A';
              
              // Determine leave type badge
              const leaveTypeBadge = t.leave_type === 'Week Off' 
                ? '<span class="leave-badge week-off">Week Off</span>'
                : t.leave_type === 'Emergency Leave'
                ? '<span class="leave-badge emergency-leave">Emergency Leave</span>'
                : t.leave_type 
                ? `<span class="leave-badge">${t.leave_type}</span>`
                : '';
              
              // Show date range if different from single date
              const dateRange = (t.from_date && t.to_date && t.from_date !== t.to_date)
                ? ` (${t.from_date} to ${t.to_date})`
                : '';
              
              return `
              <li class="therapist-item">
                <div class="therapist-avatar ${genderClass}">
                  ${isMale ? 'M' : 'F'}
                </div>
                <div class="therapist-info">
                  <div class="therapist-name">${t.name}</div>
                  <div class="therapist-details">
                    ${genderDisplay} Therapist • ${gradeDisplay}
                    ${leaveTypeBadge}
                    ${dateRange}
                    ${t.reason ? ` • ${t.reason}` : ''}
                    ${t.leave_day_name ? ` • ${t.leave_day_name}` : ''}
                  </div>
                </div>
              </li>
            `;
            }).join('')}
          </ul>
        `;
        resultDiv.className = 'result';
      } else {
        resultDiv.innerHTML = `
          <h3><i class="fas fa-list"></i> Therapists on Leave</h3>
          <div class="no-result">
            <i class="far fa-smile"></i>
            <p>No therapists on leave for selected date.</p>
          </div>
        `;
        resultDiv.className = 'result success';
      }
    }

    function showError(resultDiv, message) {
      resultDiv.innerHTML = `
        <h3><i class="fas fa-exclamation-triangle"></i> Error</h3>
        <div class="no-result">
          <i class="fas fa-exclamation-circle"></i>
          <p>${message}</p>
        </div>
      `;
      resultDiv.className = 'result error';
    }