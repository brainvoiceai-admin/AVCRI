// Global variables
    let patientData = null;
    let sessionsData = [];
    let prescriptionsData = [];
    let calYear, calMonth;

    // Initialize the dashboard
    document.addEventListener('DOMContentLoaded', function() {
      // Set today's date as default for prescription date
      document.getElementById('prescriptionDate').value = new Date().toISOString().slice(0, 10);
      
      // Load patient data
      loadPatientData();
      
      // Set up event listeners
      setupEventListeners();
    });

    function setupEventListeners() {
      // Prescription date change
      document.getElementById('prescriptionDate').addEventListener('change', function() {
        loadPrescriptionsForDate(this.value);
      });

      // Calendar navigation
      document.getElementById('calPrev').addEventListener('click', function() {
        calMonth--;
        if (calMonth < 0) {
          calMonth = 11;
          calYear--;
        }
        renderCalendar(calYear, calMonth);
      });

      document.getElementById('calNext').addEventListener('click', function() {
        calMonth++;
        if (calMonth > 11) {
          calMonth = 0;
          calYear++;
        }
        renderCalendar(calYear, calMonth);
      });

      // Print button
      document.getElementById('printBtn').addEventListener('click', function() {
        window.print();
      });
    }

    function loadPatientData() {
      // Fetch patient data from API
      fetch('/sheduling/patient/api/patient-data/')
        .then(response => response.json())
        .then(data => {
          if (data.success) {
            patientData = data.patient;
            sessionsData = data.sessions || [];
            prescriptionsData = data.prescriptions || [];
            
            // Update patient info
            document.getElementById('patientName').textContent = patientData.name;
            document.getElementById('patientId').textContent = patientData.id;
            
            // Render all components
            renderTreatmentPlan();
            renderUpcoming();
            renderSessionLog();
            
            // Initialize calendar
            if (sessionsData.length > 0) {
              const firstSession = sessionsData[0];
              const [year, month] = firstSession.date.split('-');
              calYear = parseInt(year);
              calMonth = parseInt(month) - 1;
            } else {
              const now = new Date();
              calYear = now.getFullYear();
              calMonth = now.getMonth();
            }
            renderCalendar(calYear, calMonth);
            
            // Load prescriptions for today
            loadPrescriptionsForDate(new Date().toISOString().slice(0, 10));
          } else {
            showError('Failed to load patient data: ' + (data.error || 'Unknown error'));
          }
        })
        .catch(error => {
          console.error('Error loading patient data:', error);
          showError('Error loading patient data');
        });
    }

    function loadPrescriptionsForDate(date) {
      const prescriptionContent = document.getElementById('prescriptionContent');
      prescriptionContent.innerHTML = '<div class="text-muted text-center py-4">Loading prescriptions...</div>';
      
      fetch(`/sheduling/patient/api/prescriptions/?date=${date}`)
        .then(response => response.json())
        .then(data => {
          if (data.success) {
            renderPrescriptions(data.prescriptions || []);
          } else {
            prescriptionContent.innerHTML = '<div class="text-muted text-center py-4">No prescriptions found for this date.</div>';
          }
        })
        .catch(error => {
          console.error('Error loading prescriptions:', error);
          prescriptionContent.innerHTML = '<div class="text-danger text-center py-4">Error loading prescriptions.</div>';
        });
    }

    function renderTreatmentPlan() {
      if (!patientData || sessionsData.length === 0) {
        document.getElementById('therapyType').textContent = 'No therapy assigned';
        document.getElementById('nextSessionLabel').textContent = 'No upcoming session';
        return;
      }

      // Get the most common therapy type
      const therapyCounts = {};
      sessionsData.forEach(session => {
        therapyCounts[session.therapy] = (therapyCounts[session.therapy] || 0) + 1;
      });
      const mostCommonTherapy = Object.keys(therapyCounts).reduce((a, b) => 
        therapyCounts[a] > therapyCounts[b] ? a : b
      );
      
      document.getElementById('therapyType').textContent = mostCommonTherapy;
      
      // Get all unique therapists
      const therapists = [...new Set(sessionsData.flatMap(s => s.therapists || []))];
      renderTherapists(therapists);
      
      // Get next session
      const upcomingSessions = sessionsData.filter(s => s.status.toLowerCase() === 'scheduled')
        .sort((a, b) => a.date.localeCompare(b.date) || a.slot - b.slot);
      
      if (upcomingSessions.length > 0) {
        const next = upcomingSessions[0];
        document.getElementById('nextSessionLabel').textContent = 
          `${formatDate(next.date)} • ${slotToDisplay(next.slot)} • ${next.room_id}`;
      } else {
        document.getElementById('nextSessionLabel').textContent = 'No upcoming session';
      }
    }

    function renderTherapists(therapists) {
      const therapistListEl = document.getElementById('therapistList');
      therapistListEl.innerHTML = '';
      
      therapists.forEach(therapist => {
        const div = document.createElement('div');
        div.className = 'chip';
        div.innerHTML = `<span class="avatar">${initials(therapist)}</span>${therapist}`;
        therapistListEl.appendChild(div);
      });
    }

    function renderUpcoming() {
      const upcomingList = document.getElementById('upcomingList');
      const upcoming = sessionsData.filter(s => s.status.toLowerCase() === 'scheduled')
        .sort((a, b) => a.date.localeCompare(b.date) || a.slot - b.slot);
      
      upcomingList.innerHTML = '';
      
      if (upcoming.length === 0) {
        upcomingList.innerHTML = '<div class="text-muted p-3 text-center">No upcoming appointments.</div>';
        return;
      }
      
      upcoming.slice(0, 6).forEach(session => {
        const div = document.createElement('div');
        div.className = 'list-group-item border-0';
        div.innerHTML = `
          <div class="d-flex w-100 justify-content-between align-items-center">
            <div class="flex-grow-1">
              <h6 class="mb-1 fw-semibold">${session.therapy}</h6>
              <div class="small text-muted">${formatDate(session.date)} • ${slotToDisplay(session.slot)}</div>
              <div class="small text-muted mt-1"><strong>Room-ID:</strong> ${session.room_id}</div>
            </div>
            <div class="ms-3">
              <button class="btn btn-sm btn-outline-primary" onclick="openDateModal('${session.date}')">View</button>
            </div>
          </div>
        `;
        upcomingList.appendChild(div);
      });
    }

    function renderPrescriptions(prescriptions) {
      const prescriptionContent = document.getElementById('prescriptionContent');
      
      if (prescriptions.length === 0) {
        prescriptionContent.innerHTML = '<div class="text-muted text-center py-4">No prescriptions for this date.</div>';
        return;
      }
      
      let html = '<div class="row g-3">';
      prescriptions.forEach(prescription => {
        html += `
          <div class="col-md-6">
            <div class="card">
              <div class="card-body">
                <h6 class="card-title">${prescription.item_name}</h6>
                <p class="card-text">
                  <strong>Dose:</strong> ${prescription.dose}<br>
                  <strong>Quantity:</strong> ${prescription.quantity}<br>
                  <strong>Time:</strong> ${prescription.time}<br>
                  <strong>Notes:</strong> ${prescription.notes || 'None'}
                </p>
              </div>
            </div>
          </div>
        `;
      });
      html += '</div>';
      
      prescriptionContent.innerHTML = html;
    }

    function renderSessionLog() {
      const sessionLogBody = document.getElementById('sessionLogBody');
      sessionLogBody.innerHTML = '';
      
      // Sort by date desc, slot asc
      const sortedSessions = sessionsData.slice().sort((a, b) => 
        b.date.localeCompare(a.date) || a.slot - b.slot
      );
      
      sortedSessions.forEach(session => {
        const tr = document.createElement('tr');
        const therapists = (session.therapists || []).slice(0, 3).join(', ') + 
          ((session.therapists || []).length > 3 ? (' +' + (session.therapists.length - 3)) : '');
        
        tr.innerHTML = `
          <td>${formatDate(session.date)}</td>
          <td>${slotToDisplay(session.slot)}</td>
          <td>${session.therapy}</td>
          <td>${therapists}</td>
          <td>${session.room_id}</td>
          <td><span class="badge rounded-pill text-bg-${badgeClass(session.status)} status-badge">${session.status}</span></td>
        `;
        sessionLogBody.appendChild(tr);
      });
    }

    function renderCalendar(year, month) {
      const calendarGrid = document.getElementById('calendarGrid');
      const monthLabel = document.getElementById('monthLabel');
      
      calendarGrid.innerHTML = '';
      monthLabel.textContent = new Date(year, month, 1).toLocaleString(undefined, { 
        month: 'long', 
        year: 'numeric' 
      });

      // Weekday names
      const days = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
      for (let day of days) {
        const el = document.createElement('div');
        el.className = 'calendar-day-name';
        el.textContent = day;
        calendarGrid.appendChild(el);
      }

      const firstDay = new Date(year, month, 1).getDay();
      const daysInMonth = new Date(year, month + 1, 0).getDate();
      const prevMonthDays = new Date(year, month, 0).getDate();
      const totalCells = 42;
      let dayCounter = 1;
      let nextCounter = 1;
      
      for (let i = 0; i < totalCells; i++) {
        const cell = document.createElement('div');
        cell.className = 'calendar-day';
        
        if (i < firstDay) {
          // Previous month
          const d = prevMonthDays - (firstDay - 1 - i);
          cell.classList.add('other-month');
          cell.textContent = d;
        } else if (dayCounter <= daysInMonth) {
          const iso = `${year}-${String(month + 1).padStart(2, '0')}-${String(dayCounter).padStart(2, '0')}`;
          cell.dataset.date = iso;
          cell.textContent = dayCounter;
          
          // Mark today
          if (iso === new Date().toISOString().slice(0, 10)) {
            cell.classList.add('today');
          }
          
          // Sessions on date?
          const sessions = sessionsData.filter(s => s.date === iso);
          if (sessions.length) {
            cell.classList.add('event');
            const indicator = document.createElement('div');
            indicator.className = 'event-indicator';
            cell.appendChild(indicator);
          }
          
          // Clicking opens modal
          cell.addEventListener('click', () => openDateModal(iso));
          dayCounter++;
        } else {
          // Next month
          cell.classList.add('other-month');
          cell.textContent = nextCounter++;
        }
        calendarGrid.appendChild(cell);
      }
    }

    function openDateModal(iso) {
      const modal = new bootstrap.Modal(document.getElementById('dateModal'));
      const modalDate = document.getElementById('modalDate');
      const modalBody = document.getElementById('modalBody');
      
      modalDate.textContent = formatDate(iso);
      modalBody.innerHTML = '';
      
      const sessions = sessionsData.filter(s => s.date === iso);
      if (sessions.length === 0) {
        modalBody.innerHTML = '<div class="text-muted text-center py-4">No sessions for this date.</div>';
      } else {
        sessions.forEach(session => {
          const card = document.createElement('div');
          card.className = 'session-card mb-3 p-3 border rounded';
          const therapistsHtml = (session.therapists || []).slice(0, 5).map(t => 
            `<span class="chip"><span class="avatar">${initials(t)}</span>${t}</span>`
          ).join('');
          const more = (session.therapists || []).length > 5 ? 
            `<div class="mt-2 text-muted">+${session.therapists.length - 5} more therapist(s)</div>` : '';
          
          card.innerHTML = `
            <div class="d-flex justify-content-between align-items-start mb-2">
              <div>
                <div class="fw-bold">${session.therapy}</div>
                <div class="text-muted">${slotToDisplay(session.slot)} • Room-ID: ${session.room_id}</div>
              </div>
              <div><span class="badge rounded-pill text-bg-${badgeClass(session.status)} status-badge">${session.status}</span></div>
            </div>
            <div class="mb-2">
              <div class="fw-semibold mb-1">Assigned Therapists</div>
              ${therapistsHtml}${more}
            </div>
            <div class="text-muted"><span class="fw-medium">Remarks:</span> ${session.remarks || '—'}</div>
          `;
          modalBody.appendChild(card);
        });
      }
      modal.show();
    }

    // Helper functions
    function slotToDisplay(slot) {
      const hour = slot % 24;
      const suffix = hour >= 12 ? 'PM' : 'AM';
      let h = hour % 12;
      if (h === 0) h = 12;
      return `${String(h)}.00 ${suffix}`;
    }

    function badgeClass(status) {
      const s = (status || '').toLowerCase();
      return s === 'completed' ? 'success' : (s === 'cancelled' ? 'danger' : 'primary');
    }

    function initials(name) {
      return name.split(' ').map(p => p[0] || '').slice(0, 2).join('').toUpperCase();
    }

    function formatDate(iso) {
      if (!iso) return '—';
      const parts = iso.split('T')[0].split('-');
      if (parts.length !== 3) return iso;
      return `${parts[2]}/${parts[1]}/${parts[0]}`;
    }

    function showError(message) {
      console.error(message);
      // You could show a toast notification here
    }