$(function(){

  // --- config/fallbacks ---
  const API_URL = window.location.pathname;
  const FALLBACK_PROCURED = [{name:'IP Pharmacy'},{name:'Kashaya room'}];
  const FALLBACK_OIL = [{name:'Dhara'},{name:'Pizichil'},{name:'Head'}];
  const FALLBACK_SLOTS = [{start_time:'06:30'},{start_time:'08:30'},{start_time:'10:00'},{start_time:'11:30'},{start_time:'14:30'},{start_time:'16:00'},{start_time:'17:30'}];

  // --- helpers ---
  function ajax(params){
    const url = API_URL + '?' + $.param(params);
    return fetch(url).then(r => { if (!r.ok) throw new Error('Network'); return r.json(); });
  }
  function esc(s){ return String(s||''); }
  function getDateRange(from, to){ const out=[]; let cur=new Date(from+'T00:00:00'), end=new Date(to+'T00:00:00'); while(cur<=end){ out.push(cur.toISOString().slice(0,10)); cur.setDate(cur.getDate()+1);} return out; }
  function getCookie(name) { let v = document.cookie.match('(^|;)\\s*' + name + '\\s*=\\s*([^;]+)'); return v ? v.pop() : ''; }
  function parseUsageInput(raw) {
    if (!raw) return [];
    return raw
      .split(/[\n,]+/)
      .map(u => (u || '').trim())
      .filter(Boolean);
  }
  function buildUsageTextFromData(data) {
    if (!data) return '';
    if (typeof data === 'string') return data;
    if (Array.isArray(data)) return data.join(', ');
    return '';
  }

  // Load UnitNo options from master table
  function loadUnitNumbers() {
    fetch('/unit_numbers/')
      .then(response => response.json())
      .then(data => {
        const $unitSelect = $('#item-builder-uno');
        $unitSelect.find('option').not(':first').remove(); // Keep first option
        if (data.units && data.units.length > 0) {
          data.units.forEach(unit => {
            $unitSelect.append(`<option value="${unit.unit_name}">${unit.unit_name}</option>`);
          });
        }
      })
      .catch(error => {
        console.error('Error loading unit numbers:', error);
      });
  }

  // --- DOM refs ---
  const $patientSelect = $('#header-patient-select');
  const $therapySelect = $('#therapy-select'), $slotSelect = $('#slot-select'), $fromDate = $('#from-date-input'), $toDate = $('#to-date-input'), $daysInput = $('#days-input');
  const $therapyUsageInput = $('#therapy-usage-input');
  const $procuredSelect = $('#procured-select');
  const $itemBuilder = $('#item-builder-select'), $itemGroupsList = $('#item-groups-list');
  const $itemBuilderOilClass = $('#item-builder-oil-class');
  const $allocateBtn = $('#allocate-therapy-btn'), $updateBtn = $('#update-therapy-btn'), $clearBtn = $('#clear-form');
  const $therapiesTableBody = $('#therapies-table-body');

  const $cancelModal = $('#cancel-modal-backdrop'), $cancelFrom = $('#cancel-from'), $cancelTo = $('#cancel-to'), $cancelReason = $('#cancel-reason');
  const $cancelSubmitBtn = $('#cancel-submit'), $cancelCloseBtn = $('#cancel-modal-close'), $cancelModalInfo = $('#cancel-modal-info');

  const $statusModal = $('#status-modal-backdrop'), $statusDatesList = $('#status-dates-list'), $statusModalInfo = $('#status-modal-info');
  const $statusCloseBtn = $('#status-modal-close');

  const $resumeModal = $('#resume-modal-backdrop');
  const $resumeCloseBtn = $('#resume-modal-close');

  // --- state ---
  let itemGroups = [];
  let addedTherapies = [];
  let bookings = []; // local cache mapping of bookings (keeps UI responsive)
  let editTherapyIndex = null;
  let viewingStatusTherapyIndex = null;
  let cancelingTherapyIndex = null;
  let resumingTherapyIndex = null;
  let selectedPatient = null;

  // Patient search with auto-fill functionality
  let searchTimeout;
  let initialPatientsLoaded = false;
  
  // Tab switching functionality
  $('.search-tab-btn').on('click', function() {
    const tab = $(this).data('tab');
    
    // Update active tab
    $('.search-tab-btn').removeClass('active').css({
      'border-bottom-color': 'transparent',
      'color': 'var(--text-medium)'
    });
    $(this).addClass('active').css({
      'border-bottom-color': 'var(--primary)',
      'color': 'var(--primary)'
    });
    
    // Show/hide tab content
    $('.search-tab-content').hide();
    if (tab === 'name-reg') {
      $('#name-reg-search-tab').show();
      $('#header-patient-select').focus();
    } else if (tab === 'room') {
      $('#room-search-tab').show();
      $('#header-room-search').focus();
      $('#search-results').hide();
    }
  });
  
  // Show 10 active patients when search box is focused/clicked (Name/Reg No search)
  $('#header-patient-select').on('focus', function() {
    const query = $(this).val().trim();
    // If search box is empty, show 10 active patients
    if (query.length === 0 && !initialPatientsLoaded) {
      searchPatients('', true); // true = initial load (show 10 patients)
      initialPatientsLoaded = true;
    }
  });
  
  $('#header-patient-select').on('input', function() {
    const query = $(this).val().trim();
    
    clearTimeout(searchTimeout);
    
    // If query is cleared, show initial 10 again
    if (query.length === 0) {
      if (initialPatientsLoaded) {
        searchPatients('', true);
      } else {
        $('#search-results').hide();
      }
      return;
    }
    
    // Filter as user types (no minimum character restriction)
    searchTimeout = setTimeout(() => {
      searchPatients(query, false); // false = filtered search
      initialPatientsLoaded = false; // Reset flag when filtering
    }, 300);
  });
  
  // Room number search functionality
  $('#search-room-btn').on('click', function() {
    const roomNumber = $('#header-room-search').val().trim();
    if (!roomNumber) {
      alert('Please enter a room number');
      return;
    }
    searchPatientsByRoom(roomNumber);
  });
  
  // Allow Enter key to trigger room search
  $('#header-room-search').on('keypress', function(e) {
    if (e.which === 13) {
      e.preventDefault();
      $('#search-room-btn').click();
    }
  });
  
  // Clear room search
  $('#clear-room-btn').on('click', function() {
    $('#header-room-search').val('');
    $('#search-results').hide();
  });
  
  // Function to search patients by room number
  function searchPatientsByRoom(roomNumber) {
    $('#search-results').html('<div style="padding:10px;color:#666;">Searching...</div>').show();
    
    fetch('/authentication/api/search-patients-by-room/?room=' + encodeURIComponent(roomNumber))
      .then(response => response.json())
      .then(data => {
        const patients = data.patients || [];
        displaySearchResults(patients);
      })
      .catch(error => {
        console.error('Room search error:', error);
        $('#search-results').html('<div style="padding:10px;color:#d9534f;">Error searching patients by room number</div>').show();
      });
  }

  function searchPatients(query, isInitialLoad = false) {
    // isInitialLoad: true = show 10 active patients, false = filter based on query
    // For initial load, pass empty query with a flag
    const url = isInitialLoad 
      ? '/authentication/api/search-patients/?q=&initial=true'
      : '/authentication/api/search-patients/?q=' + encodeURIComponent(query);
    
    fetch(url)
      .then(response => response.json())
      .then(data => {
        // Handle both response formats: {patients: [...]} or [...]
        const patients = data.patients || data || [];
        displaySearchResults(patients);
      })
      .catch(error => {
        console.error('Search error:', error);
        $('#search-results').html('<div style="padding:10px;color:#d9534f;">Error searching patients</div>').show();
      });
  }

  function displaySearchResults(patients) {
    const resultsContainer = $('#search-results');
    resultsContainer.empty();

    if (patients.length === 0) {
      resultsContainer.html('<div style="padding:10px;color:#666;">No patients found</div>').show();
      return;
    }

    patients.forEach(patient => {
      // Handle both field name formats: pat_reg_no/registration_number, pat_name/patient_name
      const regNo = patient.pat_reg_no || patient.registration_number;
      const patName = patient.pat_name || patient.patient_name;
      const patientType = patient.patient_type || (patient.source === 'IP' ? 'IP' : 'OP');
      const roomNo = patient.room_number || patient.pat_room_no || null;
      
      const resultItem = $(`
        <div style="padding:10px;border-bottom:1px solid #eee;cursor:pointer;" class="search-result-item" data-reg-no="${regNo}">
          <div style="display:flex;justify-content:space-between;align-items:center;">
            <div>
              <strong>${patName || 'Unknown'}</strong>
              <div style="font-size:0.9em;color:#666;margin-top:2px;">
                Reg: ${regNo}${roomNo ? ' | Room: ' + roomNo : ''}
              </div>
            </div>
            <div>
              ${patientType === 'IP' ? '<span style="background:#007bff;color:white;padding:2px 6px;border-radius:3px;font-size:0.8em;">IP</span>' : '<span style="background:#28a745;color:white;padding:2px 6px;border-radius:3px;font-size:0.8em;">OP</span>'}
            </div>
          </div>
        </div>
      `);
      resultsContainer.append(resultItem);
    });

    resultsContainer.show();
  }

  // Handle patient selection
  $(document).on('click', '.search-result-item', function() {
    const regNo = $(this).data('reg-no');
    loadPatientDetails(regNo);
  });

  // Hide search results when clicking outside
  $(document).on('click', function(e) {
    if (!$(e.target).closest('#header-patient-select, #header-room-search, #search-results, #search-room-btn').length) {
      $('#search-results').hide();
    }
  });

  function loadPatientDetails(regNo) {
    $('#search-results').hide();

    fetch('/get-patient-details/?pat_reg_no=' + encodeURIComponent(regNo))
      .then(response => response.json())
      .then(data => {
        if (data.pat_name) {
          selectedPatient = data;
          populatePatientInfo(selectedPatient);
        } else {
          alert('Patient details not found');
        }
      })
      .catch(error => {
        console.error('Error loading patient details:', error);
        alert('Error loading patient details');
      });
  }

  function updatePatientAvatar(patient) {
    if (!patient) {
      $('#patient-avatar').text('?').css('background', '#6c757d');
      return;
    }
    
    const name = patient.pat_name || '';
    const initials = name.split(' ').map(n => n[0]).join('').toUpperCase().substring(0, 2);
    $('#patient-avatar').text(initials || '?');
    
    // Set VIP status badge
    if (patient.vip_status && patient.vip_status.toLowerCase() === 'yes') {
      $('#hdr-pat-vip-badge').show();
    } else {
      $('#hdr-pat-vip-badge').hide();
    }
    
    // Set IP/OP status badge
    if (patient.patient_type === 'IP') {
      $('#hdr-pat-ip-badge').show();
    } else {
      $('#hdr-pat-ip-badge').hide();
    }
    
    // Update patient info fields with bold/highlighted styling
    const regNo = patient.pat_reg_no || patient.pat_op_reg_no || '—';
    const room = patient.pat_room_no || '—';
    const age = patient.pat_age || '—';
    const gender = patient.pat_sex || '—';
    const type = patient.patient_type || '—';
    
    $('#hdr-pat-reg').html(`<strong style="font-weight: bold; color: var(--primary);">${regNo}</strong>`);
    $('#hdr-pat-room').html(`<strong style="font-weight: bold; color: var(--primary);">${room}</strong>`);
    $('#hdr-pat-age').html(`<strong style="font-weight: bold; color: var(--primary);">${age}</strong>`);
    $('#hdr-pat-gender').html(`<strong style="font-weight: bold; color: var(--primary);">${gender}</strong>`);
    $('#hdr-pat-type').html(`<strong style="font-weight: bold; color: var(--primary);">${type}</strong>`);
  }

  function populatePatientInfo(patient) {
    // ALWAYS clear form completely whenever a patient is loaded
    // This ensures all fields are empty and fresh, like a page refresh
    
    // Complete reset - clear everything
    editTherapyIndex = null;
    cancelingTherapyIndex = null;
    resumingTherapyIndex = null;
    viewingStatusTherapyIndex = null;
    pendingSlotValue = null;
    
    // Close any open modals
    $cancelModal.hide();
    $resumeModal.hide();
    $statusModal.hide();
    
    // Clear all form fields completely
    $('#form-title').text('Create New Therapy');
    $therapySelect.val(null).trigger('change').prop('disabled', false);
    $slotSelect.val('').prop('disabled', false);
    $('#ext-int-select').val('').prop('value', '');
    $fromDate.val('').prop('value', '').prop('disabled', false);
    $toDate.val('').prop('value', '').prop('disabled', false);
    $daysInput.val('').prop('value', '');
    $therapyUsageInput.val('').prop('value', '');
    
    // Clear procured select
    $procuredSelect.val('').prop('value', '');
    if ($procuredSelect.hasClass('select2-hidden-accessible')) {
      $procuredSelect.trigger('change');
    }
    
    // Clear item builder fields
    if ($itemBuilder.hasClass('select2-hidden-accessible')) {
      $itemBuilder.val(null).trigger('change');
    } else {
      $itemBuilder.val(null);
    }
    $('#item-builder-dosage').val('').prop('value', '');
    $('#item-builder-uno').val('').prop('value', '');
    $itemBuilderOilClass.val('').prop('value', '');
    if ($itemBuilderOilClass.hasClass('select2-hidden-accessible')) {
      $itemBuilderOilClass.trigger('change');
    }
    
    // Clear item groups
    itemGroups = [];
    renderItemGroups();
    
    // Reset buttons
    $allocateBtn.show();
    $updateBtn.hide();
    
    // Clear therapies and bookings - will be reloaded for new patient
    addedTherapies = [];
    bookings = [];
    
    selectedPatient = patient; // Store patient globally
    $('#header-patient-select').val(patient.pat_reg_no || patient.pat_op_reg_no);
    // Make patient name bold/highlighted
    $('#hdr-pat-name').html(`<strong style="font-weight: bold; color: var(--primary);">${patient.pat_name || 'Unknown'}</strong>`);
    updatePatientAvatar(patient);
    
    // Clear therapy select to refresh with new patient type filter
    if ($therapySelect.length) {
      $therapySelect.val(null).trigger('change');
    }
    
    // Load patient therapies - this will refresh the entire therapy list
    // Use pat_reg_no consistently (or pat_op_reg_no if pat_reg_no doesn't exist)
    const patientRegNo = patient.pat_reg_no || patient.pat_op_reg_no;
    ajax({action:'patient_therapies', patient_reg_no: patientRegNo}).then(list => {
      // Completely replace therapies list with new patient's data
      addedTherapies = list || [];
      bookings = [];
      addedTherapies.forEach((t, idx) => {
        if (t.from_date && t.to_date) getDateRange(t.from_date, t.to_date).forEach(d => bookings.push({ id: Math.random().toString(36).slice(2,9), allocation_id: t.allocation_id || t.allocation_id || t.allocation_id, therapyIndex: idx, date:d, slot: t.slot||'', room: t.room||'', therapist: t.therapist||'', status: 'scheduled' }));
      });
      renderAll();
    }).catch(()=>{ 
      // On error, still render to show empty state
      addedTherapies = [];
      bookings = [];
      renderAll(); 
    });
  }

  // Clear patient selection functionality
  function clearPatientSelection() {
    selectedPatient = null;
    $('#header-patient-select').val('');
    $('#hdr-pat-name').text('No patient selected');
    updatePatientAvatar(null);
    $('#hdr-pat-vip-badge').hide();
    $('#hdr-pat-ip-badge').hide();
    $('#hdr-pat-reg').html('—');
    $('#hdr-pat-room').html('—');
    $('#hdr-pat-age').html('—');
    $('#hdr-pat-gender').html('—');
    $('#hdr-pat-type').html('—');
    addedTherapies = [];
    bookings = [];
    renderAll();
  }

  // Clear button event handler
  $('#clear-patient-btn').on('click', function() {
    clearPatientSelection();
    $('#search-results').hide();
  });

  // Helper function to convert 24-hour time to 12-hour format
  function format12Hour(time24) {
    if (!time24) return '';
    const parts = String(time24).split(':');
    if (parts.length !== 2) return time24;
    let hours = parseInt(parts[0], 10);
    const minutes = parts[1];
    const period = hours >= 12 ? 'PM' : 'AM';
    hours = hours % 12;
    hours = hours ? hours : 12; // 0 should be 12
    return `${hours}:${minutes} ${period}`;
  }

  function formatStaffNames(staffList, isTherapist = true) {
    if (!Array.isArray(staffList) || staffList.length === 0) return '—';
    const names = staffList.map(entry => {
      if (!entry) return null;
      let rawName = '';
      let isBathing = false;
      if (typeof entry === 'string') {
        rawName = entry;
        const trimmed = rawName.trim();
        isBathing = trimmed.startsWith('*') || /\(bathing\)/i.test(trimmed);
      } else if (typeof entry === 'object') {
        rawName = entry.name || entry.code || '';
        isBathing = entry.is_bathing === true;
      }
      const cleaned = rawName.replace(/\(bathing\)/gi, '').replace(/^\*/, '').trim();
      if (!cleaned) return null;
      return (isTherapist && isBathing) ? `*${cleaned}` : cleaned;
    }).filter(Boolean);
    return names.length ? names.join(', ') : '—';
  }

  // --- init select2s ---
  $therapySelect.select2({ 
    placeholder:'Search therapy (2+)', 
    minimumInputLength:2, 
    ajax:{
      transport: function(p,s,f){ 
        // Get patient type from selected patient
        const patientType = selectedPatient ? (selectedPatient.patient_type || 'IP') : '';
        ajax({action:'search_therapies', q: p.data.q, patient_type: patientType}).then(s).catch(f); 
      },
      processResults: data => ({ 
        results: (data||[]).map(t => ({
          id: t.therapy_code, 
          text: t.therapy_name,
          therapy_category: t.therapy_category || ''
        }))
      }),
      cache:true
    }
  });
  
  // Function to update slots based on therapy difficulty
  function updateSlotsForTherapy() {
    const selectedTherapy = $therapySelect.select2('data');
    if (!selectedTherapy || selectedTherapy.length === 0) {
      // No therapy selected, show all slots
      return populateSlots();
    }
    
    const therapy = selectedTherapy[0];
    const therapyCategory = therapy.therapy_category || '';
    
    // If therapy difficulty is "Hard", filter out 5:30 PM and 11:30 AM slots
    if (therapyCategory.toLowerCase() === 'hard') {
      // Exclude 17:30 (5:30 PM) and 11:30 (11:30 AM) in HH:MM format
      return populateSlots(['17:30', '11:30']);
    } else {
      // Show all slots for other difficulties
      return populateSlots();
    }
  }
  
  // Helper function to normalize slot time to HH:MM format
  function normalizeSlotTime(slotTime) {
    if (!slotTime) return '';
    const timeStr = String(slotTime).trim();
    if (!timeStr.includes(':')) return timeStr;
    const [hours, minutes] = timeStr.split(':');
    return `${hours.padStart(2, '0')}:${minutes}`;
  }

  // Function to populate slots with optional exclusion list
  function populateSlots(excludeSlots = []) {
    return ajax({action:'slots'}).then(resp => { 
      const slots = (resp && resp.slots) || resp || FALLBACK_SLOTS; 
      $slotSelect.find('option').not(':first').remove(); 
      (slots||FALLBACK_SLOTS).forEach(s => { 
        const st = s.start_time || s.slot_time || s;
        const slotTime = typeof st === 'string' ? st : (st.strftime ? st.strftime('%H:%M') : String(st));
        
        // Normalize slot time to HH:MM format for comparison
        let normalizedSlotTime = normalizeSlotTime(slotTime);
        
        // Check if this slot should be excluded
        const shouldExclude = excludeSlots.some(exclude => {
          // Normalize exclude time to HH:MM format
          let normalizedExclude = normalizeSlotTime(exclude);
          return normalizedSlotTime === normalizedExclude;
        });
        
        if (!shouldExclude) {
          const displayText = format12Hour(slotTime);
          $slotSelect.append(`<option value="${slotTime}">${displayText}</option>`);
        }
      }); 
      return Promise.resolve(); // Return promise for chaining
    }).catch(()=>{ 
      $slotSelect.find('option').not(':first').remove(); 
      FALLBACK_SLOTS.forEach(s => {
        const st = s.start_time || s;
        const slotTime = typeof st === 'string' ? st : (st.strftime ? st.strftime('%H:%M') : String(st));
        
        // Normalize slot time to HH:MM format for comparison
        let normalizedSlotTime = normalizeSlotTime(slotTime);
        
        // Check if this slot should be excluded
        const shouldExclude = excludeSlots.some(exclude => {
          // Normalize exclude time to HH:MM format
          let normalizedExclude = normalizeSlotTime(exclude);
          return normalizedSlotTime === normalizedExclude;
        });
        
        if (!shouldExclude) {
          const displayText = format12Hour(slotTime);
          $slotSelect.append(`<option value="${slotTime}">${displayText}</option>`);
        }
      }); 
      return Promise.resolve(); // Return promise for chaining
    });
  }
  
  // Store the slot value that should be restored after slot repopulation (for edit mode)
  let pendingSlotValue = null;
  
  // Listen for therapy selection changes
  $therapySelect.on('change', function() {
    updateSlotsForTherapy().then(() => {
      // If there's a pending slot value (from edit mode), restore it after slots are populated
      if (pendingSlotValue) {
        setTimeout(() => {
          const normalizedPending = normalizeSlotTime(pendingSlotValue);
          let foundValue = null;
          
          // Try to find exact match
          let foundOption = $slotSelect.find(`option[value="${pendingSlotValue}"]`);
          if (foundOption.length > 0) {
            foundValue = foundOption.val();
          } else {
            // Try to find by normalized value
            $slotSelect.find('option').each(function() {
              const optionValue = $(this).val();
              if (optionValue && normalizeSlotTime(optionValue) === normalizedPending) {
                foundValue = optionValue;
                return false;
              }
            });
          }
          
          if (foundValue) {
            $slotSelect.val(foundValue);
          } else {
            $slotSelect.val(pendingSlotValue);
          }
          pendingSlotValue = null; // Clear after setting
        }, 50);
      }
    });
  });

  $itemBuilder.select2({
    placeholder:'Search or type items (multi)',
    minimumInputLength: 0,
    tags: true,
    tokenSeparators: [','],
    ajax: {
      transport: function(p, s, f){
        ajax({action:'search_items', q: p.data.q}).then(s).catch(function(){ s({ results: [] }); });
      },
      processResults: data => ({ results: (data||[]).map(i => ({ id: i.item_code, text: i.item_name })) }),
      cache:true
    }
  });

  // populate masters & slots with fallback
  function populateMasters(){
    ajax({action:'masters', type:'procured'}).then(list => { $procuredSelect.empty().append('<option value="">-- Select --</option>'); (list||FALLBACK_PROCURED).forEach(p => $procuredSelect.append(new Option(p.name, p.name))); }).catch(()=>{ $procuredSelect.empty().append('<option value="">-- Select --</option>'); FALLBACK_PROCURED.forEach(p => $procuredSelect.append(new Option(p.name, p.name))); });
    // Populate Oil Class in item builder section
    ajax({action:'masters', type:'oil'}).then(list => { $itemBuilderOilClass.empty().append('<option value="">-- Select --</option>'); (list||FALLBACK_OIL).forEach(o => $itemBuilderOilClass.append(new Option(o.name, o.name))); }).catch(()=>{ $itemBuilderOilClass.empty().append('<option value="">-- Select --</option>'); FALLBACK_OIL.forEach(o => $itemBuilderOilClass.append(new Option(o.name, o.name))); }); 
    // Use updateSlotsForTherapy to populate slots (respects therapy difficulty)
    updateSlotsForTherapy();
  }
  populateMasters();

  // Add Group
  $('#add-item-group-btn').on('click', function(){
    const selected = $itemBuilder.select2('data') || [];
    const dosage = $('#item-builder-dosage').val().trim();
    const uno = $('#item-builder-uno').val().trim();
    const oilClass = $itemBuilderOilClass.val() || ''; // Get Oil Class from item builder
    
    // Validate that at least one field is selected/filled
    const hasItems = selected && selected.length > 0;
    const hasDosage = dosage && dosage.length > 0;
    const hasUnit = uno && uno.length > 0;
    const hasOilClass = oilClass && oilClass.length > 0;
    
    // Check if all fields are empty
    if (!hasItems && !hasDosage && !hasUnit && !hasOilClass) {
      alert('Please select any field and add');
      return;
    }
    
    const items = selected.length > 0 ? selected.map(s => ({ item_code: s.id, item_name: s.text || s.id })) : [];
    const grp = { id: Math.random().toString(36).slice(2,9), items, dosage, uno, oil_class: oilClass };
    itemGroups.push(grp);
    $itemBuilder.val(null).trigger('change');
    $('#item-builder-dosage').val('');
    $('#item-builder-uno').val('');
    $itemBuilderOilClass.val(''); // Clear Oil Class after adding
    renderItemGroups();
  });

  function renderItemGroups(){
    $itemGroupsList.empty();
    if (!itemGroups.length){ 
      $itemGroupsList.html(`
        <div class="empty-state" style="padding:20px;">
          <i class="fas fa-pills"></i>
          <p>No therapy items added yet</p>
        </div>
      `); 
      return; 
    }
    itemGroups.forEach((g,i) => {
      const itemsHtml = g.items && g.items.length > 0 ? g.items.map(it => `<span class="tag">${esc(it.item_name)}</span>`).join(' ') : '<span class="tag" style="color:#999;">No items</span>';
      const $div = $(`
        <div style="padding:12px;border:1px solid var(--border-light);margin-bottom:12px;border-radius:8px;display:flex;justify-content:space-between;align-items:center;background:white;">
          <div style="flex:1;">
            <div style="font-weight:600;color:var(--text-dark);margin-bottom:6px;">Group ${i+1}</div>
            <div style="margin-bottom:6px;">${itemsHtml}</div>
            <div class="small-muted">Dosage: ${esc(g.dosage||'—')} • UNO: ${esc(g.uno||'—')} • Oil Class: ${esc(g.oil_class||'—')}</div>
          </div>
          <div>
            <button class="edit-group action-btn btn btn-outline" data-id="${g.id}" style="margin-right:6px;">
              <i class="fas fa-edit"></i> Edit
            </button>
            <button class="remove-group action-btn btn btn-danger" data-id="${g.id}">
              <i class="fas fa-trash"></i> Remove
            </button>
          </div>
        </div>
      `);
      $itemGroupsList.append($div);
    });
  }

  $itemGroupsList.on('click', '.remove-group', function(){ 
    const id = $(this).data('id'); 
    itemGroups = itemGroups.filter(g=>g.id!==id); 
    renderItemGroups(); 
  });
  
  $itemGroupsList.on('click', '.edit-group', function(){ 
    const id = $(this).data('id'); 
    const g = itemGroups.find(x=>x.id===id); 
    if(!g) return; 
    $itemBuilder.val(null).trigger('change'); 
    g.items.forEach(it=>{ 
      const opt = new Option(it.item_name, it.item_code, true, true); 
      $itemBuilder.append(opt); 
    }); 
    $itemBuilder.trigger('change'); 
    $('#item-builder-dosage').val(g.dosage||''); 
    $('#item-builder-uno').val(g.uno||''); 
    // Set Oil Class in item builder
    $itemBuilderOilClass.val(g.oil_class||'');
    itemGroups = itemGroups.filter(x=>x.id!==id); 
    renderItemGroups(); 
  });

  // Auto-calculate To Date from From Date and Days
  function calcToDate() {
    const fromDate = $fromDate.val();
    const days = parseInt($daysInput.val()) || 0;
    
    if (!fromDate || days <= 0) {
      $toDate.val('');
      return;
    }
    
    const from = new Date(fromDate);
    if (isNaN(from.getTime())) {
      $toDate.val('');
      return;
    }
    
    // Calculate end date: from date + (days - 1) since the from date is day 1
    const to = new Date(from);
    to.setDate(to.getDate() + (days - 1));
    
    // Format as YYYY-MM-DD
    const year = to.getFullYear();
    const month = String(to.getMonth() + 1).padStart(2, '0');
    const day = String(to.getDate()).padStart(2, '0');
    $toDate.val(`${year}-${month}-${day}`);
  }
  
  // Calculate days from From Date and To Date (backward compatibility)
  function calcDays(){ 
    const f = $fromDate.val(), t = $toDate.val(); 
    if(!f||!t){ 
      $daysInput.val(''); 
      return; 
    } 
    const fd=new Date(f), td=new Date(t); 
    if(fd<=td) 
      $daysInput.val(Math.ceil((td.getTime()-fd.getTime())/(1000*60*60*24))+1); 
    else 
      $daysInput.val(''); 
  }
  
  // Auto-calculate To Date when From Date or Days changes
  $fromDate.on('change', function() {
    calcDays(); // Calculate days if To Date is set
    if ($daysInput.val()) {
      calcToDate(); // Auto-calculate To Date if Days is set
    }
  });
  
  $daysInput.on('input change', function() {
    if ($fromDate.val()) {
      calcToDate(); // Auto-calculate To Date when Days changes
    }
  });
  
  // Keep backward compatibility for To Date changes (manual entry disabled but kept for calculation)
  $toDate.on('change', calcDays);

  // add therapy - auto-save to server as draft
  $allocateBtn.on('click', function(){
    if (!selectedPatient) {
      alert('Please select a patient first');
      return;
    }
    
    const therapy = $therapySelect.select2('data')[0];
    if (!therapy){ alert('Select a therapy'); return; }
    const from = $fromDate.val(), to = $toDate.val();
    if (!from || !to){ alert('Please set From and To dates'); return; }
    if (from > to){ alert('From must be <= To'); return; }

    // Prepare therapy data for server
    // Use pat_reg_no consistently for IP patients (or pat_op_reg_no if pat_reg_no doesn't exist)
    const patientRegNo = selectedPatient.pat_reg_no || selectedPatient.pat_op_reg_no;
    
    const therapyUsageText = ($therapyUsageInput.val() || '').trim();
    const therapyUsageArray = parseUsageInput(therapyUsageText);

    const therapyData = {
      patient_reg_no: patientRegNo,
      patient_name: selectedPatient.pat_name || '',
      patient_age: selectedPatient.pat_age || '',
      patient_sex: selectedPatient.pat_sex || '',
      patient_room_no: selectedPatient.pat_room_no || '',
      pat_ref_id: selectedPatient.pat_ref_id || '',
      therapy_code: therapy.id,
      therapy_name: therapy.text,
      usage: therapyUsageText,
      usage_array: therapyUsageArray,
      usage_text: therapyUsageText,
      ext_int: $('#ext-int-select').val(),
      slot: $slotSelect.val() || '',
      from_date: from,
      to_date: to,
      days: Math.ceil((new Date(to).getTime() - new Date(from).getTime()) / (1000 * 60 * 60 * 24)) + 1,
      procured: $procuredSelect.val()||'',
      items_groups: itemGroups.map(g => ({ 
        items: g.items || [], 
        dosage: g.dosage, 
        uno: g.uno, 
        oil_class: g.oil_class || '' // Oil Class is now per item group
      })),
      notes: ''
    };

    // Send to server immediately
    fetch(API_URL + '?action=allocate', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(therapyData)
    })
    .then(response => {
      // Check if response is ok before parsing JSON
      if (!response.ok) {
        // Try to parse error response as JSON
        return response.json().then(data => {
          throw new Error(data.error || `Server error: ${response.status} ${response.statusText}`);
        }).catch(() => {
          // If JSON parsing fails, throw with status text
          throw new Error(`Server error: ${response.status} ${response.statusText}`);
        });
      }
      return response.json();
    })
    .then(data => {
      if (data.status === 'ok') {
        // Add to local list with server response
        const newTherapy = {
          ...therapyData,
          allocation_id: data.allocation_id,
          status: data.overall_status || 'draft', // Use overall status from server
          status_counts: data.status_counts || {},
          status_summary: data.status_summary || {},
          date_status_map: data.date_status_map || {}
        };
        addedTherapies.push(newTherapy);
        
        // Reset form
        itemGroups = []; renderItemGroups();
        $therapySelect.val(null).trigger('change'); $('#ext-int-select').val(''); $slotSelect.val(''); $fromDate.val(''); $toDate.val(''); $daysInput.val(''); $therapyUsageInput.val(''); $procuredSelect.val('');
        
        renderAll();
        
        // Reload patient therapies from server
        // Use the same registration number that was used for saving
        if (selectedPatient) {
          const patientRegNo = selectedPatient.pat_reg_no || selectedPatient.pat_op_reg_no;
          ajax({action:'patient_therapies', patient_reg_no: patientRegNo}).then(list => {
            addedTherapies = list || [];
            bookings = [];
            addedTherapies.forEach((t, idx) => {
              if (t.from_date && t.to_date) getDateRange(t.from_date, t.to_date).forEach(d => bookings.push({ id: Math.random().toString(36).slice(2,9), allocation_id: t.allocation_id || t.allocation_id || t.allocation_id, therapyIndex: idx, date:d, slot: t.slot||'', room: t.room||'', therapist: t.therapist||'', status: 'scheduled' }));
            });
            renderAll();
          }).catch(()=>{ renderAll(); });
        }
        
        alert('Therapy added and saved to server as Draft.');
      } else {
        alert('Error: ' + (data.error || 'Failed to save therapy'));
      }
    })
    .catch(error => {
      console.error('Error saving therapy:', error);
      // Show more detailed error message
      const errorMessage = error.message || 'Error saving therapy to server. Please check your connection and try again.';
      alert('Error saving therapy to server: ' + errorMessage);
    });
  });

  // render therapies table
  function renderTherapies(){
    $therapiesTableBody.empty();
    if (!addedTherapies.length){ 
      $therapiesTableBody.append(`
        <tr>
          <td colspan="10">
            <div class="empty-state">
              <i class="fas fa-spa"></i>
              <h3>No Therapies Found</h3>
              <p>Select a patient and create a new therapy to get started</p>
            </div>
          </td>
        </tr>
      `); 
      return; 
    }
    addedTherapies.forEach((t,i) => {
      // Format therapy-level usage for display
      let therapyUsageDisplay = '—';
      let usageList = [];
      if (Array.isArray(t.usage_array) && t.usage_array.length > 0) {
        usageList = t.usage_array;
      } else {
        const usageSource =
          (t.usage_text && t.usage_text.trim()) ||
          buildUsageTextFromData(t.usage) ||
          '';
        usageList = parseUsageInput(usageSource);
      }
      if (usageList.length > 0) {
        therapyUsageDisplay = esc(usageList.join(', '));
      }
      
      const groupsHtml = (t.items_groups||[]).map(g => {
        const itemsHtml = (g.items||[]).length > 0 ? (g.items||[]).map(it => `<span class="tag">${esc(it.item_name)}</span>`).join(' ') : '<span class="tag" style="color:#999;">No items</span>';
        // Oil Class is now per item group, usage is at therapy level
        return itemsHtml + `<div class="small-muted">Dosage:${esc(g.dosage||'—')} • UNO:${esc(g.uno||'—')} • Oil Class:${esc(g.oil_class||'—')}</div>`;
      }).join('<hr style="margin:8px 0;border:none;border-top:1px solid var(--border-light);"/>');
      
      // Status logic - show counts if available
      let statusHtml = '';
      let statusClass = 'status-scheduled';
      
      // Check if therapy has cancelled dates
      const hasCancelledDates = t.cancelled_date_from && t.cancelled_date_to && t.cancelled_date_from !== 'null' && t.cancelled_date_to !== 'null';
      
      // Build status display with counts - format: "2 Draft / 3 Allocated"
      // Use status_summary from backend which is based on actual booking statuses
      const statusSummary = t.status_summary || {};
      const statusParts = [];
      
      // Order: Draft, Allocated, Failed, Cancelled
      // Use status_summary values which are calculated from actual booking statuses
      if (statusSummary.draft) {
        statusParts.push(`${statusSummary.draft} Draft`);
      }
      if (statusSummary.allocated) {
        statusParts.push(`${statusSummary.allocated} Allocated`);
      }
      if (statusSummary.failed) {
        statusParts.push(`${statusSummary.failed} Failed`);
      }
      // Use status_summary.cancelled if available (based on actual booking statuses)
      // Only fall back to date range calculation if status_summary is not available
      if (statusSummary.cancelled !== undefined && statusSummary.cancelled > 0) {
        statusParts.push(`${statusSummary.cancelled} Cancelled`);
      } else if (hasCancelledDates && !statusSummary.cancelled) {
        // Fallback: Calculate cancelled days from date range only if status_summary doesn't have cancelled count
        // This handles cases where status_summary might not be populated yet
        const fromParts = t.cancelled_date_from.split('-');
        const toParts = t.cancelled_date_to.split('-');
        if (fromParts.length === 3 && toParts.length === 3) {
          const cancelledFrom = new Date(parseInt(fromParts[0]), parseInt(fromParts[1]) - 1, parseInt(fromParts[2]));
          const cancelledTo = new Date(parseInt(toParts[0]), parseInt(toParts[1]) - 1, parseInt(toParts[2]));
          const cancelledDays = Math.floor((cancelledTo - cancelledFrom) / (1000 * 60 * 60 * 24)) + 1;
          if (cancelledDays > 0) {
            statusParts.push(`${cancelledDays} Cancelled`);
          }
        }
      }
      
      // If we have detailed counts, show them with slashes
      if (statusParts.length > 0) {
        statusHtml = `<span class="status-pill status-mixed">${statusParts.join(' / ')}</span>`;
        statusClass = 'status-mixed';
      } else {
        // Fallback to overall status if no counts available
        // Also check cancelled dates for immediate feedback
        if (hasCancelledDates) {
          statusHtml = '<span class="status-pill status-cancelled">Cancelled</span>';
          statusClass = 'status-cancelled';
        } else if (t.status === 'draft') {
          statusHtml = '<span class="status-pill status-draft">Draft</span>';
          statusClass = 'status-draft';
        } else if (t.status === 'cancelled') {
          statusHtml = '<span class="status-pill status-cancelled">Cancelled</span>';
          statusClass = 'status-cancelled';
        } else if (t.status === 'allocated') {
          statusHtml = '<span class="status-pill status-scheduled">Allocated</span>';
          statusClass = 'status-scheduled';
        } else if (t.status === 'failed') {
          statusHtml = '<span class="status-pill status-cancelled">Failed</span>';
          statusClass = 'status-cancelled';
        } else {
          // Default to draft for any unknown status
          statusHtml = '<span class="status-pill status-draft">Draft</span>';
          statusClass = 'status-draft';
        }
      }
      
      const row = `<tr class="${statusClass}">
        <td>${i+1}</td>
        <td>${esc(t.therapy_name)}</td>
        <td>${therapyUsageDisplay !== '—' ? esc(therapyUsageDisplay) : '—'}</td>
        <td>${esc(t.ext_int||'')}</td>
        <td>${esc(format12Hour(t.slot||''))}</td>
        <td>${groupsHtml}</td>
        <td>${esc(t.from_date||'')}</td>
        <td>${esc(t.to_date||'')}</td>
        <td>${esc(t.days||'')}</td>
        <td>${statusHtml}</td>
        <td>
          <button class="view-status action-btn btn btn-outline" data-i="${i}">
            <i class="fas fa-eye"></i> Status
          </button>
          <button class="edit-therapy action-btn btn btn-outline" data-i="${i}">
            <i class="fas fa-edit"></i> Edit
          </button>
          <button class="update-therapy action-btn btn btn-success" data-i="${i}" style="display:none">
            <i class="fas fa-sync-alt"></i> Update
          </button>
          ${(() => {
            // Check for cancelled dates - EXACTLY like prescription entry
            const hasCancelledDates = t.cancelled_date_from && t.cancelled_date_to;
            const hasDateRange = t.from_date && t.to_date;
            let buttons = '';
            // Show resume button if there are cancelled dates
            if (hasCancelledDates) {
              buttons += `<button class="resume-therapy action-btn btn btn-success" data-i="${i}">
                <i class="fas fa-play-circle"></i> Resume
              </button>`;
            }
            // Show cancel button if there's a date range (can always cancel, will merge with existing)
            if (hasDateRange) {
              buttons += `<button class="cancel-therapy action-btn btn btn-warning" data-i="${i}">
                <i class="fas fa-ban"></i> Cancel
              </button>`;
            }
            return buttons;
          })()}
        </td>
      </tr>`;
      $therapiesTableBody.append(row);
    });
  }

  function renderAll(){ renderItemGroups(); renderTherapies(); }

  // Allocation Status (server-backed) — show date, slot, room, therapist, status; Mark as Completed allowed
  $therapiesTableBody.on('click', '.view-status', function(){ const i=$(this).data('i'); openStatusModal(i); });

  function openStatusModal(index){
    viewingStatusTherapyIndex = index;
    const t = addedTherapies[index]; if(!t) return;
    if (!t.allocation_id) {
      // fallback: show local bookings (existing behavior)
      $statusModalInfo.text(`Therapy: ${t.therapy_name} — ${t.from_date} → ${t.to_date}`);
      $statusDatesList.empty();
      const rows = bookings.filter(b=>b.therapyIndex===index).sort((a,b)=>a.date.localeCompare(b.date));
      if (!rows.length) $statusDatesList.append('<div class="empty-state" style="padding:20px;"><i class="fas fa-calendar-times"></i><p>No per-day allocations for this therapy.</p></div>');
      rows.forEach(b=> {
        const pillClass = ({scheduled:'status-scheduled', draft:'status-draft', pending:'status-draft', cancel_requested:'status-cancelreq', cancelled:'status-cancelled', completed:'status-completed'})[b.status] || 'status-scheduled';
        const statusText = ({scheduled:'Scheduled', draft:'Draft', pending:'Pending', cancel_requested:'Cancel Requested', cancelled:'Cancelled', completed:'Completed'})[b.status] || b.status;
        const $row = $(`
          <div class="status-date-row" data-id="${b.id}">
            <div style="display:flex;gap:12px;align-items:center;min-width:910px;">
              <div style="width:140px"><strong>${b.date}</strong></div>
              <div style="width:120px">${esc(format12Hour(b.slot||''))}</div>
              <div style="width:200px">${esc(b.room||'—')}</div>
              <div style="width:150px">${esc(b.patient_room_no||'—')}</div>
              <div style="width:200px">${esc(b.therapist||'—')}</div>
              <div style="width:140px"><span class="status-pill ${pillClass}">${statusText}</span></div>
            </div>
          </div>`);
        $statusDatesList.append($row);
      });
      $statusModal.show();
      return;
    }

    // fetch server allocation_status
    ajax({action:'allocation_status', allocation_id: t.allocation_id}).then(data => {
      // Check if this is a nurse treatment
      const isNurseTreatment = data.is_nurse_treatment || false;
      
      // Update header based on treatment type
      const $staffHeader = $('#status-header-row').find('#staff-header');
      if (isNurseTreatment) {
        $staffHeader.text('Nurse');
      } else {
        $staffHeader.text('Therapist');
      }
      
      // Show status summary at top
      const statusSummary = data.status_summary || {};
      const summaryParts = [];
      if (statusSummary.allocated) summaryParts.push(`${statusSummary.allocated} Allocated`);
      if (statusSummary.failed) summaryParts.push(`${statusSummary.failed} Failed`);
      if (statusSummary.cancelled) summaryParts.push(`${statusSummary.cancelled} Cancelled`);
      if (statusSummary.draft) summaryParts.push(`${statusSummary.draft} Draft`);
      
      $statusModalInfo.html(`
        <strong>Therapy: ${esc(data.therapy_name)}</strong> — ${data.from_date} → ${data.to_date}<br/>
        <small style="color:#6c757d;margin-top:4px;display:block;">${summaryParts.length > 0 ? summaryParts.join(', ') : 'Status: ' + (data.overall_status || 'Unknown')}</small>
      `);
      $statusDatesList.empty();
      
      // Group bookings by status for better visibility
      const bookingsByStatus = {};
      (data.bookings||[]).forEach(b => {
        const displayStatus = b.display_status || b.status || 'draft';
        if (!bookingsByStatus[displayStatus]) {
          bookingsByStatus[displayStatus] = [];
        }
        bookingsByStatus[displayStatus].push(b);
      });
      
      // Show status sections
      const statusOrder = ['allocated', 'failed', 'draft', 'cancelled'];
      statusOrder.forEach(status => {
        if (bookingsByStatus[status] && bookingsByStatus[status].length > 0) {
          const statusLabel = status.charAt(0).toUpperCase() + status.slice(1);
          const $section = $(`<div class="status-section"><h4>${statusLabel} Dates (${bookingsByStatus[status].length})</h4></div>`);
          $statusDatesList.append($section);
          
          bookingsByStatus[status].forEach(b => {
            const pillClass = ({scheduled:'status-scheduled', allocated:'status-scheduled', draft:'status-draft', pending:'status-draft', failed:'status-cancelled', cancel_requested:'status-cancelreq', cancelled:'status-cancelled', completed:'status-completed'})[b.status] || 'status-scheduled';
            const statusText = ({scheduled:'Scheduled', allocated:'Allocated', draft:'Draft', failed:'Failed', pending:'Pending', cancel_requested:'Cancel Requested', cancelled:'Cancelled', completed:'Completed'})[b.display_status || b.status] || b.status;
            
            // Show nurses for nurse treatments, therapists for regular treatments
            const staffNames = isNurseTreatment 
              ? formatStaffNames(b.nurses || [], false)
              : formatStaffNames(b.therapists || [], true);
            
            const $row = $(`
              <div class="status-date-row" data-id="${b.booking_id}">
                <div style="display:flex;gap:12px;align-items:center;min-width:910px;">
                  <div style="width:140px"><strong>${b.date}</strong></div>
                  <div style="width:120px">${esc(format12Hour(b.slot||''))}</div>
                  <div style="width:200px">${esc(b.room||'—')}</div>
                  <div style="width:150px">${esc(b.patient_room_no||'—')}</div>
                  <div style="width:200px">${esc(staffNames)}</div>
                  <div style="width:140px"><span class="status-pill ${pillClass}">${statusText}</span></div>
                </div>
              </div>`);
            $statusDatesList.append($row);
          });
        }
      });
      
      $statusModal.show();
    }).catch(()=>{ alert('Could not load allocation status'); });
  }


  $statusCloseBtn.on('click', function(){ $statusModal.hide(); viewingStatusTherapyIndex = null; });

  // Request cancel flow (server)
  $therapiesTableBody.on('click', '.cancel-therapy', function(){ const i=$(this).data('i'); openCancelModal(i); });
  
  function openCancelModal(index){
    cancelingTherapyIndex = index; 
    const t = addedTherapies[index]; 
    if(!t) return;
    
    let infoText = `Therapy: ${t.therapy_name} — Allowed cancel range: ${t.from_date||'—'} → ${t.to_date||'—'}`;
    
    // Set initial info text (will be updated with cancelled dates if available)
    $('#cancel-modal-info').html(infoText.replace(/\n/g, '<br>'));
    
    // Fetch booking statuses to show individual cancelled dates (not just the range)
    if (t.allocation_id && t.cancelled_date_from && t.cancelled_date_to && 
        t.cancelled_date_from !== 'null' && t.cancelled_date_to !== 'null') {
      // Fetch booking statuses to get actual cancelled dates
      ajax({action:'allocation_status', allocation_id: t.allocation_id}).then(data => {
        const bookings = data.bookings || [];
        // Get all dates in the cancelled range
        const cancelledRangeDates = getDateRange(t.cancelled_date_from, t.cancelled_date_to);
        // Filter to only dates that are actually cancelled
        const actuallyCancelledDates = cancelledRangeDates.filter(date => {
          const booking = bookings.find(b => b.date === date);
          const status = booking ? (booking.status || booking.display_status || 'draft') : 'cancelled';
          return status === 'cancelled';
        });
        
        // Update info text with individual cancelled dates
        let updatedInfoText = `Therapy: ${t.therapy_name} — Allowed cancel range: ${t.from_date||'—'} → ${t.to_date||'—'}`;
        if (actuallyCancelledDates.length > 0) {
          // Show individual cancelled dates
          const datesList = actuallyCancelledDates.map(d => formatDate(d)).join(', ');
          updatedInfoText += `<br>Already cancelled dates: ${datesList}`;
        }
        $('#cancel-modal-info').html(updatedInfoText);
      }).catch(() => {
        // Fallback: show range if we can't fetch booking statuses
        let fallbackText = infoText;
        fallbackText += `<br>Already cancelled: ${formatDate(t.cancelled_date_from)} → ${formatDate(t.cancelled_date_to)}`;
        $('#cancel-modal-info').html(fallbackText);
      });
    }
    
    // ALWAYS reset and set the date inputs to the current therapy's date range
    // Clear any previous values first
    $cancelFrom.val('');
    $cancelTo.val('');
    
    // Set min/max based on therapy date range
    if (t.from_date) {
      $cancelFrom.attr('min', t.from_date);
      $cancelFrom.attr('max', t.to_date || t.from_date);
    } else {
      $cancelFrom.removeAttr('min');
      $cancelFrom.removeAttr('max');
    }
    
    if (t.to_date) {
      $cancelTo.attr('max', t.to_date);
      $cancelTo.attr('min', t.from_date || t.to_date);
    } else {
      $cancelTo.removeAttr('max');
      $cancelTo.removeAttr('min');
    }
    
    // ALWAYS set default values to the current therapy's date range (not previous values)
    if (t.from_date && t.to_date) {
      $cancelFrom.val(t.from_date);
      $cancelTo.val(t.to_date);
    }
    
    $cancelReason.val('');
    $cancelModal.show();
  }

  $cancelCloseBtn.on('click', function(){ $cancelModal.hide(); cancelingTherapyIndex=null; });

  $cancelSubmitBtn.on('click', function(){
    if (cancelingTherapyIndex === null) return;
    const t = addedTherapies[cancelingTherapyIndex];
    if (!t) return;
    const cfrom = $cancelFrom.val(), cto = $cancelTo.val(), reason = $cancelReason.val().trim();
    if (!cfrom || !cto){ alert('Pick both Cancel From and Cancel To'); return; }
    if (cfrom > cto){ alert('Cancel From must be <= Cancel To'); return; }
    if (t.from_date && cfrom < t.from_date){ alert('Cancel From < therapy start'); return; }
    if (t.to_date && cto > t.to_date){ alert('Cancel To > therapy end'); return; }
    if (!reason){ alert('Cancellation reason is mandatory'); return; }
    
    // IMMEDIATELY update local data BEFORE server call - EXACTLY like prescription entry
    // Calculate how many days are being cancelled
    const cancelledDates = getDateRange(cfrom, cto);
    const cancelledDaysCount = cancelledDates.length;
    
    // Update status_summary optimistically to reflect the cancellation
    if (!t.status_summary) {
      t.status_summary = {};
    }
    
    // Calculate how many days were already cancelled in the new range
    let alreadyCancelledInRange = 0;
    if (t.cancelled_date_from && t.cancelled_date_to) {
      const existingCancelledDates = getDateRange(t.cancelled_date_from, t.cancelled_date_to);
      const newCancelledDates = getDateRange(cfrom, cto);
      // Count dates that are in both ranges (already cancelled)
      alreadyCancelledInRange = newCancelledDates.filter(d => existingCancelledDates.includes(d)).length;
    }
    
    // Calculate how many new days are being cancelled (not already cancelled)
    const newlyCancelledDays = cancelledDaysCount - alreadyCancelledInRange;
    
    // Update cancelled count (add newly cancelled days)
    if (newlyCancelledDays > 0) {
      t.status_summary.cancelled = (t.status_summary.cancelled || 0) + newlyCancelledDays;
      
      // Decrease draft/allocated counts for newly cancelled days
      // We need to estimate how many were draft vs allocated
      // For simplicity, we'll decrease draft first, then allocated
      const currentDraft = t.status_summary.draft || 0;
      const currentAllocated = t.status_summary.allocated || 0;
      
      if (currentDraft >= newlyCancelledDays) {
        t.status_summary.draft = currentDraft - newlyCancelledDays;
        if (t.status_summary.draft === 0) {
          delete t.status_summary.draft;
        }
      } else {
        // Decrease all draft, then decrease allocated for the remainder
        const remainingToCancel = newlyCancelledDays - currentDraft;
        if (currentDraft > 0) {
          delete t.status_summary.draft;
        }
        if (currentAllocated >= remainingToCancel) {
          t.status_summary.allocated = currentAllocated - remainingToCancel;
          if (t.status_summary.allocated === 0) {
            delete t.status_summary.allocated;
          }
        } else {
          // If allocated is less than remaining, just decrease what we have
          if (currentAllocated > 0) {
            delete t.status_summary.allocated;
          }
        }
      }
    }
    
    if (!t.cancelled_date_from || cfrom < t.cancelled_date_from) {
      t.cancelled_date_from = cfrom;
    }
    if (!t.cancelled_date_to || cto > t.cancelled_date_to) {
      t.cancelled_date_to = cto;
    }
    t.status = 'cancelled';
    t.cancellation_reason = reason;
    
    // IMMEDIATELY update UI - don't wait for server - EXACTLY like prescription entry
    $cancelModal.hide();
    renderAll();
    alert('Therapy cancelled successfully.');
    
    if (t.allocation_id) {
      // Server-side cancellation (happens in background)
      fetch(API_URL + '?action=cancel_therapy', {
        method:'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({ allocation_id: t.allocation_id, cancel_from: cfrom, cancel_to: cto, reason: reason })
      }).then(r => r.json()).then(j => {
        if (j.status === 'ok') {
          // UI already updated above, alert already shown, server sync will happen in background
          
          // Then reload from server to get merged cancellation dates (in background)
          if (t.allocation_id && selectedPatient) {
            const patientRegNo = selectedPatient.pat_op_reg_no || selectedPatient.pat_reg_no;
            if (patientRegNo) {
              ajax({action:'patient_therapies', patient_reg_no: patientRegNo}).then(therapies => {
                if (therapies && Array.isArray(therapies)) {
                  const updated = therapies.find(th => th.allocation_id === t.allocation_id);
                  if (updated) {
                    // Update all fields from server response
                    Object.assign(t, updated);
                    // Explicitly set cancelled dates (handle null/undefined/string 'null')
                    t.cancelled_date_from = (updated.cancelled_date_from && updated.cancelled_date_from !== 'null') ? updated.cancelled_date_from : null;
                    t.cancelled_date_to = (updated.cancelled_date_to && updated.cancelled_date_to !== 'null') ? updated.cancelled_date_to : null;
                    t.cancellation_reason = updated.cancellation_reason || '';
                    t.status = updated.status || t.status;
                    // Update status_summary if available
                    if (updated.status_summary) {
                      t.status_summary = updated.status_summary;
                    }
                    // Update UI again with server data
                    renderAll();
                  }
                }
              }).catch(() => {
                // Silently fail - UI already updated with local values
                console.log('Failed to reload therapy data from server, using local values');
              });
            }
          }
        } else {
          alert('Failed: ' + JSON.stringify(j));
        }
      }).catch(()=>alert('Network error'));
    } else {
      // Local cancellation - already updated above, just show message
      alert('Therapy cancelled locally.');
    }
  });

  // Edit therapy (allow editing therapy, slot, and dates per dynamic re-scheduling rules)
  $therapiesTableBody.on('click', '.edit-therapy', function(){ const i=$(this).data('i'); loadTherapyForEdit(i); });
  function loadTherapyForEdit(index){
    const t = addedTherapies[index]; if(!t) return;
    editTherapyIndex = index;
    $('#form-title').text('Edit Therapy');
    
    // Store the slot value to set after slots are populated
    const savedSlotValue = t.slot || '';
    const normalizedSavedSlot = normalizeSlotTime(savedSlotValue);
    
    // Set therapy first
    const opt = new Option(t.therapy_name, t.therapy_code, true, true);
    $therapySelect.append(opt).val(t.therapy_code);
    $therapySelect.prop('disabled', false);
    
    // Store the slot value to restore after slot repopulation
    pendingSlotValue = savedSlotValue;
    
    // Helper function to set slot value after slots are populated
    const setSlotValue = () => {
      if (!savedSlotValue) {
        $slotSelect.prop('disabled', false);
        return;
      }
      
      // Normalize the saved slot value for comparison
      const normalizedSaved = normalizeSlotTime(savedSlotValue);
      let foundValue = null;
      
      // Try to find exact match first (by value attribute)
      let foundOption = $slotSelect.find(`option[value="${savedSlotValue}"]`);
      if (foundOption.length > 0) {
        foundValue = foundOption.val();
      } else {
        // Try to find by normalized value (compare all options)
        $slotSelect.find('option').each(function() {
          const optionValue = $(this).val();
          if (optionValue && normalizeSlotTime(optionValue) === normalizedSaved) {
            foundValue = optionValue;
            return false; // break
          }
        });
      }
      
      // Set the value if found
      if (foundValue) {
        $slotSelect.val(foundValue);
      } else {
        // If no match found, try to set by value anyway (might work if format matches)
        $slotSelect.val(savedSlotValue);
      }
      $slotSelect.prop('disabled', false);
    };
    
    // Populate slots based on therapy, then set the slot value
    updateSlotsForTherapy().then(() => {
      // Wait a bit for DOM to update, then set slot value
      setTimeout(() => {
        setSlotValue();
      }, 50);
    }).catch(() => {
      // If slot population fails, still try to set the value
      setSlotValue();
    });
    
    // Trigger change after a small delay to avoid race condition
    setTimeout(() => {
      $therapySelect.trigger('change');
    }, 100);
    
    $('#ext-int-select').val(t.ext_int||'');
    $fromDate.val(t.from_date||'').prop('disabled', false);
    $toDate.val(t.to_date||'').prop('disabled', false);
    $daysInput.val(t.days||'');
    const usageText =
      (t.usage_text && t.usage_text.trim()) ||
      buildUsageTextFromData(t.usage) ||
      buildUsageTextFromData(t.usage_array);
    $therapyUsageInput.val(usageText);
    $procuredSelect.val(t.procured||'');
    itemGroups = (t.items_groups||[]).map(g=>({ 
      id: Math.random().toString(36).slice(2,9), 
      items: g.items||[], 
      dosage: g.dosage||'', 
      uno: g.uno||'',
      oil_class: g.oil_class || '' // Load Oil Class from item group
    }));
    renderItemGroups();
    $allocateBtn.hide(); $updateBtn.show(); window.scrollTo({top:0, behavior:'smooth'});
  }
  $updateBtn.on('click', function(){
    if (editTherapyIndex === null) { alert('No therapy in edit mode'); return; }
    const t = addedTherapies[editTherapyIndex]; if(!t) return;
    
    // Update local data
    t.ext_int = $('#ext-int-select').val();
    // reflect potential edits
    const selTherapy = $therapySelect.select2('data')[0];
    if (selTherapy && selTherapy.id) {
      t.therapy_code = selTherapy.id;
      t.therapy_name = selTherapy.text;
    }
    t.slot = $slotSelect.val() || '';
    const oldFromDate = t.from_date;
    const oldToDate = t.to_date;
    t.from_date = $fromDate.val() || t.from_date;
    t.to_date = $toDate.val() || t.to_date;
    
    // Adjust cancelled dates if they fall outside the new date range
    if (t.cancelled_date_from && t.cancelled_date_to && 
        t.cancelled_date_from !== 'null' && t.cancelled_date_to !== 'null') {
      const cancelledFrom = new Date(t.cancelled_date_from + 'T00:00:00');
      const cancelledTo = new Date(t.cancelled_date_to + 'T00:00:00');
      const newFrom = new Date(t.from_date + 'T00:00:00');
      const newTo = new Date(t.to_date + 'T00:00:00');
      
      // If cancelled range is completely outside new date range, clear it
      if (cancelledTo < newFrom || cancelledFrom > newTo) {
        t.cancelled_date_from = null;
        t.cancelled_date_to = null;
        t.cancellation_reason = '';
      } else {
        // Adjust cancelled range to fit within new date range
        if (cancelledFrom < newFrom) {
          t.cancelled_date_from = t.from_date;
        }
        if (cancelledTo > newTo) {
          t.cancelled_date_to = t.to_date;
        }
      }
    }
    
    // Recalculate days from the updated dates
    if (t.from_date && t.to_date) {
      const fd = new Date(t.from_date);
      const td = new Date(t.to_date);
      if (fd <= td) {
        t.days = Math.ceil((td.getTime() - fd.getTime()) / (1000 * 60 * 60 * 24)) + 1;
      } else {
        t.days = '';
      }
    } else {
      t.days = '';
    }
    const updatedUsageText = ($therapyUsageInput.val() || '').trim();
    const updatedUsageArray = parseUsageInput(updatedUsageText);
    t.usage = updatedUsageText;
    t.usage_array = updatedUsageArray;
    t.usage_text = updatedUsageText;
    t.procured = $procuredSelect.val()||'';
    t.items_groups = itemGroups.map(g=>({
      items: g.items||[], 
      dosage: g.dosage, 
      uno: g.uno,
      oil_class: g.oil_class || '' // Include Oil Class in item group
    }));
    
    // Send update to server if therapy has allocation_id
    if (t.allocation_id) {
      const updatePayload = {
        allocation_id: t.allocation_id,
        therapy_name: t.therapy_name,
        slot: t.slot,
        from_date: t.from_date,
        to_date: t.to_date,
        days: t.days, // Include updated days in payload
        ext_int: t.ext_int,
        usage: updatedUsageText,
        usage_array: updatedUsageArray,
        items_groups: t.items_groups.map(g => ({ 
          items: g.items || [], 
          dosage: g.dosage, 
          uno: g.uno,
          usage: g.usage || (g.usage_array ? g.usage_array.join(', ') : ''),
          usage_array: g.usage_array || (g.usage ? g.usage.split(',').map(u => u.trim()) : []),
          oil_class: g.oil_class || '' // Include Oil Class in item group
        })),
        usage_should: t.usage_should || '', // Therapy-level usage
        procured_from: t.procured,
        notes: t.notes || ''
      };
      
      fetch(API_URL + '?action=update_therapy', {
        method:'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify(updatePayload)
      }).then(r => r.json()).then(j => {
        if (j.status === 'ok') {
          alert('Therapy updated successfully on server.');
          resetFormState();
          
          // Reload therapy data from server to get accurate days and other fields
          if (t.allocation_id && selectedPatient) {
            const patientRegNo = t.patient_reg_no || selectedPatient.pat_reg_no || selectedPatient.pat_op_reg_no;
            if (patientRegNo) {
              ajax({action:'patient_therapies', patient_reg_no: patientRegNo}).then(therapies => {
                if (therapies && Array.isArray(therapies)) {
                  const updated = therapies.find(th => th.allocation_id === t.allocation_id);
                  if (updated) {
                    // Update all fields from server response, including days
                    Object.assign(t, updated);
                    // Ensure days is set correctly
                    if (updated.days) {
                      t.days = updated.days;
                    }
                  }
                }
                renderAll();
              }).catch(() => {
                // If reload fails, use local values
                renderAll();
              });
            } else {
              renderAll();
            }
          } else {
            renderAll();
          }
        } else {
          alert('Failed to update therapy: ' + JSON.stringify(j));
          renderAll();
        }
      }).catch(() => {
        alert('Network error. Therapy updated locally only.');
        resetFormState(); 
        renderAll();
      });
    } else {
      // Local update only (for unsaved therapies)
      alert('Therapy updated locally.');
      resetFormState(); 
      renderAll();
    }
  });

  function resetFormState(){
    editTherapyIndex = null; 
    $('#form-title').text('Create New Therapy');
    
    // Clear all form fields completely
    $therapySelect.val(null).trigger('change').prop('disabled', false);
    $slotSelect.val('').prop('disabled', false);
    $('#ext-int-select').val(''); 
    
    // Clear date fields explicitly
    $fromDate.val('').prop('value', '').prop('disabled', false); 
    $toDate.val('').prop('value', '').prop('disabled', false); 
    $daysInput.val('').prop('value', '');
    
    // Clear usage field explicitly
    $therapyUsageInput.val('').prop('value', ''); 
    
    // Clear procured select - handle both regular select and select2
    if ($procuredSelect.hasClass('select2-hidden-accessible')) {
      $procuredSelect.val('').trigger('change');
    } else {
      $procuredSelect.val('').prop('value', '');
    }
    
    // Clear item builder fields
    if ($itemBuilder.hasClass('select2-hidden-accessible')) {
      $itemBuilder.val(null).trigger('change');
    } else {
      $itemBuilder.val(null);
    }
    $('#item-builder-dosage').val('').prop('value', '');
    $('#item-builder-uno').val('').prop('value', '');
    $itemBuilderOilClass.val('').prop('value', '');
    if ($itemBuilderOilClass.hasClass('select2-hidden-accessible')) {
      $itemBuilderOilClass.trigger('change');
    }
    
    // Clear item groups
    itemGroups = []; 
    renderItemGroups();
    
    // Reset buttons
    $allocateBtn.show(); 
    $updateBtn.hide();
    
    // Clear any pending slot value
    pendingSlotValue = null;
  }

  // Helper function to format date as DD/MM/YYYY
  function formatDate(dateStr) {
    if (!dateStr) return '';
    const date = new Date(dateStr + 'T00:00:00');
    if (isNaN(date.getTime())) return dateStr;
    const day = String(date.getDate()).padStart(2, '0');
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const year = date.getFullYear();
    return `${day}/${month}/${year}`;
  }

  // Helper function to generate date range (avoiding timezone issues)
  function getDateRange(fromDate, toDate) {
    const dates = [];
    if (!fromDate || !toDate) return dates;
    
    // Parse dates directly without timezone conversion
    const startParts = fromDate.split('-');
    const endParts = toDate.split('-');
    if (startParts.length !== 3 || endParts.length !== 3) return dates;
    
    const start = new Date(parseInt(startParts[0]), parseInt(startParts[1]) - 1, parseInt(startParts[2]));
    const end = new Date(parseInt(endParts[0]), parseInt(endParts[1]) - 1, parseInt(endParts[2]));
    
    const current = new Date(start);
    while (current <= end) {
      // Format as YYYY-MM-DD without timezone conversion
      const year = current.getFullYear();
      const month = String(current.getMonth() + 1).padStart(2, '0');
      const day = String(current.getDate()).padStart(2, '0');
      dates.push(`${year}-${month}-${day}`);
      current.setDate(current.getDate() + 1);
    }
    return dates;
  }

  // Resume modal handlers
  $therapiesTableBody.on('click', '.resume-therapy', function(){ const i=$(this).data('i'); openResumeModal(i); });
  
  function openResumeModal(index){
    resumingTherapyIndex = index; 
    const t = addedTherapies[index]; 
    if(!t) return;
    
    // Get fresh data from the therapy object (ensure we have latest cancelled dates)
    const cancelledFrom = t.cancelled_date_from;
    const cancelledTo = t.cancelled_date_to;
    
    $('#resume-modal-info').html(`<strong>Therapy:</strong> ${t.therapy_name || 'N/A'}<br/><strong>Cancelled Range:</strong> ${formatDate(cancelledFrom) || '—'} → ${formatDate(cancelledTo) || '—'}`);
    
    const $datesList = $('#resume-dates-list');
    $datesList.empty();
    $datesList.html('<p style="color: #666; padding: 16px; text-align: center;">Loading cancelled dates...</p>');
    $resumeModal.show();
    
    // Check if cancelled dates exist and are valid
    if (!cancelledFrom || !cancelledTo || cancelledFrom === 'null' || cancelledTo === 'null') {
      $datesList.html('<p style="color: #666; padding: 16px; text-align: center;">No cancelled dates found.</p>');
      return;
    }
    
    const cancelledDates = getDateRange(cancelledFrom, cancelledTo);
    
    if (cancelledDates.length === 0) {
      $datesList.html('<p style="color: #666; padding: 16px; text-align: center;">No cancelled dates found.</p>');
      return;
    }
    
    // If we have an allocation_id, fetch booking statuses to show only dates that are still cancelled
    if (t.allocation_id) {
      ajax({action:'allocation_status', allocation_id: t.allocation_id}).then(data => {
        const bookings = data.bookings || [];
        // Create a map of date -> booking status
        const bookingStatusMap = {};
        bookings.forEach(b => {
          bookingStatusMap[b.date] = b.status || b.display_status || 'draft';
        });
        
        // Filter to show only dates that are still cancelled
        const stillCancelledDates = cancelledDates.filter(date => {
          const status = bookingStatusMap[date];
          // Show date if it's cancelled or if we don't have booking info for it
          return status === 'cancelled' || !status;
        });
        
        if (stillCancelledDates.length === 0) {
          $datesList.html('<p style="color: #666; padding: 16px; text-align: center;">No cancelled dates found (all dates have been resumed).</p>');
          return;
        }
        
        $datesList.empty();
        stillCancelledDates.forEach(date => {
          const $dateItem = $(`
            <div style="display: flex; justify-content: space-between; align-items: center; padding: 12px; margin-bottom: 8px; background: #f8f9fa; border: 1px solid #dee2e6; border-radius: 6px;">
              <div style="font-weight: 500; color: #333;">
                <i class="fas fa-calendar-alt" style="margin-right: 8px; color: #6c757d;"></i>
                ${formatDate(date)}
              </div>
              <button class="btn btn-sm btn-success resume-date-btn" data-date="${date}" style="min-width: 100px;">
                <i class="fas fa-play"></i> Resume
              </button>
            </div>
          `);
          $datesList.append($dateItem);
        });
      }).catch(() => {
        // Fallback: show all dates in cancelled range if we can't fetch booking statuses
        $datesList.empty();
        cancelledDates.forEach(date => {
          const $dateItem = $(`
            <div style="display: flex; justify-content: space-between; align-items: center; padding: 12px; margin-bottom: 8px; background: #f8f9fa; border: 1px solid #dee2e6; border-radius: 6px;">
              <div style="font-weight: 500; color: #333;">
                <i class="fas fa-calendar-alt" style="margin-right: 8px; color: #6c757d;"></i>
                ${formatDate(date)}
              </div>
              <button class="btn btn-sm btn-success resume-date-btn" data-date="${date}" style="min-width: 100px;">
                <i class="fas fa-play"></i> Resume
              </button>
            </div>
          `);
          $datesList.append($dateItem);
        });
      });
    } else {
      // No allocation_id - show all dates in cancelled range
      $datesList.empty();
      cancelledDates.forEach(date => {
        const $dateItem = $(`
          <div style="display: flex; justify-content: space-between; align-items: center; padding: 12px; margin-bottom: 8px; background: #f8f9fa; border: 1px solid #dee2e6; border-radius: 6px;">
            <div style="font-weight: 500; color: #333;">
              <i class="fas fa-calendar-alt" style="margin-right: 8px; color: #6c757d;"></i>
              ${formatDate(date)}
            </div>
            <button class="btn btn-sm btn-success resume-date-btn" data-date="${date}" style="min-width: 100px;">
              <i class="fas fa-play"></i> Resume
            </button>
          </div>
        `);
        $datesList.append($dateItem);
      });
    }
  }
  
  // Handle individual date resume
  $(document).on('click', '.resume-date-btn', function(){
    const date = $(this).data('date');
    if (!date || resumingTherapyIndex === null) return;
    
    const therapy = addedTherapies[resumingTherapyIndex];
    if (!therapy) return;
    
    if (!confirm(`Are you sure you want to resume therapy for ${formatDate(date)}?`)) {
      return;
    }
    
    // IMMEDIATELY update local data BEFORE server call
    // Update status_summary optimistically to reflect the resume action
    if (!therapy.status_summary) {
      therapy.status_summary = {};
    }
    
    // Decrease cancelled count and increase draft count optimistically
    if (therapy.status_summary.cancelled && therapy.status_summary.cancelled > 0) {
      therapy.status_summary.cancelled = (therapy.status_summary.cancelled || 0) - 1;
      if (therapy.status_summary.cancelled === 0) {
        delete therapy.status_summary.cancelled;
      }
    }
    // Increase draft count (the resumed booking will be draft)
    therapy.status_summary.draft = (therapy.status_summary.draft || 0) + 1;
    
    // For middle dates, we don't update cancelled_date_from/to optimistically
    // We wait for server response to get the correct updated range
    if (therapy.cancelled_date_from === date && therapy.cancelled_date_to === date) {
      // Resuming the only cancelled date - clear cancellation
      therapy.status = 'draft';
      therapy.cancelled_date_from = null;
      therapy.cancelled_date_to = null;
      therapy.cancellation_reason = '';
      renderAll();
    } else if (therapy.cancelled_date_from === date) {
      // Resuming from start - move start date forward
      const nextDate = new Date(date);
      nextDate.setDate(nextDate.getDate() + 1);
      therapy.cancelled_date_from = nextDate.toISOString().split('T')[0];
      renderAll();
    } else if (therapy.cancelled_date_to === date) {
      // Resuming from end - move end date backward
      const prevDate = new Date(date);
      prevDate.setDate(prevDate.getDate() - 1);
      therapy.cancelled_date_to = prevDate.toISOString().split('T')[0];
      renderAll();
    } else {
      // Resuming a date in the middle - DON'T update cancelled_date_from/to optimistically
      // Keep the range unchanged and wait for server response
      // The server will keep the range unchanged, only resuming the specific date's bookings
      // We'll update the UI after getting the server response
      const dateObj = new Date(date + 'T00:00:00');
      const fromObj = new Date(therapy.cancelled_date_from + 'T00:00:00');
      const toObj = new Date(therapy.cancelled_date_to + 'T00:00:00');
      
      if (dateObj > fromObj && dateObj < toObj) {
        // Middle date - don't update cancelled_date_from/to, wait for server
        // Just update status_summary optimistically and render
        renderAll();
      } else if (dateObj <= fromObj) {
        // Resumed date is at or before the start - clear cancellation entirely
        therapy.cancelled_date_from = null;
        therapy.cancelled_date_to = null;
        therapy.cancellation_reason = '';
        therapy.status = 'draft';
        renderAll();
      }
    }
    
    // Update resume modal if still open - check if there are still cancelled dates
    if (resumingTherapyIndex !== null) {
      const currentTherapy = addedTherapies[resumingTherapyIndex];
      if (currentTherapy && currentTherapy.cancelled_date_from && currentTherapy.cancelled_date_to) {
        // Still has cancelled dates - refresh the modal
        setTimeout(() => {
          openResumeModal(resumingTherapyIndex);
        }, 50);
      } else {
        // No more cancelled dates - close modal
        $resumeModal.hide();
        resumingTherapyIndex = null;
      }
    }
    
    alert('Therapy resumed successfully for ' + formatDate(date) + '.');
    
    if (therapy.allocation_id) {
      // Server-side resume (happens in background)
      fetch(API_URL + '?action=resume_therapy', {
        method:'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({ allocation_id: therapy.allocation_id, resume_date: date })
      }).then(r => r.json()).then(j => {
        if (j.status === 'ok') {
          // UI already updated above, alert already shown, server sync will happen in background
          
          // Then reload from server to get accurate updated cancelled dates and status_summary (in background)
          if (selectedPatient && therapy.allocation_id) {
            const patientRegNo = therapy.patient_reg_no || selectedPatient.pat_reg_no || selectedPatient.pat_op_reg_no;
            if (patientRegNo) {
              ajax({action:'patient_therapies', patient_reg_no: patientRegNo}).then(therapies => {
                if (therapies && Array.isArray(therapies)) {
                  const updated = therapies.find(th => th.allocation_id === therapy.allocation_id);
                  if (updated) {
                    // Update all fields from server response
                    Object.assign(therapy, updated);
                    // Explicitly set cancelled dates (handle null/undefined/string 'null')
                    therapy.cancelled_date_from = (updated.cancelled_date_from && updated.cancelled_date_from !== 'null') ? updated.cancelled_date_from : null;
                    therapy.cancelled_date_to = (updated.cancelled_date_to && updated.cancelled_date_to !== 'null') ? updated.cancelled_date_to : null;
                    therapy.cancellation_reason = updated.cancellation_reason || '';
                    therapy.status = updated.status || therapy.status;
                    // Update status_summary if available
                    if (updated.status_summary) {
                      therapy.status_summary = updated.status_summary;
                    }
                  }
                }
                // Update the table with server data
                renderAll();
                
                // Reload the modal to show updated dates (with a small delay to ensure renderAll completes)
                setTimeout(() => {
                  const currentTherapy = addedTherapies[resumingTherapyIndex];
                  if (currentTherapy && currentTherapy.cancelled_date_from && currentTherapy.cancelled_date_to && 
                      currentTherapy.cancelled_date_from !== 'null' && currentTherapy.cancelled_date_to !== 'null') {
                    openResumeModal(resumingTherapyIndex);
                  } else {
                    $resumeModal.hide();
                    resumingTherapyIndex = null;
                  }
                }, 100);
              }).catch(() => {
                // Silently fail - UI already updated with local values
                console.log('Failed to reload therapy data from server, using local values');
                // Close modal if no cancelled dates remain
                setTimeout(() => {
                  const currentTherapy = addedTherapies[resumingTherapyIndex];
                  if (currentTherapy && currentTherapy.cancelled_date_from && currentTherapy.cancelled_date_to &&
                      currentTherapy.cancelled_date_from !== 'null' && currentTherapy.cancelled_date_to !== 'null') {
                    openResumeModal(resumingTherapyIndex);
                  } else {
                    $resumeModal.hide();
                    resumingTherapyIndex = null;
                  }
                }, 100);
              });
            } else {
              // No patient reg number - close modal and refresh
              $resumeModal.hide();
              resumingTherapyIndex = null;
            }
          } else {
            // No patient selected or local therapy - close modal
            $resumeModal.hide();
            resumingTherapyIndex = null;
          }
        } else {
          alert('Failed: ' + (j.error || JSON.stringify(j)));
        }
      }).catch(()=>alert('Network error'));
    } else {
      // Local resume - data already updated above, just show message and handle modal
      alert('Therapy resumed successfully for ' + formatDate(date) + '.');
      
      // Check if there are still cancelled dates to show in modal
      if (therapy.cancelled_date_from && therapy.cancelled_date_to && 
          therapy.cancelled_date_from !== 'null' && therapy.cancelled_date_to !== 'null') {
        openResumeModal(resumingTherapyIndex);
      } else {
        $resumeModal.hide();
        resumingTherapyIndex = null;
      }
    }
  });
  
  $resumeCloseBtn.on('click', function(){ $resumeModal.hide(); resumingTherapyIndex = null; });

  // export JSON
  $('#export-json').on('click', function(){
    const patient = $patientSelect.val() || '';
    const payload = { patient_reg_no: patient, therapies: addedTherapies, bookings };
    const blob = new Blob([JSON.stringify(payload,null,2)], {type:'application/json'});
    const url = URL.createObjectURL(blob);
    const a=document.createElement('a'); a.href=url; a.download=(patient?patient+'-':'therapies-')+(new Date().toISOString().slice(0,10))+'.json'; document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url);
  });

  // initial render
  renderAll();

  // Initialize UnitNo dropdown
  loadUnitNumbers();

  // Clear form button
  $('#clear-form').on('click', function(){
    resetFormState();
  });

  // expose for debug
  window._therapyApp = { addedTherapies, bookings, itemGroups, renderAll };
});