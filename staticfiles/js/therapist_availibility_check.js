const therapists = [
      { name: 'Dr. Asha Rao', gender: 'female', available: { '2025-10-25': ['09:00', '14:00'] }, leaves: ['2025-10-30'] },
      { name: 'Mr. Raj Singh', gender: 'male', available: { '2025-10-25': ['09:00', '13:00'] }, leaves: ['2025-10-26'] },
      { name: 'Ms. Nina Kapoor', gender: 'female', available: { '2025-10-26': ['09:00', '10:00'] }, leaves: [] },
      { name: 'Mr. Sameer Patel', gender: 'male', available: { '2025-10-25': ['15:00'] }, leaves: ['2025-10-25'] }
    ];

    function findAvailability() {
      const date = document.getElementById('date').value;
      const time = document.getElementById('time').value;
      const gender = document.getElementById('gender').value;
      const resultDiv = document.getElementById('availableTherapists');

      if (!date || !time || !gender) {
        alert('Please fill all filters');
        return;
      }

      const available = therapists.filter(t => 
        (gender === 'all' || t.gender === gender) && 
        t.available[date]?.includes(time) &&
        !t.leaves.includes(date)
      );

      if (available.length) {
        resultDiv.innerHTML = `
          <h3><i class="fas fa-list"></i> Available Therapists</h3>
          <ul class="therapist-list">
            ${available.map(t => `
              <li class="therapist-item">
                <div class="therapist-avatar ${t.gender}">
                  ${t.gender === 'male' ? 'M' : 'F'}
                </div>
                <div>
                  <strong>${t.name}</strong><br>
                  <small>${t.gender === 'male' ? 'Male Therapist' : 'Female Therapist'}</small>
                </div>
              </li>
            `).join('')}
          </ul>
        `;
      } else {
        resultDiv.innerHTML = `
          <div class="no-result">
            <i class="far fa-frown"></i>
            <p>No therapists available for selected filters.</p>
          </div>
        `;
      }
    }

    function checkLeaves() {
      const date = document.getElementById('leaveDate').value;
      const gender = document.getElementById('leaveGender').value;
      const resultDiv = document.getElementById('therapistLeaves');

      if (!date || !gender) {
        alert('Please select both filters');
        return;
      }

      const leaves = therapists.filter(t => 
        (gender === 'all' || t.gender === gender) && 
        t.leaves.includes(date)
      );

      if (leaves.length) {
        resultDiv.innerHTML = `
          <h3><i class="fas fa-list"></i> Therapists on Leave</h3>
          <ul class="therapist-list">
            ${leaves.map(t => `
              <li class="therapist-item">
                <div class="therapist-avatar ${t.gender}">
                  ${t.gender === 'male' ? 'M' : 'F'}
                </div>
                <div>
                  <strong>${t.name}</strong><br>
                  <small>${t.gender === 'male' ? 'Male Therapist' : 'Female Therapist'}</small>
                </div>
              </li>
            `).join('')}
          </ul>
        `;
      } else {
        resultDiv.innerHTML = `
          <div class="no-result">
            <i class="far fa-smile"></i>
            <p>No therapists on leave for selected date.</p>
          </div>
        `;
      }
    }

    // Set default date to today
    const today = new Date().toISOString().split('T')[0];
    document.getElementById('date').value = today;
    document.getElementById('leaveDate').value = today;