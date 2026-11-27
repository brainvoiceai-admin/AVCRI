// Global variables
let timeSlots = [];
let currentAvailCount = null;
let currentOccupiedCount = null;

// Helper to get local date string YYYY-MM-DD
function getLocalDateString() {
  const now = new Date();
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, '0');
  const day = String(now.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

// Initialize the dashboard
document.addEventListener('DOMContentLoaded', function () {
  // Set today's local date as default
  const today = getLocalDateString();
  const dateInput = document.getElementById('date');
  const occupiedDateInput = document.getElementById('occupiedDate');

  if (dateInput) dateInput.value = today;
  if (occupiedDateInput) occupiedDateInput.value = today;

  // Setup synchronization between form 1 and form 2 filters
  setupFilterSync();

  // Load time slots and auto-run dashboard
  loadTimeSlots();
});

function setupFilterSync() {
  const date1 = document.getElementById('date');
  const date2 = document.getElementById('occupiedDate');
  const time1 = document.getElementById('time');
  const time2 = document.getElementById('occupiedTime');
  const floor1 = document.getElementById('floor');
  const floor2 = document.getElementById('occupiedFloor');

  if (date1 && date2) {
    date1.addEventListener('change', () => { date2.value = date1.value; checkAll(); });
    date2.addEventListener('change', () => { date1.value = date2.value; checkAll(); });
  }
  if (time1 && time2) {
    time1.addEventListener('change', () => { time2.value = time1.value; checkAll(); });
    time2.addEventListener('change', () => { time1.value = time2.value; checkAll(); });
  }
  if (floor1 && floor2) {
    floor1.addEventListener('change', () => { floor2.value = floor1.value; checkAll(); });
    floor2.addEventListener('change', () => { floor1.value = floor2.value; checkAll(); });
  }
}

function updateStatCounters(availCount, occCount) {
  if (availCount !== null && availCount !== undefined) {
    currentAvailCount = availCount;
    const el = document.getElementById('statAvailable');
    if (el) el.textContent = availCount;
  }
  if (occCount !== null && occCount !== undefined) {
    currentOccupiedCount = occCount;
    const el = document.getElementById('statOccupied');
    if (el) el.textContent = occCount;
  }
  if (currentAvailCount !== null && currentOccupiedCount !== null) {
    const totalEl = document.getElementById('statTotalRooms');
    if (totalEl) totalEl.textContent = currentAvailCount + currentOccupiedCount;
  }
}

function loadTimeSlots() {
  fetch('/sheduling/room-availability/api/time-slots/')
    .then(response => response.json())
    .then(data => {
      if (data.success) {
        timeSlots = data.time_slots || [];
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

  let optionHTML = '<option value="all">-- All Time Slots (Full Day) --</option>';
  optionHTML += timeSlots.map(slot => `<option value="${slot.start_time}">${slot.display_name}</option>`).join('');

  if (timeSelect) timeSelect.innerHTML = optionHTML;
  if (occupiedTimeSelect) occupiedTimeSelect.innerHTML = optionHTML;

  // Set default selection to Slot 1 (06:30) if present, or first slot
  const slot1 = timeSlots.find(s => s.slot_number === 1 || s.start_time === '06:30');
  const defaultVal = slot1 ? slot1.start_time : (timeSlots.length > 0 ? timeSlots[0].start_time : 'all');

  if (timeSelect) timeSelect.value = defaultVal;
  if (occupiedTimeSelect) occupiedTimeSelect.value = defaultVal;

  // Automatically check availability and occupied rooms
  checkAll();
}

function populateDefaultTimeSlots() {
  const defaultHTML = `
    <option value="all">-- All Time Slots (Full Day) --</option>
    <option value="06:30">Slot 1 (6:30 AM)</option>
    <option value="08:30">Slot 2 (8:30 AM)</option>
    <option value="10:00">Slot 3 (10:00 AM)</option>
    <option value="11:30">Slot 4 (11:30 AM)</option>
    <option value="14:30">Slot 5 (2:30 PM)</option>
    <option value="16:00">Slot 6 (4:00 PM)</option>
    <option value="17:30">Slot 7 (5:30 PM)</option>
  `;

  const timeSelect = document.getElementById('time');
  const occupiedTimeSelect = document.getElementById('occupiedTime');

  if (timeSelect) timeSelect.innerHTML = defaultHTML;
  if (occupiedTimeSelect) occupiedTimeSelect.innerHTML = defaultHTML;

  if (timeSelect) timeSelect.value = '06:30';
  if (occupiedTimeSelect) occupiedTimeSelect.value = '06:30';

  checkAll();
}

function checkAll() {
  findAvailability();
  checkOccupied();
}

function findAvailability() {
  const dateEl = document.getElementById('date');
  const timeEl = document.getElementById('time');
  const floorEl = document.getElementById('floor');
  const resultDiv = document.getElementById('availableRooms');
  const btn = document.getElementById('availabilityBtn');

  if (!dateEl) return;
  const date = dateEl.value;
  const time = timeEl ? timeEl.value : 'all';
  const floor = floorEl ? floorEl.value : 'all';

  if (!date) {
    alert('Please select a date');
    return;
  }

  // Show loading state
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Checking...';
  }

  if (resultDiv) {
    resultDiv.innerHTML = `
      <h3><i class="fas fa-door-open"></i> Available Rooms</h3>
      <div class="loading">
        <i class="fas fa-spinner fa-spin"></i>
        <p>Searching for available rooms...</p>
      </div>
    `;
  }

  // Build API URL
  const apiUrl = `/sheduling/room-availability/api/available-rooms/?date=${encodeURIComponent(date)}&time=${encodeURIComponent(time)}&floor=${encodeURIComponent(floor)}`;

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
      showError(resultDiv, 'Error connecting to room availability service');
    })
    .finally(() => {
      if (btn) {
        btn.disabled = false;
        btn.innerHTML = '<i class="fas fa-search"></i> Check Availability';
      }
    });
}

function displayAvailableRooms(rooms, totalCount) {
  const resultDiv = document.getElementById('availableRooms');
  updateStatCounters(totalCount, null);

  if (!resultDiv) return;

  if (rooms && rooms.length > 0) {
    resultDiv.innerHTML = `
      <h3><i class="fas fa-door-open"></i> Available Rooms (${totalCount})</h3>
      <ul class="room-list">
        ${rooms.map(room => {
          let amenityBadges = '';
          if (room.is_steam_room) {
            amenityBadges += '<span class="amenity-badge steam" title="Steam Therapy Room"><i class="fas fa-smog"></i> Steam</span>';
          }
          if (room.is_vamanam_room) {
            amenityBadges += '<span class="amenity-badge vamanam" title="Vamanam Treatment Room"><i class="fas fa-hand-holding-medical"></i> Vamanam</span>';
          }
          if (room.is_wheelchair_accessible) {
            amenityBadges += '<span class="amenity-badge wheelchair" title="Wheelchair Accessible"><i class="fas fa-wheelchair"></i> Wheelchair</span>';
          }
          return `
          <li class="room-item">
            <div class="room-icon available">
              <i class="fas fa-door-open"></i>
            </div>
            <div class="room-info">
              <div class="room-name">
                ${room.room_no}
                <span class="available-badge">AVAILABLE</span>
                ${amenityBadges}
              </div>
              <div class="room-details">
                Floor: ${room.floor} • TR Code: ${room.tr_code}
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
      <h3><i class="fas fa-door-open"></i> Available Rooms (0)</h3>
      <div class="no-result">
        <i class="far fa-frown"></i>
        <p>No rooms available for selected filters.</p>
      </div>
    `;
    resultDiv.className = 'result';
  }
}

function checkOccupied() {
  const dateEl = document.getElementById('occupiedDate');
  const timeEl = document.getElementById('occupiedTime');
  const floorEl = document.getElementById('occupiedFloor');
  const resultDiv = document.getElementById('occupiedRooms');
  const btn = document.getElementById('occupiedBtn');

  if (!dateEl) return;
  const date = dateEl.value;
  const time = timeEl ? timeEl.value : 'all';
  const floor = floorEl ? floorEl.value : 'all';

  if (!date) {
    alert('Please select a date');
    return;
  }

  // Show loading state
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Checking...';
  }

  if (resultDiv) {
    resultDiv.innerHTML = `
      <h3><i class="fas fa-door-closed"></i> Occupied Rooms</h3>
      <div class="loading">
        <i class="fas fa-spinner fa-spin"></i>
        <p>Checking occupied rooms...</p>
      </div>
    `;
  }

  // Build API URL
  const apiUrl = `/sheduling/room-availability/api/occupied-rooms/?date=${encodeURIComponent(date)}&time=${encodeURIComponent(time)}&floor=${encodeURIComponent(floor)}`;

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
      showError(resultDiv, 'Error connecting to room occupancy service');
    })
    .finally(() => {
      if (btn) {
        btn.disabled = false;
        btn.innerHTML = '<i class="fas fa-search"></i> Check Occupied';
      }
    });
}

function displayOccupiedRooms(rooms, totalCount) {
  const resultDiv = document.getElementById('occupiedRooms');
  updateStatCounters(null, totalCount);

  if (!resultDiv) return;

  if (rooms && rooms.length > 0) {
    resultDiv.innerHTML = `
      <h3><i class="fas fa-door-closed"></i> Occupied Rooms (${totalCount})</h3>
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
                ${room.time_slot ? `<span class="slot-badge"><i class="far fa-clock"></i> ${room.time_slot}</span>` : ''}
              </div>
              <div class="room-details">
                Floor: ${room.floor} • TR Code: ${room.tr_code}
              </div>
              <div class="patient-info">
                <div><i class="fas fa-spa"></i> <strong>Therapy:</strong> <span class="therapy-name">${room.therapy_name}</span></div>
                <div><i class="fas fa-user"></i> <strong>Patient:</strong> ${room.patient_name}${room.patient_reg_no && room.patient_reg_no !== 'N/A' ? ` (${room.patient_reg_no})` : ''}</div>
                ${room.therapists && room.therapists !== 'N/A' ? `<div class="therapist-info"><i class="fas fa-user-md"></i> <strong>Therapists:</strong> ${room.therapists}</div>` : ''}
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
      <h3><i class="fas fa-door-closed"></i> Occupied Rooms (0)</h3>
      <div class="no-result">
        <i class="far fa-smile"></i>
        <p>No rooms occupied for selected filters.</p>
      </div>
    `;
    resultDiv.className = 'result success';
  }
}

function showError(resultDiv, message) {
  if (!resultDiv) return;
  resultDiv.innerHTML = `
    <h3><i class="fas fa-exclamation-triangle"></i> Error</h3>
    <div class="no-result">
      <i class="fas fa-exclamation-circle"></i>
      <p>${message}</p>
    </div>
  `;
  resultDiv.className = 'result error';
}
