// Global variables
    let therapistData = null;
    let sessionsData = [];
    let calYear, calMonth;

    // Treatment slots configuration
    const TREATMENT_SLOTS = [
      { time: '6:30 AM', value: '6-30am', hour: 6, minute: 30 },
      { time: '8:30 AM', value: '8-30am', hour: 8, minute: 30 },
      { time: '10:00 AM', value: '10-00am', hour: 10, minute: 0 },
      { time: '11:30 AM', value: '11-30am', hour: 11, minute: 30 },
      { time: '2:30 PM', value: '2-30pm', hour: 14, minute: 30 },
      { time: '4:00 PM', value: '4-00pm', hour: 16, minute: 0 },
      { time: '5:30 PM', value: '5-30pm', hour: 17, minute: 30 }
    ];

    // Initialize the dashboard
    document.addEventListener('DOMContentLoaded', function() {
      // Set today's date as default
      document.getElementById('dateFilter').value = new Date().toISOString().slice(0, 10);
      
      // Load therapist data
      loadTherapistData();
      
      // Set up event listeners
      setupEventListeners();
    });

    function setupEventListeners() {
      // Date filter change
      document.getElementById('dateFilter').addEventListener('change', function() {
        const dateValue = this.value;
        if (dateValue) {
          loadSessionsForDate(dateValue);
        } else {
          // If date is cleared, load today's sessions
          const today = new Date().toISOString().slice(0, 10);
          this.value = today;
          loadSessionsForDate(today);
        }
      });

      // Status filter change
      document.getElementById('statusFilter').addEventListener('change', function() {
        filterSessions();
      });

      // Clear filters
      document.getElementById('clearFilters').addEventListener('click', function() {
        document.getElementById('dateFilter').value = new Date().toISOString().slice(0, 10);
        document.getElementById('statusFilter').value = '';
        loadTherapistData();
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
    }

    function loadTherapistData() {
      // Fetch therapist data from API
      fetch('/sheduling/therapist/api/therapist-data/')
        .then(response => response.json())
        .then(data => {
          if (data.success) {
            therapistData = data.therapist;
            sessionsData = data.sessions || [];
            console.log(therapistData);
            
            // Update therapist info
            document.getElementById('therapistName').textContent = therapistData.name;
            document.getElementById('therapistId').textContent = therapistData.id;
            document.getElementById('therapistLevel').textContent = therapistData.level;
            
            // Render all components
            renderTodaySchedule();
            renderUpcomingSessions();
            renderSessionHistory();
            
            // Initialize calendar
            const now = new Date();
            calYear = now.getFullYear();
            calMonth = now.getMonth();
            renderCalendar(calYear, calMonth);
          } else {
            showError('Failed to load therapist data: ' + (data.error || 'Unknown error'));
          }
        })
        .catch(error => {
          console.error('Error loading therapist data:', error);
          showError('Error loading therapist data');
        });
    }

    function loadSessionsForDate(date) {
      const todayTimeline = document.getElementById('todayTimeline');
      todayTimeline.innerHTML = '<div class="text-muted text-center py-4">Loading sessions...</div>';
      
      fetch(`/sheduling/therapist/api/sessions-by-date/?date=${date}`)
        .then(response => response.json())
        .then(data => {
          if (data.success) {
            renderSessionsForDate(data.sessions || [], date);
          } else {
            todayTimeline.innerHTML = '<div class="text-muted text-center py-4">No sessions found for this date.</div>';
          }
        })
        .catch(error => {
          console.error('Error loading sessions for date:', error);
          todayTimeline.innerHTML = '<div class="text-danger text-center py-4">Error loading sessions.</div>';
        });
    }

    function renderSessionsForDate(sessions, date) {
      const todayTimeline = document.getElementById('todayTimeline');
      
      // Format date for display
      if (date) {
          document.getElementById('todayDate').textContent = formatDate(date);
      }
      
      todayTimeline.innerHTML = '';
      
      // Check if TREATMENT_SLOTS is defined
      if (typeof TREATMENT_SLOTS === 'undefined') {
        todayTimeline.innerHTML = '<div class="text-danger text-center py-4">Error: Treatment slots not defined.</div>';
        return;
      }
      
      TREATMENT_SLOTS.forEach(slot => {
        const session = sessions.find(s => s.slot_value === slot.value);
        
        const slotElement = document.createElement('div');
        slotElement.className = 'timeline-slot';
        
        slotElement.innerHTML = `
          <div class="timeline-time">${slot.time}</div>
          <div class="timeline-content">
            ${session ? `
              <div class="slot-session slot-${slot.value}">
                <div class="d-flex justify-content-between align-items-start">
                  <div class="flex-grow-1">
                    <div class="d-flex align-items-center mb-1">
                      <h6 class="mb-0 fw-semibold me-2">${session.patient_name}</h6>
                      <span class="badge rounded-pill text-bg-${badgeClass(session.status)} status-badge">${session.status}</span>
                    </div>
                    <div class="small text-muted mb-1">
                      ${session.therapy}${session.is_bathing === true ? '<span class="bathing-flag">(bathing)</span>' : ''}
                    </div>
                    <div class="small">
                      <span><i class="bi bi-geo-alt me-1"></i> ${session.room}</span>
                    </div>
                    ${session.notes ? `<div class="small mt-1 text-muted"><i class="bi bi-journal-text me-1"></i> ${session.notes}</div>` : ''}
                  </div>
                  <div class="avatar ms-3">${initials(session.patient_name)}</div>
                </div>
              </div>
            ` : `
              <div class="slot-session empty">
                <div class="text-muted">No session scheduled</div>
              </div>
            `}
          </div>
        `;
        
        todayTimeline.appendChild(slotElement);
      });
      
      // Update session count
      document.getElementById('todaySessions').textContent = sessions.length;
    }

    function renderTodaySchedule() {
      const today = new Date().toISOString().slice(0, 10);
      const todaySessions = sessionsData.filter(s => s.date === today);
      renderSessionsForDate(todaySessions, today);
    }

    function renderUpcomingSessions() {
      const upcomingSessionsList = document.getElementById('upcomingSessionsList');
      const today = new Date().toISOString().slice(0, 10);
      const upcoming = sessionsData
        .filter(s => s.date > today && s.status === 'Scheduled')
        .sort((a, b) => a.date.localeCompare(b.date))
        .slice(0, 5);
      
      upcomingSessionsList.innerHTML = '';
      
      if (upcoming.length === 0) {
        upcomingSessionsList.innerHTML = '<div class="text-muted p-3 text-center">No upcoming sessions.</div>';
        return;
      }
      
      upcoming.forEach(session => {
        const div = document.createElement('div');
        div.className = 'list-group-item border-0';
        
        div.innerHTML = `
          <div class="d-flex w-100 justify-content-between align-items-start">
            <div class="flex-grow-1">
              <h6 class="mb-1 fw-semibold">${session.patient_name}</h6>
                    <div class="small text-muted mb-1">
                      ${session.therapy}${session.is_bathing === true ? '<span class="bathing-flag">(bathing)</span>' : ''}
                    </div>
              <div class="small">
                <span class="me-3"><i class="bi bi-calendar me-1"></i> ${formatDate(session.date)}</span>
                <span class="me-3"><i class="bi bi-clock me-1"></i> ${session.slot}</span>
                <span><i class="bi bi-geo-alt me-1"></i> ${session.room}</span>
              </div>
            </div>
            <div class="avatar ms-3">${initials(session.patient_name)}</div>
          </div>
        `;
        upcomingSessionsList.appendChild(div);
      });
    }

    function renderSessionHistory() {
      const sessionHistoryBody = document.getElementById('sessionHistoryBody');
      const today = new Date().toISOString().slice(0, 10);
      const sevenDaysAgo = new Date();
      sevenDaysAgo.setDate(sevenDaysAgo.getDate() - 7);
      const sevenDaysAgoStr = sevenDaysAgo.toISOString().slice(0, 10);
      
      // Only show past sessions (not today or future) from the last 7 days
      const pastSessions = sessionsData
        .filter(s => s.date < today && s.date >= sevenDaysAgoStr && s.status === 'Completed')
        .sort((a, b) => b.date.localeCompare(a.date));
      
      sessionHistoryBody.innerHTML = '';
      
      if (pastSessions.length === 0) {
        const emptyRow = document.createElement('tr');
        emptyRow.innerHTML = `
          <td colspan="6" class="text-center text-muted py-4">No session history for the past 7 days.</td>
        `;
        sessionHistoryBody.appendChild(emptyRow);
        return;
      }
      
      pastSessions.forEach(session => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
          <td>${formatDate(session.date)}</td>
          <td>${session.slot}</td>
          <td>${session.patient_name} (${session.patient_id})</td>
          <td>
            ${session.therapy}${session.is_bathing === true ? '<span class="bathing-flag">(bathing)</span>' : ''}
          </td>
          <td>${session.room}</td>
          <td><span class="badge rounded-pill text-bg-${badgeClass(session.status)} status-badge">${session.status}</span></td>
        `;
        sessionHistoryBody.appendChild(tr);
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
            
            // Add session count badge
            if (sessions.length > 1) {
              const countBadge = document.createElement('div');
              countBadge.className = 'event-count';
              countBadge.textContent = sessions.length > 9 ? '9+' : sessions.length;
              cell.appendChild(countBadge);
            }
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
          card.className = `session-card mb-3 p-3 border rounded ${session.status.toLowerCase().replace(' ', '-')}`;
          
          card.innerHTML = `
            <div class="d-flex justify-content-between align-items-start mb-2">
              <div>
                <div class="fw-bold">${session.patient_name} (${session.patient_id})</div>
                <div class="text-muted">
                  ${session.therapy}${session.is_bathing === true ? '<span class="bathing-flag">(bathing)</span>' : ''}
                </div>
                <div class="text-muted mt-1">
                  <span class="me-3"><i class="bi bi-clock me-1"></i> ${session.slot}</span>
                  <span><i class="bi bi-geo-alt me-1"></i> ${session.room}</span>
                </div>
              </div>
              <div><span class="badge rounded-pill text-bg-${badgeClass(session.status)} status-badge">${session.status}</span></div>
            </div>
            ${session.notes ? `<div class="text-muted"><span class="fw-medium">Notes:</span> ${session.notes}</div>` : ''}
          `;
          modalBody.appendChild(card);
        });
      }
      modal.show();
    }

    function filterSessions() {
      const statusFilter = document.getElementById('statusFilter').value;
      const dateFilter = document.getElementById('dateFilter').value;
      
      // Always use the date filter - if empty, use today's date
      const targetDate = dateFilter || new Date().toISOString().slice(0, 10);
      
      if (statusFilter) {
        // Load sessions for the date first, then filter by status
        fetch(`/sheduling/therapist/api/sessions-by-date/?date=${targetDate}`)
          .then(response => response.json())
          .then(data => {
            if (data.success) {
              const sessions = data.sessions || [];
              const filteredSessions = sessions.filter(s => s.status === statusFilter);
              renderSessionsForDate(filteredSessions, targetDate);
            } else {
              const todayTimeline = document.getElementById('todayTimeline');
              todayTimeline.innerHTML = '<div class="text-muted text-center py-4">No sessions found for this date.</div>';
            }
          })
          .catch(error => {
            console.error('Error loading sessions for date:', error);
            const todayTimeline = document.getElementById('todayTimeline');
            todayTimeline.innerHTML = '<div class="text-danger text-center py-4">Error loading sessions.</div>';
          });
      } else {
        // Show all sessions for the date
        loadSessionsForDate(targetDate);
      }
    }

    // Helper functions
    function badgeClass(status) {
      const s = (status || '').toLowerCase();
      if (s === 'completed') return 'success';
      if (s === 'in progress') return 'warning';
      if (s === 'cancelled') return 'danger';
      return 'primary';
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