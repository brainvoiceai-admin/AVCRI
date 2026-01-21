document.addEventListener('DOMContentLoaded', function () {
    // Set today's date as default
    const today = new Date().toISOString().split('T')[0];
    document.getElementById('date').value = today;
    document.getElementById('bookedDate').value = today;

    // Load initial data
    loadTimeSlots();
    loadFloors();
});

async function loadTimeSlots() {
    try {
        const response = await fetch('/sheduling/therapist-availability/api/time-slots/');
        const data = await response.json();

        if (data.success) {
            const timeSelect = document.getElementById('time');
            data.time_slots.forEach(slot => {
                const option = document.createElement('option');
                option.value = slot.start_time;
                option.textContent = slot.display_name;
                timeSelect.appendChild(option);
            });
        }
    } catch (error) {
        console.error('Error loading time slots:', error);
    }
}

async function loadFloors() {
    try {
        const response = await fetch('/sheduling/room-availability/api/floors/');
        const data = await response.json();

        if (data.success) {
            const floorSelects = [document.getElementById('floor'), document.getElementById('bookedFloor')];
            data.floors.forEach(floor => {
                floorSelects.forEach(select => {
                    const option = document.createElement('option');
                    option.value = floor;
                    option.textContent = floor;
                    select.appendChild(option);
                });
            });
        }
    } catch (error) {
        console.error('Error loading floors:', error);
    }
}

async function findAvailability() {
    const date = document.getElementById('date').value;
    const time = document.getElementById('time').value;
    const floor = document.getElementById('floor').value;
    const btn = document.getElementById('availabilityBtn');
    const resultDiv = document.getElementById('availableRooms');
    const countBadge = document.getElementById('availableCount');

    if (!date) {
        alert('Please select a date');
        return;
    }

    // Show loading state
    btn.disabled = true;
    const originalBtnHtml = btn.innerHTML;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Checking...';

    resultDiv.innerHTML = `
        <div class="loading">
            <i class="fas fa-spinner fa-spin"></i>
            <p>Searching for available rooms...</p>
        </div>
    `;

    try {
        let url = `/sheduling/room-availability/api/available-rooms/?date=${date}&floor=${floor}`;
        if (time) url += `&time=${time}`;

        const response = await fetch(url);
        const data = await response.json();

        if (data.success) {
            displayAvailableRooms(data.rooms);
            countBadge.textContent = `${data.total_count} found`;
        } else {
            showError(resultDiv, data.error || 'Failed to fetch results');
        }
    } catch (error) {
        showError(resultDiv, 'Error communicating with server');
    } finally {
        btn.disabled = false;
        btn.innerHTML = originalBtnHtml;
    }
}

function displayAvailableRooms(rooms) {
    const resultDiv = document.getElementById('availableRooms');

    if (rooms.length === 0) {
        resultDiv.innerHTML = `
            <div class="placeholder-text">
                <i class="far fa-frown"></i>
                <p>No available rooms found for the selected criteria.</p>
            </div>
        `;
        return;
    }

    let html = '<ul class="room-list">';
    rooms.forEach(room => {
        html += `
            <li class="room-item">
                <div class="room-icon">
                    <i class="fas fa-door-open"></i>
                </div>
                <div class="room-info">
                    <div class="room-name">Room ${room.room_no}</div>
                    <div class="room-details">
                        <div class="detail-item"><i class="fas fa-layer-group"></i> ${room.floor}</div>
                        ${room.tr_code ? `<div class="detail-item"><i class="fas fa-tag"></i> ${room.tr_code}</div>` : ''}
                        <div class="status-indicator status-available">Available</div>
                    </div>
                </div>
            </li>
        `;
    });
    html += '</ul>';
    resultDiv.innerHTML = html;
}

async function checkBookings() {
    const date = document.getElementById('bookedDate').value;
    const floor = document.getElementById('bookedFloor').value;
    const btn = document.getElementById('bookedBtn');
    const resultDiv = document.getElementById('bookedRooms');
    const countBadge = document.getElementById('bookedCount');

    if (!date) {
        alert('Please select a date');
        return;
    }

    btn.disabled = true;
    const originalBtnHtml = btn.innerHTML;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Loading...';

    try {
        const response = await fetch(`/sheduling/room-availability/api/booked-rooms/?date=${date}&floor=${floor}`);
        const data = await response.json();

        if (data.success) {
            displayBookedRooms(data.bookings);
            countBadge.textContent = `${data.total_count} sessions`;
        } else {
            showError(resultDiv, data.error || 'Failed to fetch bookings');
        }
    } catch (error) {
        showError(resultDiv, 'Error communicating with server');
    } finally {
        btn.disabled = false;
        btn.innerHTML = originalBtnHtml;
    }
}

function displayBookedRooms(bookings) {
    const resultDiv = document.getElementById('bookedRooms');

    if (bookings.length === 0) {
        resultDiv.innerHTML = `
            <div class="placeholder-text">
                <i class="far fa-calendar-check"></i>
                <p>No bookings found for this date.</p>
            </div>
        `;
        return;
    }

    let html = '<ul class="booking-list">';
    bookings.forEach(booking => {
        html += `
            <li class="booking-item">
                <div class="room-icon">
                    <i class="fas fa-door-closed"></i>
                </div>
                <div class="booking-info">
                    <div class="booking-title">Room ${booking.room_no}</div>
                    <div class="booking-details">
                        <div class="detail-item"><i class="far fa-clock"></i> ${booking.time_slot}</div>
                        <div class="detail-item"><i class="fas fa-notes-medical"></i> ${booking.therapy_name}</div>
                    </div>
                    <div class="patient-info-row">
                        <i class="fas fa-user-tag"></i> <span class="patient-label">Patient:</span> <span class="patient-name">${booking.patient_name}</span>
                    </div>
                </div>
            </li>
        `;
    });
    html += '</ul>';
    resultDiv.innerHTML = html;
}

function showError(resultDiv, message) {
    resultDiv.innerHTML = `
        <div class="placeholder-text" style="color: var(--danger);">
            <i class="fas fa-exclamation-triangle"></i>
            <p>${message}</p>
        </div>
    `;
}
