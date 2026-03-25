// Global variables
    let timeSlots = [];

    // Initialize the dashboard
    document.addEventListener('DOMContentLoaded', function() {
      // Set today's date as default
      const today = new Date().toISOString().split('T')[0];
      document.getElementById('date').value = today;
      document.getElementById('leaveDate').value = today;
      
      // Default summary date = tomorrow, but allow user to change it.
      const summaryDateEl = document.getElementById('summaryDate');
      if (summaryDateEl) {
        summaryDateEl.value = getTomorrowISODate();
        summaryDateEl.addEventListener('change', function () {
          generateTherapistAvailabilitySummary();
        });
      }

      // Render summary immediately using fallback time slots so the UI doesn't stay
      // stuck on "Generating..." while time-slots API call is slow/hanging.
      try {
        populateDefaultTimeSlots();
      } catch (e) {
        // Non-fatal if #time select is missing on some builds.
      }
      generateTherapistAvailabilitySummary();

      // Then load real time slots and re-generate to reflect correct slot list.
      loadTimeSlots().then(function () {
        generateTherapistAvailabilitySummary();
      });
    });

    function loadTimeSlots() {
      return fetch('/sheduling/therapist-availability/api/time-slots/')
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
      timeSelect.innerHTML = '<option value="">-- Select Time Slot --</option>';
      
      timeSlots.forEach(slot => {
        const option = document.createElement('option');
        option.value = slot.start_time;
        option.textContent = slot.display_name;
        timeSelect.appendChild(option);
      });
    }

    function populateDefaultTimeSlots() {
      // Keep `timeSlots` in sync with the select options for summary rendering.
      timeSlots = [
        { id: 1, start_time: '09:00', slot_name: 'Morning Slot', display_name: '9:00 AM', slot_number: 1 },
        { id: 2, start_time: '10:00', slot_name: 'Late Morning', display_name: '10:00 AM', slot_number: 2 },
        { id: 3, start_time: '14:00', slot_name: 'Afternoon Slot', display_name: '2:00 PM', slot_number: 3 },
        { id: 4, start_time: '15:00', slot_name: 'Late Afternoon', display_name: '3:00 PM', slot_number: 4 },
      ];
      const timeSelect = document.getElementById('time');
      timeSelect.innerHTML = `
        <option value="">-- Select Time Slot --</option>
        <option value="09:00">09:00 AM - 10:00 AM</option>
        <option value="10:00">10:00 AM - 11:00 AM</option>
        <option value="14:00">02:00 PM - 03:00 PM</option>
        <option value="15:00">03:00 PM - 04:00 PM</option>
      `;
    }

    function getTomorrowISODate() {
      const t = new Date();
      t.setDate(t.getDate() + 1);
      const y = t.getFullYear();
      const m = String(t.getMonth() + 1).padStart(2, '0');
      const d = String(t.getDate()).padStart(2, '0');
      return `${y}-${m}-${d}`;
    }

    function normalizeRequiredSex(sexVal) {
      const x = String(sexVal || '').trim().toUpperCase();
      if (!x) return 'Other';
      if (x.startsWith('F')) return 'Female';
      if (x.startsWith('M')) return 'Male';
      return 'Other';
    }

    function isNurseTreatmentFlag(item) {
      const nurseFlag = typeof item.is_nurse_treatment !== 'undefined'
        ? (item.is_nurse_treatment === true || item.is_nurse_treatment === 'true')
        : false;
      return nurseFlag;
    }

    function parseIntSafe(v) {
      const s = v === null || typeof v === 'undefined' ? '' : String(v).trim();
      if (!s || s === '—') return 0;
      const n = parseInt(s, 10);
      return Number.isFinite(n) ? n : 0;
    }

    async function fetchJsonWithTimeout(url, timeoutMs = 60000) {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), timeoutMs);
      try {
        const resp = await fetch(url, { signal: controller.signal });
        if (!resp.ok) {
          throw new Error(`Request failed (${resp.status})`);
        }
        return await resp.json();
      } finally {
        clearTimeout(timer);
      }
    }

    async function fetchTherapistRequiredBySlot(dateIso) {
      // "Required" should come from therapies that have been ENTERED (draft),
      // not from already scheduled/allocated results.
      const url = `/sheduling/scheduling/api/therapy-data/?status=draft&date=${encodeURIComponent(dateIso)}`;
      const json = await fetchJsonWithTimeout(url, 60000);
      const rows = (json && json.success && Array.isArray(json.data)) ? json.data : [];

      const requiredTotals = { Female: 0, Male: 0 };
      const requiredBySlot = {}; // slotStartTime -> {Female: n, Male: n}

      rows.forEach(item => {
        if (!item) return;
        if (isNurseTreatmentFlag(item)) return; // therapist availability report only
        const slot = item.timeslot;
        if (!slot) return;

        const sex = normalizeRequiredSex(item.patient_sex);
        if (sex !== 'Female' && sex !== 'Male') return;

        const req = parseIntSafe(item.therapists_required);
        if (req <= 0) return;

        if (!requiredBySlot[slot]) requiredBySlot[slot] = { Female: 0, Male: 0 };
        requiredBySlot[slot][sex] += req;
        requiredTotals[sex] += req;
      });

      return { requiredTotals, requiredBySlot };
    }

    async function fetchAvailableTherapists(dateIso, gender, timeSlotStart) {
      let apiUrl = `/sheduling/therapist-availability/api/available-therapists/?date=${encodeURIComponent(dateIso)}&gender=${encodeURIComponent(gender)}`;
      if (timeSlotStart) {
        apiUrl += `&time=${encodeURIComponent(timeSlotStart)}`;
      }
      const json = await fetchJsonWithTimeout(apiUrl, 30000);
      if (json && json.success) {
        return json.total_count || 0;
      }
      return 0;
    }

    async function generateTherapistAvailabilitySummary() {
      const box = document.getElementById('tomorrowSummary');
      if (!box) return;

      const summaryDateEl = document.getElementById('summaryDate');
      const dateIso = (summaryDateEl && summaryDateEl.value) ? summaryDateEl.value : getTomorrowISODate();
      const btn = document.getElementById('summaryGenerateBtn');
      if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Generating...';
      }

      box.innerHTML = `
        <h3><i class="fas fa-chart-bar"></i> Therapist Availability Summary</h3>
        <p style="color: var(--gray); font-style: italic; margin-bottom: 15px;">For: ${dateIso}</p>
        <div class="loading"><i class="fas fa-spinner fa-spin"></i> Loading required therapists...</div>
      `;

      try {
        const required = await fetchTherapistRequiredBySlot(dateIso);
        box.innerHTML = `
          <h3><i class="fas fa-chart-bar"></i> Therapist Availability Summary</h3>
          <p style="color: var(--gray); font-style: italic; margin-bottom: 15px;">For: ${dateIso}</p>
          <div class="loading"><i class="fas fa-spinner fa-spin"></i> Loading therapist availability totals...</div>
        `;
        const requiredBySlot = required.requiredBySlot || {};

        const [femaleAvailTotal, maleAvailTotal] = await Promise.all([
          fetchAvailableTherapists(dateIso, 'female', null),
          fetchAvailableTherapists(dateIso, 'male', null),
        ]);

        box.innerHTML = `
          <h3><i class="fas fa-chart-bar"></i> Therapist Availability Summary</h3>
          <p style="color: var(--gray); font-style: italic; margin-bottom: 15px;">For: ${dateIso}</p>
          <div class="loading"><i class="fas fa-spinner fa-spin"></i> Preparing required slot-wise tables...</div>
        `;

        // Render slot tables
        function slotDisplayName(slot) {
          return slot.display_name || slot.slot_name || slot.start_time || '';
        }

        // Slot-wise availability (male/female available counts per time slot).
        // This does NOT require scheduling; it uses leave filters + existing BOOKED TherapistBooking rows.
        box.innerHTML = `
          <h3><i class="fas fa-chart-bar"></i> Therapist Availability Summary</h3>
          <p style="color: var(--gray); font-style: italic; margin-bottom: 15px;">For: ${dateIso}</p>
          <div class="loading"><i class="fas fa-spinner fa-spin"></i> Loading slot-wise availability...</div>
        `;

        const slotStarts = (timeSlots || []).map(s => s.start_time).filter(Boolean);
        const availableFemaleBySlot = {};
        const availableMaleBySlot = {};
        const availableCache = { Female: {}, Male: {} };

        await Promise.all((slotStarts || []).map(async (start) => {
          if (!start) return;
          if (availableCache.Female[start] === undefined) {
            availableCache.Female[start] = await fetchAvailableTherapists(dateIso, 'female', start);
          }
          if (availableCache.Male[start] === undefined) {
            availableCache.Male[start] = await fetchAvailableTherapists(dateIso, 'male', start);
          }
          availableFemaleBySlot[start] = availableCache.Female[start] || 0;
          availableMaleBySlot[start] = availableCache.Male[start] || 0;
        }));

        const femaleTableRows = (timeSlots || []).map(s => {
          const start = s.start_time;
          const display = slotDisplayName(s);
          const req = requiredBySlot[start] ? requiredBySlot[start].Female : 0;
          const avail = availableFemaleBySlot[start] || 0;
          return `
            <tr>
              <td>${escapeHtml(display)}</td>
              <td><b>${req}</b></td>
              <td><b>${avail}</b></td>
            </tr>
          `;
        }).join('');

        const maleTableRows = (timeSlots || []).map(s => {
          const start = s.start_time;
          const display = slotDisplayName(s);
          const req = requiredBySlot[start] ? requiredBySlot[start].Male : 0;
          const avail = availableMaleBySlot[start] || 0;
          return `
            <tr>
              <td>${escapeHtml(display)}</td>
              <td><b>${req}</b></td>
              <td><b>${avail}</b></td>
            </tr>
          `;
        }).join('');

        box.innerHTML = `
          <div style="display:flex; gap:20px; flex-wrap:wrap; margin-bottom: 15px;">
            <div style="flex:1; min-width:220px;">
              <h4 style="margin-bottom:8px;">Therapist Available</h4>
              <div style="display:flex; gap:10px; flex-wrap:wrap;">
                <div style="padding:8px 12px; background:#fde2e9; border-radius:8px;">
                  Female available: <b>${femaleAvailTotal || 0}</b>
                </div>
                <div style="padding:8px 12px; background:#e0e7ff; border-radius:8px;">
                  Male available: <b>${maleAvailTotal || 0}</b>
                </div>
              </div>
            </div>
          </div>

          <div style="margin-top:10px;">
            <h4 style="margin-bottom:8px;">Female Therapist Required (Slot-wise)</h4>
            <table style="width:100%; border-collapse:collapse;">
              <thead>
                <tr>
                  <th style="text-align:left; border-bottom:1px solid #ddd; padding:6px;">Time Slot</th>
                  <th style="text-align:center; border-bottom:1px solid #ddd; padding:6px;">Required</th>
                  <th style="text-align:center; border-bottom:1px solid #ddd; padding:6px;">Available</th>
                </tr>
              </thead>
              <tbody>${femaleTableRows}</tbody>
            </table>
          </div>

          <div style="margin-top:20px;">
            <h4 style="margin-bottom:8px;">Male Therapist Required (Slot-wise)</h4>
            <table style="width:100%; border-collapse:collapse;">
              <thead>
                <tr>
                  <th style="text-align:left; border-bottom:1px solid #ddd; padding:6px;">Time Slot</th>
                  <th style="text-align:center; border-bottom:1px solid #ddd; padding:6px;">Required</th>
                  <th style="text-align:center; border-bottom:1px solid #ddd; padding:6px;">Available</th>
                </tr>
              </thead>
              <tbody>${maleTableRows}</tbody>
            </table>
          </div>
        `;
      } catch (e) {
        const msg = e && e.name === 'AbortError'
          ? 'Request timed out. Please try again (this can happen when the date has many draft therapies or scheduling hasn’t been processed yet).'
          : (e && e.message ? e.message : String(e));
        box.innerHTML = `
          <h3><i class="fas fa-exclamation-circle"></i> Summary could not be generated</h3>
          <p style="color: var(--gray);">Error: ${escapeHtml(msg)}</p>
        `;
      } finally {
        if (btn) {
          btn.disabled = false;
          btn.innerHTML = '<i class="fas fa-redo"></i> Generate';
        }
      }
    }

    // Expose for template `onclick` usage.
    window.generateTherapistAvailabilitySummary = generateTherapistAvailabilitySummary;

    // Simple HTML escape for dynamic HTML injection.
    function escapeHtml(str) {
      return String(str || '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
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