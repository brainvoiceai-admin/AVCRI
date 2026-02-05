// Global variables
let timeSlots = [];

// Initialize the dashboard
document.addEventListener('DOMContentLoaded', function () {
  // Set today's date as default
  const today = new Date().toISOString().split('T')[0];
  document.getElementById('date').value = today;
  document.getElementById('occupiedDate').value = today;

  // Load time slots
  loadTimeSlots();
});

function loadTimeSlots() {
  fetch('/sheduling/room-availability/api/time-slots/')
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
  const occupiedTimeSelect = document.getElementById('occupiedTime');

  const optionHTML = '<option value="">-- Select Time Slot --</option>' +
    timeSlots.map(slot => `<option value="${slot.start_time}">${slot.display_name}</option>`).join('');

  timeSelect.innerHTML = optionHTML;
  occupiedTimeSelect.innerHTML = optionHTML;
}

function populateDefaultTimeSlots() {
  const defaultHTML = `
    <option value="">-- Select Time Slot --</option>
    <option value="09:00">09:00 AM - 10:00 AM</option>
    <option value="10:00">10:00 AM - 11:00 AM</option>
    <option value="14:00">02:00 PM - 03:00 PM</option>
    <option value="15:00">03:00 PM - 04:00 PM</option>
  `;

  document.getElementById('time').innerHTML = defaultHTML;
  document.getElementById('occupiedTime').innerHTML = defaultHTML;
}

function findAvailability() {
  const date = document.getElementById('date').value;
  const time = document.getElementById('time').value;
  const floor = document.getElementById('floor').value;
  const resultDiv = document.getElementById('availableRooms');
  const btn = document.getElementById('availabilityBtn');

  if (!date || !time) {
    alert('Please fill all filters');
    return;
  }

  // Show loading state
  btn.disabled = true;
  btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Checking...';

  resultDiv.innerHTML = `
    <h3><i class="fas fa-list"></i> Available Rooms</h3>
    <div class="loading">
      <i class="fas fa-spinner fa-spin"></i>
      <p>Searching for available rooms...</p>
    </div>
  `;

  // Build API URL
  const apiUrl = `/sheduling/room-availability/api/available-rooms/?date=${date}&time=${time}&floor=${floor}`;

  fetch(apiUrl)
    .then(response => response.json())
    .then(data => {
      if (data.success) {
        displayAvailableRooms(data.rooms, data.total_count);
      } else {
        showError(resultDiv, data.error || 'Failed to fetch available rooms');
      }
    })
    .catch(error => {
      console.error('Error fetching available rooms:', error);
      showError(resultDiv, 'Error fetching available rooms');
    })
    .finally(() => {
      // Reset button state
      btn.disabled = false;
      btn.innerHTML = '<i class="fas fa-search"></i> Check Availability';
    });
}

function displayAvailableRooms(rooms, totalCount) {
  const resultDiv = document.getElementById('availableRooms');

  if (rooms.length > 0) {
    resultDiv.innerHTML = `
      <h3><i class="fas fa-list"></i> Available Rooms (${totalCount})</h3>
      <ul class="room-list">
        ${rooms.map(room => {
      const roomInitial = room.room_no.charAt(0).toUpperCase();
      return `
          <li class="room-item">
            <div class="room-icon">
              <i class="fas fa-door-open"></i>
            </div>
            <div class="room-info">
              <div class="room-name">${room.room_no}</div>
              <div class="room-details">
                Floor: ${room.floor}
                ${room.description ? ` • ${room.description}` : ''}
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
      <h3><i class="fas fa-list"></i> Available Rooms</h3>
      <div class="no-result">
        <i class="far fa-frown"></i>
        <p>No rooms available for selected filters.</p>
      </div>
    `;
    resultDiv.className = 'result';
  }
}

function checkOccupied() {
  const date = document.getElementById('occupiedDate').value;
  const time = document.getElementById('occupiedTime').value;
  const floor = document.getElementById('occupiedFloor').value;
  const resultDiv = document.getElementById('occupiedRooms');
  const btn = document.getElementById('occupiedBtn');

  if (!date || !time) {
    alert('Please select both filters');
    return;
  }

  // Show loading state
  btn.disabled = true;
  btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Checking...';

  resultDiv.innerHTML = `
    <h3><i class="fas fa-list"></i> Occupied Rooms</h3>
    <div class="loading">
      <i class="fas fa-spinner fa-spin"></i>
      <p>Checking occupied rooms...</p>
    </div>
  `;

  // Build API URL
  const apiUrl = `/sheduling/room-availability/api/occupied-rooms/?date=${date}&time=${time}&floor=${floor}`;

  fetch(apiUrl)
    .then(response => response.json())
    .then(data => {
      if (data.success) {
        displayOccupiedRooms(data.occupied_rooms, data.total_count);
      } else {
        showError(resultDiv, data.error || 'Failed to fetch occupied rooms');
      }
    })
    .catch(error => {
      console.error('Error fetching occupied rooms:', error);
      showError(resultDiv, 'Error fetching occupied rooms');
    })
    .finally(() => {
      // Reset button state
      btn.disabled = false;
      btn.innerHTML = '<i class="fas fa-search"></i> Check Occupied';
    });
}

function displayOccupiedRooms(rooms, totalCount) {
  const resultDiv = document.getElementById('occupiedRooms');

  if (rooms.length > 0) {
    resultDiv.innerHTML = `
      <h3><i class="fas fa-list"></i> Occupied Rooms (${totalCount})</h3>
      <ul class="room-list">
        ${rooms.map(room => {
      return `
          <li class="room-item">
            <div class="room-icon occupied">
              <i class="fas fa-door-closed"></i>
            </div>
            <div class="room-info">
              <div class="room-name">
                ${room.room_no}
                <span class="occupied-badge">OCCUPIED</span>
              </div>
              <div class="room-details">
                Floor: ${room.floor}
              </div>
              <div class="patient-info">
                <span class="therapy-name">${room.therapy_name}</span> • 
                Patient: ${room.patient_name}
                ${room.patient_reg_no && room.patient_reg_no !== 'N/A' ? ` (${room.patient_reg_no})` : ''}
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
      <h3><i class="fas fa-list"></i> Occupied Rooms</h3>
      <div class="no-result">
        <i class="far fa-smile"></i>
        <p>No rooms occupied for selected filters.</p>
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
