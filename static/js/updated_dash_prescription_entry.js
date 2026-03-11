$(function () {
  console.log('Prescription Entry JS v4.6 - DOA label updated');
  // --- config/fallbacks ---
  const API_URL = window.location.pathname;
  const FALLBACK_PROCURED = [{ name: 'IP Pharmacy' }, { name: 'Kashaya room' }];

  // --- helpers ---
  function ajax(params) {
    const url = API_URL + '?' + $.param(params);
    return fetch(url).then(r => {
      if (!r.ok) throw new Error('Network error (' + r.status + ')');
      const contentType = r.headers.get('content-type');
      if (contentType && contentType.includes('application/json')) {
        return r.json();
      } else {
        throw new Error('Session expired or server error. Please refresh the page.');
      }
    });
  }
  function esc(s) { return String(s || ''); }
  // Format date as DD/MM/YYYY
  function formatDate(dateStr) {
    if (!dateStr) return '';
    try {
      const date = new Date(dateStr + 'T00:00:00');
      if (isNaN(date.getTime())) return dateStr; // Return original if invalid
      const day = String(date.getDate()).padStart(2, '0');
      const month = String(date.getMonth() + 1).padStart(2, '0');
      const year = date.getFullYear();
      return `${day}/${month}/${year}`;
    } catch (e) {
      return dateStr; // Return original if error
    }
  }

  function getDateRange(from, to) { const out = []; let cur = new Date(from + 'T00:00:00'), end = new Date(to + 'T00:00:00'); while (cur <= end) { out.push(cur.toISOString().slice(0, 10)); cur.setDate(cur.getDate() + 1); } return out; }
  function getCookie(name) { let v = document.cookie.match('(^|;)\\s*' + name + '\\s*=\\s*([^;]+)'); return v ? v.pop() : ''; }

  // Load UnitNo options from master table
  function loadUnitNumbers() {
    fetch('/unit_numbers/')
      .then(response => {
        const ct = response.headers.get('content-type');
        return (ct && ct.includes('json')) ? response.json() : Promise.reject('Invalid response');
      })
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
  const $hdrName = $('#hdr-pat-name'), $hdrMeta = $('#hdr-pat-meta'), $hdrVip = $('#hdr-pat-vip'), $hdrIp = $('#hdr-pat-ip'), $hdrUnique = $('#hdr-pat-unique'), $hdrType = $('#hdr-pat-type');
  const $fromDate = $('#from-date-input'), $toDate = $('#to-date-input'), $daysInput = $('#days-input');
  const $procuredSelect = $('#procured-from-select'); // Keep for backward compatibility, but use item-builder-procured-from for new groups
  const $itemBuilderProcuredFrom = $('#item-builder-procured-from');
  const $scopeSelect = $('#scope-select');
  const $commonUsageSelect = $('#common-usage-select');
  let usageSelectionOrder = []; // Track selection order for usage field

  // Flag to prevent reordering during unselect operations
  let isUnselecting = false;

  // Function to reorder selected tags in the DOM to match selection order (global function)
  function reorderUsageTags() {
    // Don't reorder if we're in the middle of an unselect operation
    if (isUnselecting) return;

    // Use requestAnimationFrame for smoother updates
    requestAnimationFrame(() => {
      setTimeout(() => {
        // Double-check flag after timeout
        if (isUnselecting) return;

        const $select2Container = $commonUsageSelect.next('.select2-container');
        if (!$select2Container.length) return;

        const $choicesContainer = $select2Container.find('.select2-selection__rendered');
        if (!$choicesContainer.length) return;

        const $tags = $choicesContainer.find('.select2-selection__choice');
        if ($tags.length === 0) return;

        const currentValues = $commonUsageSelect.val() || [];
        const orderedValues = usageSelectionOrder.filter(val => currentValues.indexOf(val) !== -1);

        // If no reordering needed, return early
        if (orderedValues.length <= 1) return;

        // Create a map of value to DOM element by matching text content
        const tagMap = {};
        $tags.each(function () {
          const $tag = $(this);
          // Get the text content (removing the X button text)
          const tagText = $tag.clone().find('.select2-selection__choice__remove').remove().end().text().trim();

          // Find matching value by comparing with option text
          for (let i = 0; i < orderedValues.length; i++) {
            const val = orderedValues[i];
            const $option = $commonUsageSelect.find(`option[value="${val}"]`);
            const optionText = $option.text().trim();
            if (tagText === optionText || tagText === val) {
              tagMap[val] = $tag;
              break;
            }
          }
        });

        // Reorder tags based on selection order by moving them in DOM
        // Only reorder if we have all tags mapped correctly
        if (Object.keys(tagMap).length === orderedValues.length) {
          orderedValues.forEach(val => {
            if (tagMap[val]) {
              // Use a more gentle approach that preserves event handlers
              const $tag = tagMap[val];
              if ($tag.parent()[0] !== $choicesContainer[0]) {
                $tag.appendTo($choicesContainer);
              } else {
                // If already in the right container, just move to correct position
                const currentIndex = $tag.index();
                const targetIndex = orderedValues.indexOf(val);
                if (currentIndex !== targetIndex) {
                  if (targetIndex === 0) {
                    $tag.prependTo($choicesContainer);
                  } else {
                    const $prevTag = tagMap[orderedValues[targetIndex - 1]];
                    if ($prevTag && $prevTag.length) {
                      $tag.insertAfter($prevTag);
                    }
                  }
                }
              }
            }
          });
        }
      }, 10);
    });
  }
  const $itemBuilder = $('#item-builder-select'), $itemGroupsList = $('#item-groups-list');
  const $itemBuilderOilClass = $('#item-builder-oil-class');
  const $allocateBtn = $('#allocate-prescription-btn'), $updateBtn = $('#update-prescription-btn'), $clearBtn = $('#clear-form');
  const $prescriptionsTableBody = $('#prescriptions-table-body');

  const $cancelModal = $('#cancel-modal-backdrop'), $cancelFrom = $('#cancel-from'), $cancelTo = $('#cancel-to'), $cancelReason = $('#cancel-reason');
  const $cancelSubmitBtn = $('#cancel-submit'), $cancelCloseBtn = $('#cancel-modal-close'), $cancelModalInfo = $('#cancel-modal-info');

  const $resumeModal = $('#resume-modal-backdrop');
  const $resumeCloseBtn = $('#resume-modal-close'), $resumeModalInfo = $('#resume-modal-info');

  // --- Confirmation Modal Logic ---
  const $confirmModal = $('#confirmation-modal-backdrop');
  const $confirmTitle = $('#confirmation-modal-title');
  const $confirmMessage = $('#confirmation-modal-message');
  const $confirmBtn = $('#confirmation-modal-confirm');
  const $confirmCancel = $('#confirmation-modal-cancel');
  let onConfirmAction = null;

  function showConfirm(title, message, btnText, callback) {
    $confirmTitle.text(title);
    $confirmMessage.html(message.replace(/\n/g, '<br>'));
    $confirmBtn.text(btnText);
    onConfirmAction = callback;
    $confirmModal.show();
  }

  $confirmCancel.on('click', function () {
    $confirmModal.hide();
    onConfirmAction = null;
  });

  $confirmBtn.on('click', function () {
    if (onConfirmAction) onConfirmAction();
    $confirmModal.hide();
    onConfirmAction = null;
  });

  // Set today's date as default for From Date field
  if (!$fromDate.val()) {
    const today = new Date().toISOString().split('T')[0];
    $fromDate.val(today);
  }

  // --- state ---
  let itemGroups = [];
  let addedPrescriptions = [];
  let editPrescriptionIndex = null;
  let cancelingPrescriptionIndex = null;
  let resumingPrescriptionIndex = null;
  let selectedPatient = null;
  let prescriptionActionById = {};

  // Track the last action performed so rows can be color-coded
  // This in-memory dict is only used as an immediate-session override (e.g. right after an
  // edit action so the row turns yellow before the page re-fetches from the DB).
  function rememberPrescriptionAction(id, action) {
    if (!id) return;
    const key = String(id);
    prescriptionActionById[key] = action;
  }

  // Derive the row colour action from DB-persisted timestamps.
  // Priority: cancelled_at > resumed_at > updated_today > created_today > default(added)
  function derivePrescriptionActionFromDB(p) {
    const now = new Date();
    const todayStr = now.getFullYear() + '-' +
      String(now.getMonth() + 1).padStart(2, '0') + '-' +
      String(now.getDate()).padStart(2, '0');

    function dateOf(ts) {
      if (!ts || ts === 'null') return null;
      return String(ts).slice(0, 10);
    }

    const updatedAtDate = dateOf(p.updated_at);
    const createdAtDate = dateOf(p.created_at);

    // 1. Cancelled: cancelled_at is set
    if (p.cancelled_at && p.cancelled_at !== 'null') {
      // Unless it was resumed AFTER being cancelled
      if (p.resumed_at && p.resumed_at !== 'null' && p.resumed_at >= p.cancelled_at) {
        return 'resumed';
      }
      return 'cancelled';
    }

    // 2. Resumed (has resumed_at and no active cancellation)
    if (p.resumed_at && p.resumed_at !== 'null') {
      return 'resumed';
    }

    // 3. Updated today: Compare timestamps with a threshold
    if (updatedAtDate === todayStr && p.updated_at && p.created_at) {
      const upTs = new Date(p.updated_at).getTime();
      const crTs = new Date(p.created_at).getTime();
      if (!isNaN(upTs) && !isNaN(crTs) && (upTs - crTs) > 10000) { // 10 sec threshold
        return 'updated';
      }
    }

    // 4. Newly created today or Pre-existing
    return 'added';
  }

  function decoratePrescriptionList(list) {
    console.log('Decorating prescription list. IDs:', (list || []).map(p => p.id));
    return (list || []).map(p => {
      // Check in-memory session override first
      const key1 = p.allocation_id ? String(p.allocation_id) : null;
      const key2 = p.id ? String(p.id) : null;
      const sessionOverride = (key1 && prescriptionActionById[key1]) ||
        (key2 && prescriptionActionById[key2]) || '';

      // DB-derived action (persistent, survives navigation)
      const dbDerived = derivePrescriptionActionFromDB(p);

      // Session override wins for current session; DB-derived is authoritative on reload
      const action = sessionOverride || dbDerived;
      return { ...p, last_action: action };
    });
  }

  // Patient search with auto-fill functionality
  let searchTimeout;
  let initialPatientsLoaded = false;

  // Tab switching functionality
  $('.search-tab-btn').on('click', function () {
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
  $('#header-patient-select').on('focus', function () {
    const query = $(this).val().trim();
    // If search box is empty, show 10 active patients
    if (query.length === 0 && !initialPatientsLoaded) {
      searchPatients('', true); // true = initial load (show 10 patients)
      initialPatientsLoaded = true;
    }
  });

  $('#header-patient-select').on('input', function () {
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
  $('#search-room-btn').on('click', function () {
    const roomNumber = $('#header-room-search').val().trim();
    if (!roomNumber) {
      alert('Please enter a room number');
      return;
    }
    searchPatientsByRoom(roomNumber);
  });

  // Allow Enter key to trigger room search
  $('#header-room-search').on('keypress', function (e) {
    if (e.which === 13) {
      e.preventDefault();
      $('#search-room-btn').click();
    }
  });

  // Clear room search
  $('#clear-room-btn').on('click', function () {
    $('#header-room-search').val('');
    $('#search-results').hide();
  });

  // Function to search patients by room number
  function searchPatientsByRoom(roomNumber) {
    $('#search-results').html('<div style="padding:10px;color:#666;">Searching...</div>').show();

    fetch('/authentication/api/search-patients-by-room/?room=' + encodeURIComponent(roomNumber))
      .then(response => {
        const ct = response.headers.get('content-type');
        return (ct && ct.includes('json')) ? response.json() : Promise.reject('Invalid response (Session Timeout?)');
      })
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
      .then(response => {
        const ct = response.headers.get('content-type');
        return (ct && ct.includes('json')) ? response.json() : Promise.reject('Invalid response (Session Timeout?)');
      })
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
  $(document).on('click', '.search-result-item', function () {
    const regNo = $(this).data('reg-no');
    loadPatientDetails(regNo);
  });

  // Hide search results when clicking outside
  $(document).on('click', function (e) {
    if (!$(e.target).closest('#header-patient-select, #header-room-search, #search-results, #search-room-btn').length) {
      $('#search-results').hide();
    }
  });

  function loadPatientDetails(regNo) {
    $('#search-results').hide();

    fetch('/get-patient-details/?pat_reg_no=' + encodeURIComponent(regNo))
      .then(response => {
        const ct = response.headers.get('content-type');
        return (ct && ct.includes('json')) ? response.json() : Promise.reject('Invalid response (Session Timeout?)');
      })
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
    const doa = patient.doa || '—';
    const team = patient.doctor_team || '—';

    $('#hdr-pat-reg').html(`<strong style="font-weight: bold; color: var(--primary);">${regNo}</strong>`);
    $('#hdr-pat-room').html(`<strong style="font-weight: bold; color: var(--primary);">${room}</strong>`);
    $('#hdr-pat-age').html(`<strong style="font-weight: bold; color: var(--primary);">${age}</strong>`);
    $('#hdr-pat-gender').html(`<strong style="font-weight: bold; color: var(--primary);">${gender}</strong>`);
    $('#hdr-pat-type').html(`<strong style="font-weight: bold; color: var(--primary);">${type}</strong>`);
    $('#hdr-pat-doa').html(`<strong style="font-weight: bold; color: var(--primary);">${doa}</strong>`);
    $('#hdr-pat-team').html(`<strong style="font-weight: bold; color: var(--primary);">${team}</strong>`);
  }

  function populatePatientInfo(patient) {
    // Clear previous patient's data first
    addedPrescriptions = [];
    itemGroups = [];
    editPrescriptionIndex = null;
    cancelingPrescriptionIndex = null;
    resumingPrescriptionIndex = null;
    editingGroupId = null; // Clear editing group ID
    editingGroupIndex = null; // Clear editing group index
    // Clear remembered actions when switching patients to avoid stale data
    prescriptionActionById = {};

    // Reset form state
    resetFormState();

    // Determine correct registration number based on patient type
    // For IP patients: use pat_reg_no (not pat_op_reg_no)
    // For OP patients: use pat_op_reg_no if available, otherwise pat_reg_no
    const patientType = patient.patient_type ||
      (patient.pat_reg_no && patient.pat_reg_no.toString().replace(/\D/g, '').length === 5 ? 'OP' : 'IP');
    const patientRegNo = patientType === 'IP'
      ? patient.pat_reg_no
      : (patient.pat_op_reg_no || patient.pat_reg_no);

    $('#header-patient-select').val(patientRegNo);
    // Make patient name bold/highlighted
    $('#hdr-pat-name').html(`<strong style="font-weight: bold; color: var(--primary);">${patient.pat_name || 'Unknown'}</strong>`);
    updatePatientAvatar(patient);

    // Load patient prescriptions
    ajax({ action: 'patient_prescriptions', patient_reg_no: patientRegNo }).then(list => {
      addedPrescriptions = decoratePrescriptionList(list || []);
      renderAll();
    }).catch(() => {
      addedPrescriptions = [];
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
    $('#hdr-pat-doa').html('—');
    $('#hdr-pat-team').html('—');
    addedPrescriptions = [];
    renderAll();
  }

  // Clear button event handler
  $('#clear-patient-btn').on('click', function () {
    clearPatientSelection();
    $('#search-results').hide();
  });

  // populate masters with fallback
  function populateMasters() {
    ajax({ action: 'masters', type: 'procured' }).then(list => {
      $procuredSelect.empty().append('<option value="">-- Select Source --</option>');
      $itemBuilderProcuredFrom.empty().append('<option value="">-- Select Source --</option>');
      (list || FALLBACK_PROCURED).forEach(p => {
        $procuredSelect.append(new Option(p.name, p.name));
        $itemBuilderProcuredFrom.append(new Option(p.name, p.name));
      });
    }).catch(() => {
      $procuredSelect.empty().append('<option value="">-- Select Source --</option>');
      $itemBuilderProcuredFrom.empty().append('<option value="">-- Select Source --</option>');
      FALLBACK_PROCURED.forEach(p => {
        $procuredSelect.append(new Option(p.name, p.name));
        $itemBuilderProcuredFrom.append(new Option(p.name, p.name));
      });
    });
    ajax({ action: 'masters', type: 'prescriptionscope' }).then(list => { $scopeSelect.empty().append('<option value="">-- Select --</option>'); (list || []).forEach(x => $scopeSelect.append(new Option(x.name, x.name))); }).catch(() => { $scopeSelect.empty().append('<option value="">-- Select --</option>'); });
    ajax({ action: 'masters', type: 'prescriptionusage' }).then(list => {
      const $u = $commonUsageSelect;
      $u.empty();
      usageSelectionOrder = []; // Reset selection order
      (list || []).forEach(x => $u.append(new Option(x.name, x.name)));
      // Initialize Select2 for multiselect
      if (!$u.hasClass('select2-hidden-accessible')) {
        $u.select2({
          placeholder: 'Select Usage (multiple)',
          allowClear: true,
          width: '100%',
          closeOnSelect: false
        });
      }

      // Track selection order and reorder display immediately
      $u.on('select2:select', function (e) {
        const selectedValue = e.params.data.id;
        if (usageSelectionOrder.indexOf(selectedValue) === -1) {
          usageSelectionOrder.push(selectedValue);
        }
        // Reorder tags after Select2 has rendered the new tag
        // Use a single delayed call to avoid race conditions
        setTimeout(() => {
          if (!isUnselecting) {
            reorderUsageTags();
          }
        }, 100);
      });

      $u.on('select2:unselect', function (e) {
        // Set flag to prevent reordering during unselect
        isUnselecting = true;

        const unselectedValue = e.params.data.id;
        const index = usageSelectionOrder.indexOf(unselectedValue);
        if (index > -1) {
          usageSelectionOrder.splice(index, 1);
        }

        // Clear flag after a short delay to allow Select2 to complete the unselect
        setTimeout(() => {
          isUnselecting = false;
          // Reorder remaining tags after unselect is complete
          reorderUsageTags();
        }, 100);
      });

      // Also reorder when values are set programmatically (like when loading for edit)
      $u.on('change', function () {
        if (!isUnselecting) {
          setTimeout(() => {
            if (!isUnselecting) {
              reorderUsageTags();
            }
          }, 100);
        }
      });

      // Reorder after Select2 closes to ensure correct order (but not on open to avoid interference)
      $u.on('select2:close', function () {
        if (!isUnselecting) {
          setTimeout(() => {
            if (!isUnselecting) {
              reorderUsageTags();
            }
          }, 50);
        }
      });

      // Use MutationObserver to watch for DOM changes and reorder automatically
      // But be careful not to interfere with Select2's native unselect behavior
      setTimeout(() => {
        const $select2Container = $u.next('.select2-container');
        if ($select2Container.length) {
          const $choicesContainer = $select2Container.find('.select2-selection__rendered');
          if ($choicesContainer.length && $choicesContainer[0]) {
            const observer = new MutationObserver(function (mutations) {
              // Don't reorder if we're in the middle of an unselect operation
              if (isUnselecting) return;

              // Only reorder if tags were added (not removed, as removal is handled by select2:unselect)
              const hasAdditions = mutations.some(m => m.addedNodes.length > 0);
              if (hasAdditions) {
                // Use a small delay to ensure Select2 has finished its operations
                setTimeout(() => {
                  if (!isUnselecting) {
                    reorderUsageTags();
                  }
                }, 50);
              }
            });

            observer.observe($choicesContainer[0], {
              childList: true,
              subtree: true
            });
          }
        }
      }, 500);
    }).catch(() => { });
    ajax({ action: 'masters', type: 'prescriptiontime' }).then(list => { const $t = $('#item-builder-time'); $t.empty().append('<option value="">Select Time</option>'); (list || []).forEach(x => $t.append(new Option(x.name, x.name))); }).catch(() => { });
    // Populate Oil Class in item builder section
    ajax({ action: 'masters', type: 'oil' }).then(list => { $itemBuilderOilClass.empty().append('<option value="">-- Select --</option>'); (list || []).forEach(o => $itemBuilderOilClass.append(new Option(o.name, o.name))); }).catch(() => { $itemBuilderOilClass.empty().append('<option value="">-- Select --</option>'); });

    // Ingredients field is now a free text input - no need to populate from API
  }
  populateMasters();

  // Store item data for procured_from checking
  const itemDataCache = {};

  // Track which group is being edited (if any)
  let editingGroupId = null;
  let editingGroupIndex = null; // Track the position of the group being edited

  // Function to get all currently selected item codes across all groups
  // Optionally exclude a specific group (for edit mode)
  function getAllSelectedItemCodes(excludeGroupId = null) {
    const allItemCodes = new Set();
    itemGroups.forEach(group => {
      // Skip the group being edited
      if (excludeGroupId && group.id === excludeGroupId) {
        return;
      }
      if (group.items && Array.isArray(group.items)) {
        group.items.forEach(item => {
          if (item.item_code) {
            allItemCodes.add(item.item_code);
          }
        });
      }
    });
    return allItemCodes;
  }

  // Function to check if an item is already selected in any group
  // Optionally exclude a specific group (for edit mode)
  function isItemAlreadySelected(itemCode, excludeGroupId = null) {
    const selectedCodes = getAllSelectedItemCodes(excludeGroupId);
    return selectedCodes.has(itemCode);
  }

  // init select2s
  $itemBuilder.select2({
    placeholder: 'Search or type items (multi)',
    minimumInputLength: 0,
    tags: true,
    tokenSeparators: [','],
    ajax: {
      url: function () {
        return API_URL;
      },
      dataType: 'json',
      delay: 250,
      data: function (params) {
        return {
          action: 'search_items',
          q: params.term || ''
        };
      },
      processResults: function (data) {
        console.log('Select2 processResults called with data:', data);
        // Cache item data including procured_from
        if (data && Array.isArray(data)) {
          data.forEach(item => {
            if (item && item.item_code) {
              itemDataCache[item.item_code] = item;
            }
          });

          // Format for Select2 - NO global duplicate checking
          // Items can be added to multiple groups
          const formattedResults = data.map(i => ({
            id: i.item_code,
            text: i.item_name || i.item_code
          }));
          console.log('Formatted results:', formattedResults);
          return { results: formattedResults };
        }
        return { results: [] };
      },
      cache: true
    },
    // Prevent Select2 from sorting - maintain selection order
    sorter: function (data) {
      return data; // Return data as-is, don't sort
    }
  });

  // Intercept Select2 Unselect (Item Removal from Group Builder)
  $itemBuilder.on('select2:unselecting', function (e) {
    // Removal of single item should NOT show confirmation popup
    const data = (e.params.args && e.params.args.data) || e.params.data;
    const itemId = data.id;

    // Manually remove item immediately
    let currentInfo = $itemBuilder.val() || [];
    if (!Array.isArray(currentInfo)) currentInfo = [currentInfo];
    const newValue = currentInfo.filter(x => x !== itemId);
    $itemBuilder.val(newValue).trigger('change');

    // Manually trigger update logic specific to prescription
    setTimeout(function () {
      updateProcuredFromField();
      updateUOMField();
    }, 100);
  });

  // Function to check and auto-fill procured_from based on selected items
  function updateProcuredFromField() {
    const selected = $itemBuilder.select2('data') || [];

    if (selected.length === 0) {
      $itemBuilderProcuredFrom.val('').trigger('change');
      return;
    }

    // Get procured_from values from selected items using cached data
    const procuredFromValues = [];
    selected.forEach(item => {
      const itemData = itemDataCache[item.id];
      if (itemData && itemData.procured_from) {
        procuredFromValues.push(itemData.procured_from);
      } else {
        // If not in cache, fetch it from API
        procuredFromValues.push(null);
      }
    });

    // Filter out null/empty values
    const validProcuredFromValues = procuredFromValues.filter(v => v && v.trim() !== '');

    // Check if all items have the same procured_from
    if (validProcuredFromValues.length > 0 && validProcuredFromValues.length === selected.length) {
      // All selected items have procured_from values
      const uniqueValues = [...new Set(validProcuredFromValues)];

      if (uniqueValues.length === 1) {
        // All items have the same procured_from - auto-fill
        const procuredFromName = uniqueValues[0];
        // Check if the option exists in the dropdown
        const optionExists = $itemBuilderProcuredFrom.find(`option[value="${procuredFromName}"]`).length > 0;
        if (optionExists) {
          $itemBuilderProcuredFrom.val(procuredFromName).trigger('change');
        } else {
          // Option doesn't exist, add it temporarily
          $itemBuilderProcuredFrom.append(new Option(procuredFromName, procuredFromName));
          $itemBuilderProcuredFrom.val(procuredFromName).trigger('change');
        }
      } else {
        // Different procured_from values - clear and let user select
        $itemBuilderProcuredFrom.val('').trigger('change');
      }
    } else {
      // Some or all items have null/empty procured_from - clear field and let user select
      $itemBuilderProcuredFrom.val('').trigger('change');
    }
  }

  // Listen for item selection changes
  $itemBuilder.on('select2:select select2:unselect', function () {
    // Small delay to ensure select2 data is updated
    setTimeout(function () {
      updateProcuredFromField();
      updateUOMField();
    }, 100);
  });

  // Function to check and auto-fill UOM based on selected items
  function updateUOMField() {
    const selected = $itemBuilder.select2('data') || [];

    if (selected.length === 0) {
      $('#item-builder-uno').val('').trigger('change');
      return;
    }

    // Get UOM values from selected items using cached data
    const uomValues = [];
    let missingData = false;

    selected.forEach(item => {
      const itemData = itemDataCache[item.id];
      if (itemData && typeof itemData.item_uom !== 'undefined') {
        // Treat empty string as a valid UOM (it might be "No UOM") or should we ignore it?
        // Requirement: "Evaluate... ALL medicines have SAME UOM".
        // If one has "ml" and one has "", they are different.
        // If both have "", they are same.
        uomValues.push(itemData.item_uom || '');
      } else {
        missingData = true;
      }
    });

    if (missingData) {
      // If we allow auto-fetch here it would be better, but for now fallback to empty
      $('#item-builder-uno').val('').trigger('change');
      return;
    }

    // Check if all items have the same UOM
    if (uomValues.length > 0) {
      const firstUOM = uomValues[0];
      const allSame = uomValues.every(u => u === firstUOM);

      if (allSame && firstUOM) {
        // Auto-populate
        const $uomSelect = $('#item-builder-uno');
        // Check if option exists, if not add it
        if ($uomSelect.find(`option[value="${firstUOM}"]`).length === 0) {
          $uomSelect.append(new Option(firstUOM, firstUOM));
        }
        $uomSelect.val(firstUOM).trigger('change');
      } else if (allSame && !firstUOM) {
        // All specify NO UOM.
        $('#item-builder-uno').val('').trigger('change');
      } else {
        // Different UOMs
        $('#item-builder-uno').val('').trigger('change');
      }
    }
  }

  // Add Group
  let isAddingGroup = false; // Prevent double-click

  $('#add-item-group-btn').on('click', function () {
    // Prevent double-click
    if (isAddingGroup) {
      console.warn('Add Group already in progress, ignoring duplicate click');
      return;
    }
    isAddingGroup = true;

    const selected = $itemBuilder.select2('data') || [];
    const dosage = $('#item-builder-dosage').val().trim();
    const time = $('#item-builder-time').val().trim();
    const uno = $('#item-builder-uno').val().trim();
    const oilClass = $itemBuilderOilClass.val() || '';
    const procuredFrom = $itemBuilderProcuredFrom.val() || '';
    // Ingredients is now a free text field
    const ingredientInput = $('#item-builder-ingredients');
    const ingredientsText = (ingredientInput.val() || '').trim();
    // Store as text string and also as array for backward compatibility
    const ingredients = ingredientsText ? [{ ingredient_name: ingredientsText }] : [];
    const ingredientIds = []; // No IDs for free text

    // Validate mandatory fields
    if (!selected || selected.length === 0) {
      alert('Please select at least one medication');
      $itemBuilder.focus();
      isAddingGroup = false; // Reset flag
      return;
    }

    // Check for duplicate items WITHIN the current selection only
    // NOT across all groups - same medicine can exist in different groups
    const selectedItemCodes = new Set();
    const duplicatesInSelection = [];

    selected.forEach(item => {
      if (selectedItemCodes.has(item.id)) {
        duplicatesInSelection.push(item.text || item.id);
      } else {
        selectedItemCodes.add(item.id);
      }
    });

    if (duplicatesInSelection.length > 0) {
      alert(`The following item(s) are selected multiple times in this group:\n\n${duplicatesInSelection.join('\n')}\n\nEach item can only be added once per group. Please remove the duplicate(s) from your selection.`);
      isAddingGroup = false; // Reset flag
      return;
    }

    const items = selected.length > 0 ? selected.map(s => ({ item_code: s.id, item_name: s.text || s.id })) : [];

    // Debug logging
    console.log('=== Add Group Debug ===');
    console.log('Items to add:', items.map(i => `${i.item_name} (${i.item_code})`));
    console.log('Current itemGroups count:', itemGroups.length);
    console.log('All existing item codes:', Array.from(getAllSelectedItemCodes()));
    console.log('editingGroupId:', editingGroupId);
    console.log('editingGroupIndex:', editingGroupIndex);

    const grp = { id: Math.random().toString(36).slice(2, 9), items, dosage, time, uno, oil_class: oilClass, procured_from: procuredFrom, ingredients, ingredient_ids: ingredientIds };

    // If editing a group, insert at the original position; otherwise, add to the end
    if (editingGroupIndex !== null && editingGroupIndex >= 0) {
      itemGroups.splice(editingGroupIndex, 0, grp); // Insert at original position
      console.log(`Inserted group at position ${editingGroupIndex}`);
    } else {
      itemGroups.push(grp); // Add to end
      console.log('Added group to end');
    }

    console.log('After adding - itemGroups count:', itemGroups.length);
    console.log('New group ID:', grp.id);
    console.log('=======================');

    // Clear editing group ID and index after adding
    editingGroupId = null;
    editingGroupIndex = null;

    $itemBuilder.val(null).trigger('change');
    $('#item-builder-dosage').val('');
    $('#item-builder-time').val('');
    $('#item-builder-uno').val('');
    $itemBuilderOilClass.val('');
    $itemBuilderProcuredFrom.val('');
    ingredientInput.val(''); // Clear text input
    renderItemGroups();

    // Reset flag after a short delay to allow for UI updates
    setTimeout(() => {
      isAddingGroup = false;
    }, 300);
  });

  function renderItemGroups() {
    $itemGroupsList.empty();
    if (!itemGroups.length) {
      $itemGroupsList.html(`
        <div class="empty-state" style="padding:20px;">
          <i class="fas fa-pills"></i>
          <p>No medication groups added yet</p>
        </div>
      `);
      return;
    }

    // Show each group separately with edit/remove buttons, but in the same format as final display
    itemGroups.forEach((g, i) => {
      const itemNames = (g.items || []).map(it => esc(it.item_name)).join(', ');
      // Handle ingredients - can be array of objects, array of strings, or a single string
      let ingredientsDisplay = '—';
      if (g.ingredients) {
        if (Array.isArray(g.ingredients) && g.ingredients.length > 0) {
          // Array format (old or new)
          ingredientsDisplay = g.ingredients.map(ing => {
            if (typeof ing === 'string') return esc(ing);
            return esc(ing.ingredient_name || ing.text || '');
          }).filter(Boolean).join(', ');
        } else if (typeof g.ingredients === 'string' && g.ingredients.trim()) {
          // String format (new free text)
          ingredientsDisplay = esc(g.ingredients);
        }
      }
      const timeDisplay = g.time ? esc(g.time) : '—';
      const oilClassDisplay = g.oil_class ? esc(g.oil_class) : '—';
      const procuredFromDisplay = g.procured_from ? esc(g.procured_from) : '—';
      const dosageDisplay = (g.dosage && g.uno)
        ? `${esc(g.dosage)} (${esc(g.uno)})`
        : (g.dosage ? esc(g.dosage) : '—') + (g.uno ? ` (${esc(g.uno)})` : '');

      const mainPart = itemNames || '—';
      let parts = [];
      if (mainPart !== '—') {
        parts.push(mainPart + (dosageDisplay !== '—' ? ` (${dosageDisplay})` : ''));
      }
      if (procuredFromDisplay !== '—') {
        parts.push(`Procured From: ${procuredFromDisplay}`);
      }
      if (ingredientsDisplay !== '—') {
        parts.push(`Ingredients: ${ingredientsDisplay}`);
      }
      if (timeDisplay !== '—') {
        parts.push(`Time: ${timeDisplay}`);
      }
      if (oilClassDisplay !== '—') {
        parts.push(`Oil Class: ${oilClassDisplay}`);
      }
      const groupDisplay = parts.join(', ');

      // Add separator if not the first group
      if (i > 0) {
        $itemGroupsList.append(`<div style="text-align:center;margin:8px 0;font-weight:bold;color:var(--text-medium);">+</div>`);
      }

      const $div = $(`
        <div style="padding:12px;border:1px solid var(--border-light);border-radius:8px;display:flex;justify-content:space-between;align-items:center;background:white;">
          <div style="flex:1;font-size:0.95em;">${groupDisplay}</div>
          <div style="display:flex;gap:6px;">
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

  $itemGroupsList.on('click', '.remove-group', function (e) {
    e.preventDefault();
    const id = $(this).data('id');
    showConfirm(
      "Confirm Group Removal",
      "Are you sure you want to remove this entire group and all its medicines?\nThis action cannot be undone.",
      "Yes, Remove Group",
      function () {
        itemGroups = itemGroups.filter(g => g.id !== id);
        // Clear editing group ID if the removed group was being edited
        if (editingGroupId === id) {
          editingGroupId = null;
          editingGroupIndex = null;
        }
        renderItemGroups();
      }
    );
  });

  $itemGroupsList.on('click', '.edit-group', function () {
    const id = $(this).data('id');
    const g = itemGroups.find(x => x.id === id);
    if (!g) return;

    // Show loading indicator on button
    const $btn = $(this);
    const originalText = $btn.html();
    $btn.html('<i class="fas fa-spinner fa-spin"></i> Loading...').prop('disabled', true);

    // Fetch details for all items in the group to populate cache (UOM, procured_from)
    const promises = (g.items || []).map(it => {
      if (it.item_code && !itemDataCache[it.item_code]) {
        return ajax({ action: 'search_items', q: it.item_code }).then(data => {
          if (data && Array.isArray(data)) {
            const match = data.find(x => x.item_code === it.item_code) || data[0];
            if (match) {
              itemDataCache[it.item_code] = match;
            }
          }
        }).catch(err => console.error('Error fetching item details:', err));
      }
      return Promise.resolve();
    });

    Promise.all(promises).then(() => {
      // Restore button state
      $btn.html(originalText).prop('disabled', false);

      // Set the editing group ID so duplicate checking excludes this group
      editingGroupId = id;

      // Completely clear Select2 - remove all options and values
      $itemBuilder.empty(); // Remove all option elements
      $itemBuilder.val(null).trigger('change'); // Clear selection

      // Add the group's items as new options
      g.items.forEach(it => {
        const opt = new Option(it.item_name, it.item_code, true, true);
        $itemBuilder.append(opt);
      });

      // Trigger change to update Select2 display
      $itemBuilder.trigger('change');

      // Manually trigger UOM and Procured From updates since 'change' might not trigger our custom handlers depending on binding
      // And we want to ensure fields are populated based on the now-cached data
      updateProcuredFromField();
      updateUOMField();

      // If the group had explicit saved values, override the auto-filled ones
      // This is important: if user manually changed UOM/Procured but it was valid auto-fill, we should respect saved?
      // Requirement: "user edits an existing prescription... Existing medicines must be evaluated... UOM must auto-select ONLY if all... share same UOM"
      // This suggests re-evaluation is preferred on edit opening.
      // However, if the saved group had a specific UOM (maybe manually selected when auto-select wasn't applicable, OR manually changed), 
      // strictly speaking, we should load what was saved.
      // BUT, if the user adds/removes items, auto-logic kicks in.
      // Let's set the saved values LAST, so they override auto-fill if present.

      if (g.dosage) $('#item-builder-dosage').val(g.dosage);
      if (g.time) $('#item-builder-time').val(g.time);
      if (g.uno) $('#item-builder-uno').val(g.uno).trigger('change');
      if (g.oil_class) $itemBuilderOilClass.val(g.oil_class).trigger('change');
      if (g.procured_from) $itemBuilderProcuredFrom.val(g.procured_from).trigger('change');

      // Handle ingredients - now a free text field
      const ingredientInput = $('#item-builder-ingredients');
      if (g.ingredients && Array.isArray(g.ingredients) && g.ingredients.length > 0) {
        // Extract ingredient names from array and join them
        const ingredientText = g.ingredients.map(ing => ing.ingredient_name || ing.text || '').filter(Boolean).join(', ');
        ingredientInput.val(ingredientText);
      } else if (typeof g.ingredients === 'string') {
        // Handle case where ingredients is stored as a string
        ingredientInput.val(g.ingredients);
      } else {
        ingredientInput.val('');
      }

      // Debug logging
      console.log('=== Edit Group Debug ===');
      console.log('Editing group ID:', id);
      console.log('Group items:', g.items.map(i => `${i.item_name} (${i.item_code})`));
      console.log('itemGroups count before removal:', itemGroups.length);

      // Store the original index of this group so we can restore it to the same position
      const originalIndex = itemGroups.findIndex(x => x.id === id);
      editingGroupIndex = originalIndex; // Track the position

      // Remove the group from the list (it will be re-added at the same position when user clicks "Add Group")
      itemGroups = itemGroups.filter(x => x.id !== id);

      console.log('itemGroups count after removal:', itemGroups.length);
      console.log('Original group index:', originalIndex);
      console.log('Remaining item codes:', Array.from(getAllSelectedItemCodes()));
      console.log('========================');

      renderItemGroups();
    });
  });

  // days calc
  function calcDays() {
    const f = $fromDate.val(), t = $toDate.val();
    if (!f || !t) {
      $daysInput.val('');
      return;
    }
    const fd = new Date(f), td = new Date(t);
    if (fd <= td)
      $daysInput.val(Math.ceil((td.getTime() - fd.getTime()) / (1000 * 60 * 60 * 24)) + 1);
    else
      $daysInput.val('');
  }
  $fromDate.on('change', calcDays);
  $toDate.on('change', calcDays);

  // add prescription directly to server as draft
  $allocateBtn.on('click', function () {
    if (!selectedPatient) {
      alert('Please select a patient first');
      return;
    }

    if (!itemGroups.length) { alert('Add at least one item group'); return; }
    const from = $fromDate.val(), to = $toDate.val();
    if (!from || !to) { alert('Please set From and To dates'); return; }
    if (from > to) { alert('From must be <= To'); return; }

    // Get common usage in selection order
    const selectedValues = $commonUsageSelect.val() || [];
    // Maintain selection order instead of alphabetical
    const commonUsageValues = usageSelectionOrder.filter(val => selectedValues.indexOf(val) !== -1);
    const commonUsage = commonUsageValues.join(', ');

    // Prepare prescription data
    const prescriptionData = {
      from_date: from,
      to_date: to,
      days: Math.ceil((new Date(to).getTime() - new Date(from).getTime()) / (1000 * 60 * 60 * 24)) + 1,
      // procured_from is now stored per group in items_groups, not globally
      scope: $scopeSelect.val() || '',
      usage: commonUsage,
      usage_array: commonUsageValues,
      items_groups: itemGroups.map(g => ({
        items: g.items,
        dosage: g.dosage,
        time: g.time,
        uno: g.uno,
        oil_class: g.oil_class || '',
        procured_from: g.procured_from || '',
        ingredient_ids: g.ingredient_ids || [],
        ingredients: g.ingredients || []
      })),
      notes: ''
    };

    // Determine correct registration number based on patient type
    // For IP patients: use pat_reg_no (not pat_op_reg_no)
    // For OP patients: use pat_op_reg_no if available, otherwise pat_reg_no
    const patientType = selectedPatient.patient_type ||
      (selectedPatient.pat_reg_no && selectedPatient.pat_reg_no.toString().replace(/\D/g, '').length === 5 ? 'OP' : 'IP');
    const patientRegNo = patientType === 'IP'
      ? selectedPatient.pat_reg_no
      : (selectedPatient.pat_op_reg_no || selectedPatient.pat_reg_no);

    // Save directly to server as draft
    const payload = {
      patient_reg_no: patientRegNo,
      patient_name: selectedPatient.pat_name,
      patient_age: selectedPatient.pat_age || '',
      patient_sex: selectedPatient.pat_sex || '',
      patient_room_no: selectedPatient.pat_room_no || '',
      pat_ref_id: selectedPatient.pat_ref_id || '',
      ...prescriptionData
    };

    // Show loading state
    $allocateBtn.prop('disabled', true).html('<i class="fas fa-spinner fa-spin"></i> Saving...');

    fetch(API_URL + '?action=allocate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
      body: JSON.stringify(payload)
    }).then(response => {
      if (!response.ok) {
        return response.json().then(j => {
          throw new Error(j.error || 'Failed to save prescription');
        }).catch(() => {
          throw new Error(`Server error: ${response.status}`);
        });
      }
      return response.json();
    }).then(j => {
      if (j.allocation_id || j.status === 'ok') {
        // Remember this as 'added' action before reloading
        const newAllocationId = j.allocation_id;
        if (newAllocationId) {
          rememberPrescriptionAction(newAllocationId, 'added');
        }

        // Reset form first
        itemGroups = [];
        renderItemGroups();
        const today = new Date().toISOString().split('T')[0];
        $fromDate.val(today);
        $toDate.val('');
        $daysInput.val('');
        // procured_from is now per group, not global - no need to clear global field 
        $scopeSelect.val('');
        $commonUsageSelect.val(null).trigger('change');
        usageSelectionOrder = []; // Reset selection order

        if (j.prescriptions && Array.isArray(j.prescriptions)) {
          addedPrescriptions = decoratePrescriptionList(j.prescriptions);
          console.log('Allocation successful. Updated prescription list count:', addedPrescriptions.length);
          renderAll();
          alert('Prescription saved to server as Draft.');
        } else if (selectedPatient) {
          // Fallback if prescriptions not in response
          const patientType = selectedPatient.patient_type ||
            (selectedPatient.pat_reg_no && selectedPatient.pat_reg_no.toString().replace(/\D/g, '').length === 5 ? 'OP' : 'IP');
          const patientRegNo = patientType === 'IP'
            ? selectedPatient.pat_reg_no
            : (selectedPatient.pat_op_reg_no || selectedPatient.pat_reg_no);

          setTimeout(() => {
            ajax({ action: 'patient_prescriptions', patient_reg_no: patientRegNo }).then(list => {
              if (list && Array.isArray(list)) {
                addedPrescriptions = decoratePrescriptionList(list);
                renderAll();
                alert('Prescription saved to server as Draft.');
              }
            });
          }, 500);
        } else {
          alert('Prescription saved to server as Draft.');
          renderAll();
        }
      } else {
        alert('Failed to save prescription: ' + (j.error || 'Unknown error'));
      }
    }).catch(e => {
      console.error('Network error saving prescription:', e);
      alert('Network error: ' + (e.message || 'Please try again.'));
    }).finally(() => {
      // Reset button state
      $allocateBtn.prop('disabled', false).html('<i class="fas fa-save"></i> Save Prescription');
    });
  });

  // Decide row color for today's prescription status (Added/Updated/Resumed/Cancelled for today only)
  function getTodayPrescriptionColorClass(p) {
    if (!p) return '';
    // Priority 1: Session Action
    const lastAction = String(p.last_action || '').toLowerCase().trim();
    if (lastAction && lastAction !== '' && lastAction !== 'null' && lastAction !== 'undefined') {
      return 'action-' + lastAction;
    }

    // Priority 2: Status-based derivation
    const s = String(p.status || '').trim().toLowerCase();
    const hasCancellations = p.cancelled_date_from && p.cancelled_date_to && p.cancelled_date_from !== 'null';
    if (s === 'cancelled' || hasCancellations) return 'action-cancelled';

    return 'action-added';
  }

  function buildActionBadge(actionClass) {
    const labelMap = {
      'action-added': 'Added (today)',
      'action-updated': 'Updated (today)',
      'action-resumed': 'Resumed (today)',
      'action-cancelled': 'Cancelled (today)'
    };
    if (!actionClass || !labelMap[actionClass]) return '';
    return `<span class="action-pill ${actionClass}">${labelMap[actionClass]}</span>`;
  }

  // render prescriptions table
  function renderPrescriptions() {
    $prescriptionsTableBody.empty();
    if (!addedPrescriptions.length) {
      $prescriptionsTableBody.append(`
        <tr>
          <td colspan="9">
            <div class="empty-state">
              <i class="fas fa-prescription-bottle"></i>
              <h3>No Prescriptions Found</h3>
              <p>Select a patient and create a new prescription to get started</p>
            </div>
          </td>
        </tr>
      `);
      return;
    }
    addedPrescriptions.forEach((p, i) => {
      // Get common usage from prescription level (shown in its own column)
      let commonUsageDisplay = '';
      if (p.usage) {
        commonUsageDisplay = esc(p.usage);
      } else if (Array.isArray(p.usage_array) && p.usage_array.length > 0) {
        commonUsageDisplay = esc(p.usage_array.join(', '));
      }

      // Build clearer, per‑group blocks:
      //   Line 1: item names (highlighted)
      //   Line 2: Dosage / Time / Ext-Int / Ingredients
      const groupsHtml = (p.items_groups || []).map((g, idx) => {
        const items = g.items || [];
        const itemNames = items.map(it => esc(it.item_name)).join(', ');

        // Dosage + UNO
        const doseRaw = g.dosage || '';
        const unoRaw = g.uno || '';
        let doseDisplay = '';
        if (doseRaw && unoRaw) {
          doseDisplay = `${doseRaw} (${unoRaw})`;
        } else if (doseRaw) {
          doseDisplay = doseRaw;
        } else if (unoRaw) {
          doseDisplay = unoRaw;
        }

        // Ingredients - handle both array and string formats
        let ingredientsDisplay = '';
        if (g.ingredients) {
          if (Array.isArray(g.ingredients) && g.ingredients.length > 0) {
            ingredientsDisplay = g.ingredients.map(ing => {
              if (typeof ing === 'string') return esc(ing);
              return esc(ing.ingredient_name || ing.text || '');
            }).filter(Boolean).join(', ');
          } else if (typeof g.ingredients === 'string' && g.ingredients.trim()) {
            ingredientsDisplay = esc(g.ingredients);
          }
        }

        const time = g.time ? esc(g.time) : '';
        const extInt = g.internal_external ? esc(g.internal_external) : '';
        const procuredFrom = g.procured_from ? esc(g.procured_from) : '';

        const details = [];
        const oilClass = g.oil_class ? esc(g.oil_class) : '';
        if (doseDisplay) details.push(`Dosage: ${doseDisplay}`);
        if (procuredFrom) details.push(`Procured From: ${procuredFrom}`);
        if (time) details.push(`Time: ${time}`);
        if (extInt) details.push(`Ext/Int: ${extInt}`);
        if (ingredientsDisplay) details.push(`Ingredients: ${ingredientsDisplay}`);
        if (oilClass) details.push(`Oil Class: ${oilClass}`);

        const firstLinePrefix = idx === 0 ? '• ' : '+ ';
        const firstLine = `${firstLinePrefix}<span class="med-items-pill">${itemNames || 'No medicines'}</span>`;
        const secondLine = details.length ? `<span class="med-details-text">${details.join(' | ')}</span>` : '';

        return `
          <div class="med-group-line">
            <div class="med-group-items">${firstLine}</div>
            ${secondLine ? `<div class="med-group-details">${secondLine}</div>` : ''}
          </div>
        `;
      }).join('');

      // Status logic - show counts if available, format: "2 Draft / 3 Active"
      let statusHtml = '';
      let statusClass = 'status-active';

      // Build status display with counts - format: "2 Draft / 3 Active / 1 Scheduled"
      const statusSummary = p.status_summary || {};
      const statusParts = [];

      // Order: Draft, Active, Scheduled, Dispatched, Failed, Cancelled
      if (statusSummary.draft) {
        statusParts.push(`${statusSummary.draft} Draft`);
      }
      if (statusSummary.active) {
        statusParts.push(`${statusSummary.active} Active`);
      }
      if (statusSummary.scheduled) {
        statusParts.push(`${statusSummary.scheduled} Scheduled`);
      }
      if (statusSummary.dispatched) {
        statusParts.push(`${statusSummary.dispatched} Dispatched`);
      }
      if (statusSummary.failed) {
        statusParts.push(`${statusSummary.failed} Failed`);
      }
      if (statusSummary.cancelled) {
        statusParts.push(`${statusSummary.cancelled} Cancelled`);
      }

      // If we have detailed counts, show them with slashes
      if (statusParts.length > 0) {
        statusHtml = `<span class="status-pill status-mixed">${statusParts.join(' / ')}</span>`;
        statusClass = 'status-mixed';
      } else {
        // Fallback to overall status if no counts available
        if (p.status === 'cancelled') {
          statusHtml = '<span class="status-pill status-cancelled">Cancelled</span>';
          statusClass = 'status-cancelled';
        } else if (p.status === 'draft') {
          statusHtml = '<span class="status-pill status-draft">Draft</span>';
          statusClass = 'status-draft';
        } else if (p.status === 'active') {
          statusHtml = '<span class="status-pill status-active">Active</span>';
          statusClass = 'status-active';
        } else if (p.status === 'failed') {
          statusHtml = '<span class="status-pill status-failed">Failed</span>';
          statusClass = 'status-failed';
        } else {
          statusHtml = '<span class="status-pill status-draft">Draft</span>';
          statusClass = 'status-draft';
        }
      }

      // Get unique procured_from values from all groups for display
      const procuredFromValues = [...new Set((p.items_groups || []).map(g => g.procured_from).filter(pf => pf))];
      const procuredFromDisplay = procuredFromValues.length > 0 ? procuredFromValues.join(', ') : '—';

      const actionClass = getTodayPrescriptionColorClass(p);

      const row = `<tr class="${statusClass} ${actionClass}">
        <td>${i + 1}</td>
        <td>${esc(p.prescription_name || 'Prescription')}</td>
        <td>${esc(procuredFromDisplay)}</td>
        <td>${esc(p.scope || '')}</td>
        <td>${commonUsageDisplay || '—'}</td>
        <td>
          <div>${groupsHtml}</div>
        </td>
        <td>${formatDate(p.from_date)}</td>
        <td>${formatDate(p.to_date)}</td>
        <td>${esc(p.days || '')}</td>
        <td>${statusHtml}</td>
        <td>
          <button class="edit-prescription action-btn btn btn-outline" data-i="${i}">
            <i class="fas fa-edit"></i> Edit
          </button>
          <button class="update-prescription action-btn btn btn-success" data-i="${i}" style="display:none">
            <i class="fas fa-sync-alt"></i> Update
          </button>
          ${(() => {
          // Check for cancelled dates - handle null, undefined, and string 'null'
          const hasCancelledDates = p.cancelled_date_from &&
            p.cancelled_date_to &&
            p.cancelled_date_from !== 'null' &&
            p.cancelled_date_to !== 'null' &&
            p.cancelled_date_from !== null &&
            p.cancelled_date_to !== null;
          const hasDateRange = p.from_date && p.to_date;
          let buttons = '';
          // Show resume button if there are cancelled dates
          if (hasCancelledDates) {
            buttons += `<button class="resume-prescription action-btn btn btn-success" data-i="${i}">
                <i class="fas fa-play-circle"></i> Resume
              </button>`;
          }
          // Show cancel button if there's a date range (can always cancel, will merge with existing)
          if (hasDateRange) {
            buttons += `<button class="cancel-prescription action-btn btn" data-i="${i}" style="background:var(--warning);">
                <i class="fas fa-ban"></i> Cancel
              </button>`;
          }
          // Show Status button to view day-by-day history
          buttons += `<button class="status-prescription action-btn btn btn-outline" data-i="${i}" style="border:1px solid var(--primary); color:var(--primary);">
              <i class="fas fa-list"></i> Status
            </button>`;
          return buttons;
        })()}
        </td>
      </tr>`;
      $prescriptionsTableBody.append(row);
    });
  }

  function renderAll() { renderItemGroups(); renderPrescriptions(); }

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

  // Edit prescription
  $prescriptionsTableBody.on('click', '.edit-prescription', function () { const i = $(this).data('i'); loadPrescriptionForEdit(i); });
  function loadPrescriptionForEdit(index) {
    const p = addedPrescriptions[index]; if (!p) return;
    editPrescriptionIndex = index;
    $('#form-title').text('Edit Prescription');
    $fromDate.val(p.from_date || '');
    $toDate.val(p.to_date || '');
    $daysInput.val(p.days || '');
    // procured_from is now per group, not global - no need to set global field
    $scopeSelect.val(p.scope || '');

    // Load common usage and restore selection order
    usageSelectionOrder = []; // Reset selection order
    if (p.usage_array && Array.isArray(p.usage_array)) {
      usageSelectionOrder = [...p.usage_array]; // Preserve the order from saved data
      $commonUsageSelect.val(p.usage_array).trigger('change');
      // Reorder tags after loading
      setTimeout(reorderUsageTags, 200);
    } else if (p.usage) {
      const usageArray = p.usage.split(',').map(u => u.trim()).filter(u => u);
      usageSelectionOrder = [...usageArray]; // Preserve the order from saved data
      $commonUsageSelect.val(usageArray).trigger('change');
      // Reorder tags after loading
      setTimeout(reorderUsageTags, 200);
    } else {
      usageSelectionOrder = [];
      $commonUsageSelect.val(null).trigger('change');
    }

    // Load item groups and deduplicate items WITHIN each group only
    // Same medicine can exist in different groups
    const loadedGroups = [];

    (p.items_groups || []).forEach(g => {
      // Deduplicate items within THIS group only
      const seenInGroup = new Set();
      const uniqueItems = (g.items || []).filter(item => {
        if (!item.item_code) return true; // Keep items without codes (shouldn't happen)
        if (seenInGroup.has(item.item_code)) {
          console.warn(`Duplicate item within group detected and removed: ${item.item_name} (${item.item_code})`);
          return false; // Skip this duplicate item within the group
        }
        seenInGroup.add(item.item_code);
        return true; // Keep this unique item within the group
      });

      // Only add the group if it has items after deduplication
      if (uniqueItems.length > 0) {
        loadedGroups.push({
          id: Math.random().toString(36).slice(2, 9),
          items: uniqueItems,
          dosage: g.dosage || '',
          time: g.time || '',
          uno: g.uno || '',
          oil_class: g.oil_class || '',
          procured_from: g.procured_from || '',
          ingredient_ids: g.ingredient_ids || [],
          ingredients: g.ingredients || []
        });
      }
    });

    itemGroups = loadedGroups;
    renderItemGroups();
    $allocateBtn.hide(); $updateBtn.show(); window.scrollTo({ top: 0, behavior: 'smooth' });
  }
  $updateBtn.on('click', function () {
    if (editPrescriptionIndex === null) { alert('No prescription in edit mode'); return; }
    const p = addedPrescriptions[editPrescriptionIndex]; if (!p) return;

    // Get common usage in selection order
    const selectedValues = $commonUsageSelect.val() || [];
    // Maintain selection order instead of alphabetical
    const commonUsageValues = usageSelectionOrder.filter(val => selectedValues.indexOf(val) !== -1);
    const commonUsage = commonUsageValues.join(', ');

    // Get dates and days from form
    const fromDate = $fromDate.val() || '';
    const toDate = $toDate.val() || '';
    const days = parseInt($daysInput.val()) || 0;

    // Update local data
    p.scope = $scopeSelect.val() || '';
    p.usage = commonUsage;
    p.usage_array = commonUsageValues;
    p.from_date = fromDate;
    p.to_date = toDate;
    p.days = days;
    p.items_groups = itemGroups.map(g => ({
      ingredient_ids: g.ingredient_ids || [],
      ingredients: g.ingredients || [],
      items: g.items,
      dosage: g.dosage,
      time: g.time,
      procured_from: g.procured_from || '',
      uno: g.uno,
      oil_class: g.oil_class || ''
    }));

    // Send update to server if prescription has allocation_id
    if (p.allocation_id) {
      const updatePayload = {
        allocation_id: p.allocation_id,
        items_groups: p.items_groups,
        // procured_from is now stored per group in items_groups, not globally
        scope: p.scope,
        usage: p.usage,
        usage_array: p.usage_array,
        from_date: p.from_date,
        to_date: p.to_date,
        days: p.days,
        notes: p.notes || ''
      };

      console.log('--- Sending Update to Server ---');
      console.log('Payload:', JSON.stringify(updatePayload));

      fetch(API_URL + '?action=update_prescription&_cb=' + Date.now(), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updatePayload)
      }).then(response => {
        if (!response.ok) {
          return response.json().then(j => {
            throw new Error(j.error || 'Failed to update prescription');
          }).catch(() => {
            throw new Error(`Server error: ${response.status}`);
          });
        }
        return response.json();
      }).then(j => {
        console.log('--- Server Response Received ---');
        console.log('Raw result:', j);

        if (j.status === 'ok') {
          // Check if today is cancelled or resumed BEFORE marking as updated
          const today = new Date().toISOString().slice(0, 10);
          const todayIsCancelled = p.cancelled_date_from && p.cancelled_date_to &&
            p.cancelled_date_from !== 'null' && p.cancelled_date_to !== 'null' &&
            today >= p.cancelled_date_from && today <= p.cancelled_date_to;
          const todayIsResumed = p.resumed_at && p.resumed_at.slice(0, 10) === today;

          // Use the potentially new allocation_id returned by the server for color-coding
          const resultId = j.allocation_id || p.allocation_id || p.id;

          if (todayIsCancelled) {
            rememberPrescriptionAction(resultId, 'cancelled');
          } else if (todayIsResumed) {
            rememberPrescriptionAction(resultId, 'resumed');
          } else {
            rememberPrescriptionAction(resultId, 'updated');
          }

          // Also mark the local object just in case, though it might be replaced soon
          p.last_action = todayIsCancelled ? 'cancelled' : (todayIsResumed ? 'resumed' : 'updated');

          // Non-blocking feedback instead of alert
          console.log('Prescription updated successfully on server. Returned ID:', resultId);
          resetFormState();

          // Use the refreshed prescriptions list returned directly in the response
          if (j.prescriptions && Array.isArray(j.prescriptions)) {
            const oldLen = addedPrescriptions.length;
            console.log(`Syncing UI. Before: ${oldLen}, After: ${j.prescriptions.length}`);
            console.table(j.prescriptions.map(p => ({
              id: p.id,
              name: p.prescription_name,
              from: p.from_date,
              to: p.to_date,
              status: JSON.stringify(p.status_summary)
            })));

            // Atomically replace and re-render
            addedPrescriptions = decoratePrescriptionList(j.prescriptions);

            if (addedPrescriptions.length > oldLen) {
              console.log('%c Prescription split successfully! New record added for historical integrity. ', 'background: #222; color: #bada55');
              alert(`Update successful.\n\nHistorical integrity preserved: Today's dispatched record was shortened, and a new record was created starting tomorrow.\n\nTotal prescriptions: ${addedPrescriptions.length}`);
            }

            setTimeout(renderAll, 100);
          } else {
            console.warn('Backend did not return updated prescriptions list. Attempting manual sync.');
            renderAll();
            // Fallback for backward compatibility
            setTimeout(() => {
              if (selectedPatient) {
                const patientType = selectedPatient.patient_type ||
                  (selectedPatient.pat_reg_no && selectedPatient.pat_reg_no.toString().replace(/\D/g, '').length === 5 ? 'OP' : 'IP');
                const patientRegNo = patientType === 'IP'
                  ? selectedPatient.pat_reg_no
                  : (selectedPatient.pat_op_reg_no || selectedPatient.pat_reg_no);

                if (patientRegNo) {
                  ajax({ action: 'patient_prescriptions', patient_reg_no: patientRegNo, _t: Date.now() }).then(list => {
                    if (list && Array.isArray(list)) {
                      addedPrescriptions = decoratePrescriptionList(list);
                      renderAll();
                    }
                  });
                }
              }
            }, 500);
          }
        } else {
          alert('Failed to update prescription: ' + (j.error || JSON.stringify(j)));
          renderAll();
        }
      }).catch(e => {
        alert('Network error: ' + (e.message || 'Prescription updated locally only.'));
        // Check if today is cancelled or resumed before marking as updated
        const today = new Date().toISOString().slice(0, 10);
        const todayIsCancelled = p.cancelled_date_from && p.cancelled_date_to &&
          p.cancelled_date_from !== 'null' && p.cancelled_date_to !== 'null' &&
          today >= p.cancelled_date_from && today <= p.cancelled_date_to;
        const todayIsResumed = p.resumed_at && p.resumed_at.slice(0, 10) === today;

        if (todayIsCancelled) {
          p.last_action = 'cancelled';
          rememberPrescriptionAction(p.allocation_id || p.id, 'cancelled');
        } else if (todayIsResumed) {
          p.last_action = 'resumed';
          rememberPrescriptionAction(p.allocation_id || p.id, 'resumed');
        } else {
          p.last_action = 'updated';
          rememberPrescriptionAction(p.allocation_id || p.id, 'updated');
        }
        resetFormState();
        renderAll();
      });
    } else {
      // Update local data only (for unsaved prescriptions)
      // Check if today is cancelled or resumed before marking as updated
      const today = new Date().toISOString().slice(0, 10);
      const todayIsCancelled = p.cancelled_date_from && p.cancelled_date_to &&
        p.cancelled_date_from !== 'null' && p.cancelled_date_to !== 'null' &&
        today >= p.cancelled_date_from && today <= p.cancelled_date_to;
      const todayIsResumed = p.resumed_at && p.resumed_at.slice(0, 10) === today;

      if (todayIsCancelled) {
        p.last_action = 'cancelled';
        rememberPrescriptionAction(p.allocation_id || p.id, 'cancelled');
      } else if (todayIsResumed) {
        p.last_action = 'resumed';
        rememberPrescriptionAction(p.allocation_id || p.id, 'resumed');
      } else {
        p.last_action = 'updated';
        rememberPrescriptionAction(p.allocation_id || p.id, 'updated');
      }
      resetFormState();
      // Render immediately to show correct color
      renderAll();
      alert('Prescription updated locally.');
    }
  });

  function resetFormState() {
    editPrescriptionIndex = null; $('#form-title').text('Create New Prescription');
    const today = new Date().toISOString().split('T')[0];
    $fromDate.val(today); $toDate.val(''); $daysInput.val('');
    // procured_from is now per group, not global - no need to clear global field
    $scopeSelect.val('');
    $commonUsageSelect.val(null).trigger('change');
    usageSelectionOrder = []; // Reset selection order
    itemGroups = [];
    editingGroupId = null; // Clear editing group ID
    editingGroupIndex = null; // Clear editing group index
    renderItemGroups();
    $allocateBtn.show(); $updateBtn.hide();
  }

  // Cancel prescription
  $prescriptionsTableBody.on('click', '.cancel-prescription', function () { const i = $(this).data('i'); openCancelModal(i); });
  function openCancelModal(index) {
    cancelingPrescriptionIndex = index;
    const p = addedPrescriptions[index];
    if (!p) return;

    let infoText = `Prescription: ${p.prescription_name} — Allowed cancel range: ${formatDate(p.from_date) || '—'} → ${formatDate(p.to_date) || '—'}`;

    // Set initial info text (will be updated with cancelled dates if available)
    $('#cancel-modal-info').html(infoText.replace(/\n/g, '<br>'));

    // Fetch PrescriptionScheduling statuses to show individual cancelled dates (not just the range)
    if (p.allocation_id && p.cancelled_date_from && p.cancelled_date_to &&
      p.cancelled_date_from !== 'null' && p.cancelled_date_to !== 'null') {
      // Get all dates in the cancelled range
      const cancelledRangeDates = getDateRange(p.cancelled_date_from, p.cancelled_date_to);
      // Filter out dates that have been resumed (from resumed_dates array)
      const resumedDates = p.resumed_dates && Array.isArray(p.resumed_dates) ? new Set(p.resumed_dates) : new Set();
      const actuallyCancelledDates = cancelledRangeDates.filter(date => !resumedDates.has(date));

      // Update info text with individual cancelled dates
      let updatedInfoText = `Prescription: ${p.prescription_name} — Allowed cancel range: ${formatDate(p.from_date) || '—'} → ${formatDate(p.to_date) || '—'}`;
      if (actuallyCancelledDates.length > 0) {
        // Show individual cancelled dates
        const datesList = actuallyCancelledDates.map(d => formatDate(d)).join(', ');
        updatedInfoText += `<br>Already cancelled dates: ${datesList}`;
      }
      $('#cancel-modal-info').html(updatedInfoText);
    }

    // ALWAYS reset and set the date inputs to the current prescription's date range
    // Clear any previous values first
    $cancelFrom.val('');
    $cancelTo.val('');

    // Set min/max based on prescription date range
    if (p.from_date) {
      $cancelFrom.attr('min', p.from_date);
      $cancelFrom.attr('max', p.to_date || p.from_date);
    } else {
      $cancelFrom.removeAttr('min');
      $cancelFrom.removeAttr('max');
    }

    if (p.to_date) {
      $cancelTo.attr('max', p.to_date);
      $cancelTo.attr('min', p.from_date || p.to_date);
    } else {
      $cancelTo.removeAttr('max');
      $cancelTo.removeAttr('min');
    }

    // ALWAYS set default values to the current prescription's date range (not previous values)
    if (p.from_date && p.to_date) {
      $cancelFrom.val(p.from_date);
      $cancelTo.val(p.to_date);
    }

    $cancelReason.val('');
    $cancelModal.show();
  }

  $cancelCloseBtn.on('click', function () { $cancelModal.hide(); cancelingPrescriptionIndex = null; });

  $cancelSubmitBtn.on('click', function () {
    if (cancelingPrescriptionIndex === null) return;
    const p = addedPrescriptions[cancelingPrescriptionIndex];
    if (!p) return;
    const cfrom = $cancelFrom.val(), cto = $cancelTo.val(), reason = $cancelReason.val().trim();
    if (!cfrom || !cto) { alert('Pick both Cancel From and Cancel To'); return; }
    if (cfrom > cto) { alert('Cancel From must be <= Cancel To'); return; }
    if (p.from_date && cfrom < p.from_date) { alert('Cancel From < prescription start'); return; }
    if (p.to_date && cto > p.to_date) { alert('Cancel To > prescription end'); return; }
    if (!reason) { alert('Cancellation reason is mandatory'); return; }

    // IMMEDIATELY update local data BEFORE server call - EXACTLY like therapy entry
    // Calculate how many days are being cancelled
    const cancelledDates = getDateRange(cfrom, cto);
    const cancelledDaysCount = cancelledDates.length;

    // Update status_summary optimistically to reflect the cancellation
    if (!p.status_summary) {
      p.status_summary = {};
    }

    // Calculate how many days were already cancelled in the new range
    let alreadyCancelledInRange = 0;
    if (p.cancelled_date_from && p.cancelled_date_to) {
      const existingCancelledDates = getDateRange(p.cancelled_date_from, p.cancelled_date_to);
      const newCancelledDates = getDateRange(cfrom, cto);
      // Count dates that are in both ranges (already cancelled)
      alreadyCancelledInRange = newCancelledDates.filter(d => existingCancelledDates.includes(d)).length;
    }

    // Calculate how many new days are being cancelled (not already cancelled)
    const newlyCancelledDays = cancelledDaysCount - alreadyCancelledInRange;

    // Update cancelled count (add newly cancelled days)
    if (newlyCancelledDays > 0) {
      p.status_summary.cancelled = (p.status_summary.cancelled || 0) + newlyCancelledDays;

      // Decrease draft/active counts for newly cancelled days
      // We need to estimate how many were draft vs active
      // For simplicity, we'll decrease draft first, then active
      const currentDraft = p.status_summary.draft || 0;
      const currentActive = p.status_summary.active || 0;

      if (currentDraft >= newlyCancelledDays) {
        p.status_summary.draft = currentDraft - newlyCancelledDays;
        if (p.status_summary.draft === 0) {
          delete p.status_summary.draft;
        }
      } else {
        // Decrease all draft, then decrease active for the remainder
        const remainingToCancel = newlyCancelledDays - currentDraft;
        if (currentDraft > 0) {
          delete p.status_summary.draft;
        }
        if (currentActive >= remainingToCancel) {
          p.status_summary.active = currentActive - remainingToCancel;
          if (p.status_summary.active === 0) {
            delete p.status_summary.active;
          }
        } else {
          // If active is less than remaining, just decrease what we have
          if (currentActive > 0) {
            delete p.status_summary.active;
          }
        }
      }
    }

    if (!p.cancelled_date_from || cfrom < p.cancelled_date_from) {
      p.cancelled_date_from = cfrom;
    }
    if (!p.cancelled_date_to || cto > p.cancelled_date_to) {
      p.cancelled_date_to = cto;
    }
    p.status = 'cancelled';
    p.cancellation_reason = reason;

    // Set last_action to 'cancelled' immediately (ignore today's date check)
    p.last_action = 'cancelled';
    rememberPrescriptionAction(p.allocation_id || p.id, 'cancelled');

    // IMMEDIATELY update UI - don't wait for server - EXACTLY like therapy entry
    $cancelModal.hide();
    renderAll();
    setTimeout(() => {
      alert('Prescription cancelled successfully.');
    }, 100);

    if (p.allocation_id) {
      // Server-side cancellation (happens in background)
      fetch(API_URL + '?action=cancel_prescription', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ allocation_id: p.allocation_id, cancel_from: cfrom, cancel_to: cto, reason: reason })
      }).then(r => r.json()).then(j => {
        if (j.status === 'ok') {
          // UI already updated above, alert already shown, server sync will happen in background

          // Use the refreshed prescriptions list returned directly in the response
          if (j.prescriptions && Array.isArray(j.prescriptions)) {
            addedPrescriptions = decoratePrescriptionList(j.prescriptions);
            renderAll();
          } else if (selectedPatient) {
            // Fallback
            const patientRegNo = selectedPatient.pat_reg_no || selectedPatient.pat_op_reg_no;
            setTimeout(() => {
              ajax({ action: 'patient_prescriptions', patient_reg_no: patientRegNo, _t: Date.now() }).then(list => {
                if (list && Array.isArray(list)) {
                  addedPrescriptions = decoratePrescriptionList(list);
                  renderAll();
                }
              });
            }, 500);
          }
        } else {
          alert('Failed: ' + JSON.stringify(j));
        }
      }).catch(() => alert('Network error'));
    } else {
      // Local cancellation - already updated above, just show message
      // (alert already shown above)
    }
  });

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

  // Resume prescription
  $prescriptionsTableBody.on('click', '.resume-prescription', function () { const i = $(this).data('i'); openResumeModal(i); });

  function openResumeModal(index) {
    resumingPrescriptionIndex = index;
    const p = addedPrescriptions[index];
    if (!p) return;

    // Get fresh data from the prescription object (ensure we have latest cancelled dates)
    const cancelledFrom = p.cancelled_date_from;
    const cancelledTo = p.cancelled_date_to;

    $('#resume-modal-info').html(`<strong>Prescription:</strong> ${p.prescription_name || 'N/A'}<br/><strong>Cancelled Range:</strong> ${formatDate(cancelledFrom) || '—'} → ${formatDate(cancelledTo) || '—'}`);

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

    // If we have an allocation_id, use resumed_dates to show only dates that are still cancelled
    if (p.allocation_id) {
      // Get set of already resumed dates for this prescription
      const resumedDates = p.resumed_dates && Array.isArray(p.resumed_dates) ? new Set(p.resumed_dates) : new Set();

      // Filter to show only dates that are still cancelled (not in resumed_dates)
      const stillCancelledDates = cancelledDates.filter(date => !resumedDates.has(date));

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
  $(document).on('click', '.resume-date-btn', function (e) {
    e.preventDefault();
    e.stopPropagation();

    const date = $(this).data('date');
    console.log('Resume button clicked, date:', date, 'resumingPrescriptionIndex:', resumingPrescriptionIndex);

    if (!date || resumingPrescriptionIndex === null) {
      console.log('Missing date or resumingPrescriptionIndex:', { date, resumingPrescriptionIndex });
      return;
    }

    const prescription = addedPrescriptions[resumingPrescriptionIndex];
    if (!prescription) {
      console.log('Prescription not found at index:', resumingPrescriptionIndex);
      return;
    }

    console.log('Prescription found:', prescription);
    console.log('Cancelled dates:', prescription.cancelled_date_from, prescription.cancelled_date_to);

    if (!confirm(`Are you sure you want to resume prescription for ${formatDate(date)}?`)) {
      return;
    }

    // IMMEDIATELY remove the button from the modal (optimistic UI update)
    // This provides instant feedback to the user
    const $clickedButton = $(this);
    const $dateItem = $clickedButton.closest('div[style*="display: flex"]');

    $dateItem.fadeOut(200, function () {
      $(this).remove();
      // If no dates left, show message
      const $datesList = $('#resume-dates-list');
      if ($datesList.children().length === 0) {
        $datesList.html('<p style="color: #666; padding: 16px; text-align: center;">No cancelled dates remaining.</p>');
      }
    });

    // IMMEDIATELY update local data BEFORE server call
    // Update status_summary optimistically to reflect the resume action
    if (!prescription.status_summary) {
      prescription.status_summary = {};
    }

    // Mark as resumed for color coding FIRST, before rendering
    prescription.last_action = 'resumed';
    rememberPrescriptionAction(prescription.allocation_id || prescription.id, 'resumed');

    // Decrease cancelled count and increase draft count optimistically
    if (prescription.status_summary.cancelled && prescription.status_summary.cancelled > 0) {
      prescription.status_summary.cancelled = (prescription.status_summary.cancelled || 0) - 1;
      if (prescription.status_summary.cancelled === 0) {
        delete prescription.status_summary.cancelled;
      }
    }
    // Increase draft count (the resumed prescription will be draft)
    prescription.status_summary.draft = (prescription.status_summary.draft || 0) + 1;

    // For middle dates, we don't update cancelled_date_from/to optimistically
    // We wait for server response to get the correct updated range
    if (prescription.cancelled_date_from === date && prescription.cancelled_date_to === date) {
      // Resuming the only cancelled date - clear cancellation
      prescription.status = 'draft';
      prescription.cancelled_date_from = null;
      prescription.cancelled_date_to = null;
      prescription.cancellation_reason = '';
      renderAll();
    } else if (prescription.cancelled_date_from === date) {
      // Resuming from start - move start date forward
      const nextDate = new Date(date);
      nextDate.setDate(nextDate.getDate() + 1);
      prescription.cancelled_date_from = nextDate.toISOString().split('T')[0];
      renderAll();
    } else if (prescription.cancelled_date_to === date) {
      // Resuming from end - move end date backward
      const prevDate = new Date(date);
      prevDate.setDate(prevDate.getDate() - 1);
      prescription.cancelled_date_to = prevDate.toISOString().split('T')[0];
      renderAll();
    } else {
      // Resuming a date in the middle - DON'T update cancelled_date_from/to optimistically
      // Keep the range unchanged and wait for server response
      // The server will keep the range unchanged, only resuming the specific date
      // But we've already removed the button from the modal, so UI is updated
      renderAll();
    }

    setTimeout(() => {
      alert('Prescription resumed successfully for ' + formatDate(date) + '.');
    }, 100);

    if (prescription.allocation_id) {
      // Server-side resume (happens in background)
      fetch(API_URL + '?action=resume_prescription', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ allocation_id: prescription.allocation_id, resume_date: date })
      }).then(r => {
        console.log('Server response status:', r.status);
        if (!r.ok) {
          return r.json().then(err => {
            console.error('Server error:', err);
            throw new Error(err.error || 'Server error');
          });
        }
        return r.json();
      }).then(j => {
        console.log('Server response:', j);
        if (j.status === 'ok') {
          // UI already updated above, alert already shown, server sync will happen in background

          // Then reload from server to get accurate updated cancelled dates and status_summary (in background)
          if (selectedPatient && prescription.allocation_id) {
            const patientRegNo = prescription.patient_reg_no || selectedPatient.pat_reg_no || selectedPatient.pat_op_reg_no;
            if (patientRegNo) {
              setTimeout(() => {
                ajax({ action: 'patient_prescriptions', patient_reg_no: patientRegNo }).then(list => {
                  if (list && Array.isArray(list)) {
                    // Use decoratePrescriptionList to properly preserve remembered actions
                    const decoratedList = decoratePrescriptionList(list);
                    const updated = decoratedList.find(pr => pr.allocation_id === prescription.allocation_id);
                    if (updated) {
                      // Preserve last_action before updating - use string keys to match storage
                      const key1 = prescription.allocation_id ? String(prescription.allocation_id) : null;
                      const key2 = prescription.id ? String(prescription.id) : null;
                      const rememberedAction = (key1 && prescriptionActionById[key1]) ||
                        (key2 && prescriptionActionById[key2]) || '';
                      // Update all fields from server response
                      Object.assign(prescription, updated);
                      // Restore last_action if it was remembered (always restore to preserve resumed/updated state)
                      // This is critical - we must restore the remembered action to preserve color coding
                      // The rememberedAction should already be 'resumed' since we set it before server call
                      if (rememberedAction) {
                        prescription.last_action = rememberedAction;
                        // Also update the stored action to ensure it persists
                        if (key1) {
                          rememberPrescriptionAction(key1, rememberedAction);
                        }
                      } else {
                        // If no remembered action but we just resumed, ensure it's set
                        // This handles edge cases where the action wasn't remembered properly
                        prescription.last_action = 'resumed';
                        if (key1) {
                          rememberPrescriptionAction(key1, 'resumed');
                        }
                      }
                      // Re-render to show updated color immediately
                      renderAll();
                      // Explicitly set cancelled dates (handle null/undefined/string 'null')
                      prescription.cancelled_date_from = (updated.cancelled_date_from && updated.cancelled_date_from !== 'null') ? updated.cancelled_date_from : null;
                      prescription.cancelled_date_to = (updated.cancelled_date_to && updated.cancelled_date_to !== 'null') ? updated.cancelled_date_to : null;
                      prescription.cancellation_reason = updated.cancellation_reason || '';
                      prescription.status = updated.status || prescription.status;
                      // Update status_summary if available
                      if (updated.status_summary) {
                        prescription.status_summary = updated.status_summary;
                      }
                      // Update UI again with server data
                      renderAll();

                      // For middle dates, don't reload modal automatically - button already removed optimistically
                      // Only reload if it's not a middle date (start/end dates update the range, so we need to reload)
                      // Check if this was a middle date resume
                      const wasMiddleDate = prescription.cancelled_date_from !== date && prescription.cancelled_date_to !== date;

                      if (!wasMiddleDate) {
                        // Start or end date - reload modal to show updated range
                        setTimeout(() => {
                          if ($resumeModal.is(':visible') && resumingPrescriptionIndex !== null) {
                            const currentPrescription = addedPrescriptions[resumingPrescriptionIndex];
                            if (currentPrescription && currentPrescription.cancelled_date_from && currentPrescription.cancelled_date_to &&
                              currentPrescription.cancelled_date_from !== 'null' && currentPrescription.cancelled_date_to !== 'null') {
                              // Reload modal with updated dates
                              openResumeModal(resumingPrescriptionIndex);
                            } else {
                              // No cancelled dates remaining - close modal
                              $resumeModal.hide();
                              resumingPrescriptionIndex = null;
                            }
                          }
                        }, 100);
                      }
                      // For middle dates, modal already has the button removed, so no need to reload
                    }
                  }
                }).catch(() => {
                  // Silently fail - UI already updated with local values
                  console.log('Failed to reload prescription data from server, using local values');
                  // Close modal if no cancelled dates remain (only if modal is still open)
                  setTimeout(() => {
                    if ($resumeModal.is(':visible') && resumingPrescriptionIndex !== null) {
                      const currentPrescription = addedPrescriptions[resumingPrescriptionIndex];
                      if (currentPrescription && currentPrescription.cancelled_date_from && currentPrescription.cancelled_date_to &&
                        currentPrescription.cancelled_date_from !== 'null' && currentPrescription.cancelled_date_to !== 'null') {
                        // Reload modal with current data
                        openResumeModal(resumingPrescriptionIndex);
                      } else {
                        // No cancelled dates remaining - close modal
                        $resumeModal.hide();
                        resumingPrescriptionIndex = null;
                      }
                    }
                  }, 100);
                });
              }, 500);
            }
          }
        } else {
          console.error('Resume failed:', j);
          alert('Failed: ' + JSON.stringify(j));
        }
      }).catch(err => {
        console.error('Resume error:', err);
        alert('Network error: ' + (err.message || 'Please try again.'));
      });
    } else {
      // Local resume - already updated above, just show message
      // (alert already shown above)
    }
  });

  $resumeCloseBtn.on('click', function () { $resumeModal.hide(); resumingPrescriptionIndex = null; });

  // export JSON
  $('#export-json').on('click', function () {
    const patient = $patientSelect.val() || '';
    const payload = { patient_reg_no: patient, prescriptions: addedPrescriptions };
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a'); a.href = url; a.download = (patient ? patient + '-' : 'prescriptions-') + (new Date().toISOString().slice(0, 10)) + '.json'; document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url);
  });

  // initial render
  renderAll();

  // Initialize UnitNo dropdown
  loadUnitNumbers();

  // Clear form button
  $('#clear-form').on('click', function () {
    resetFormState();
  });

  // --- Past History Feature ---
  const $historyModal = $('#history-modal-backdrop');

  $('#past-history-btn').on('click', function () {
    if (!selectedPatient) {
      alert('Please select a patient first.');
      return;
    }

    // Open modal
    $historyModal.addClass('show');
    $historyModal.css('display', 'flex'); // Ensure flex display for modal
    $('#history-patient-name').text((selectedPatient.pat_name || 'Unknown') + ' (' + (selectedPatient.pat_reg_no || selectedPatient.pat_op_reg_no) + ')');

    // Load data
    loadPrescriptionHistory();
  });

  $('#history-modal-close').on('click', function () {
    $historyModal.removeClass('show');
    $historyModal.hide();
  });

  function loadPrescriptionHistory() {
    const regNo = selectedPatient.pat_reg_no || selectedPatient.pat_op_reg_no;

    $('#history-content-loader').show();
    $('#history-content-empty').hide();
    $('#history-list').empty();

    fetch(`/sheduling/prescription/api/previous-history/?registration_no=${encodeURIComponent(regNo)}`)
      .then(r => r.json())
      .then(resp => {
        $('#history-content-loader').hide();

        if (!resp.success || !resp.data || resp.data.length === 0) {
          $('#history-content-empty').show();
          return;
        }

        renderHistoryList(resp.data, resp.previous_doa, resp.doctor_name);
      })
      .catch(err => {
        $('#history-content-loader').hide();
        const errMsg = err.message || 'Unknown error';
        $('#history-list').html(`<div style="color:red;padding:20px;text-align:center">Error loading history: ${errMsg}. Please try again.</div>`);
        console.error('History API error:', err);
      });
  }

  function renderHistoryList(historyData, previousDoa, doctorName) {
    const doaHtml = previousDoa ? `
      <div style="background: #f1f5f9; padding: 10px 15px; border-radius: 6px; margin-bottom: 25px; border-left: 4px solid #3b82f6; display: flex; align-items: center; gap: 20px; flex-wrap: wrap;">
        <div style="display: flex; align-items: center;">
          <span style="font-size: 0.85em; color: #64748b; text-transform: uppercase; letter-spacing: 0.05em; font-weight: 700;">PREVIOUS DOA:</span>
          <span style="font-size: 1em; color: #1e293b; font-weight: 800; margin-left: 8px;">${previousDoa}</span>
        </div>
        <div style="height: 15px; width: 1px; background: #cbd5e1;"></div>
        <div style="display: flex; align-items: center;">
          <span style="font-size: 0.85em; color: #64748b; text-transform: uppercase; letter-spacing: 0.05em; font-weight: 700;">DOCTOR:</span>
          <span style="font-size: 1em; color: #1e293b; font-weight: 800; margin-left: 8px;">${esc(doctorName) || 'N/A'}</span>
        </div>
      </div>
    ` : '';

    const html = historyData.map((dateGroup, dateIdx) => {
      const date = formatDate(dateGroup.date);

      // Collect ALL rows from all prescriptions for this date into a single list of rows
      const allRows = [];
      dateGroup.prescriptions.forEach((pres) => {
        const allItems = pres.items;
        if (!allItems || allItems.length === 0) return;

        // Sort items by seq1 to ensure order (1,1 before 1,2)
        // Group by seq1
        const seq1Groups = {};
        allItems.forEach(it => {
          const s1 = it.seq1 || 0;
          if (!seq1Groups[s1]) seq1Groups[s1] = [];
          seq1Groups[s1].push(it);
        });

        const sortedSeq1List = Object.keys(seq1Groups).sort((a, b) => Number(a) - Number(b));

        const medCombined = sortedSeq1List.map(s1 => {
          const g = seq1Groups[s1];
          const names = g.map(it => esc(it.item_name)).join(' + ');
          const firstIt = g[0];
          const dosage = (esc(firstIt.dosage) || '').trim();
          const uom = (esc(firstIt.uom) || '').trim();

          let res = `<b>[${names}]</b>`;
          if (dosage) res += ` ${dosage}`;
          if (uom) res += ` ${uom}`;

          const allIngreds = g.map(it => it.ingred).filter(ig => {
            const val = esc(ig).trim();
            return val !== '' && val !== '-';
          });
          if (allIngreds.length > 0) {
            const uniqueIngreds = [...new Set(allIngreds)].join(', ');
            res += `<span style="font-size: 0.8em; color: #888; font-style: italic;"> (${esc(uniqueIngreds)})</span>`;
          }
          return res;
        }).join(' + ');

        // Usage & Ext/Int from first item in this prescription session
        const firstIt = allItems[0];
        const usage = (esc(firstIt.usage).trim() !== '-' && esc(firstIt.usage).trim() !== '') ? firstIt.usage : '-';
        const extInt = (esc(firstIt.int_ext).trim() !== '-' && esc(firstIt.int_ext).trim() !== '') ? firstIt.int_ext : '-';

        const extIntLower = (extInt || '').toLowerCase();
        const badgeClass = extIntLower.includes('ext') ? 'bg-info' : (extIntLower.includes('int') ? 'bg-primary' : 'bg-secondary');

        allRows.push(`
          <tr>
            <td style="padding: 12px 15px; border-bottom: 1px solid #edf2f7; vertical-align: middle;">
              <div style="color: #334155; line-height: 1.6;">${medCombined}</div>
            </td>
            <td style="padding: 12px 15px; border-bottom: 1px solid #edf2f7; text-align: center; color: #475569; font-weight: 600; vertical-align: middle;">${esc(usage)}</td>
            <td style="padding: 12px 15px; border-bottom: 1px solid #edf2f7; text-align: center; vertical-align: middle;">
              <span class="badge ${badgeClass}" style="font-size: 10px; padding: 5px 10px; border-radius: 6px; text-transform: uppercase; font-weight: 700;">${esc(extInt)}</span>
            </td>
          </tr>
        `);
      });

      const tableHtml = `
        <div style="background: #fff; border: 1px solid #e2e8f0; border-radius: 10px; box-shadow: 0 2px 4px rgba(0,0,0,0.02); overflow: hidden; margin-bottom: 15px;">
          <div style="overflow-x: auto;">
            <table style="width: 100%; border-collapse: collapse;">
              <thead style="background: #f0f9f1;">
                <tr>
                  <th style="padding: 12px 15px; text-align: left; color: #4a5568; font-size: 0.75em; text-transform: uppercase; letter-spacing: 0.05em; border-bottom: 2px solid #e2e8f0; width: 60%;">Medicine</th>
                  <th style="padding: 12px 15px; text-align: center; color: #4a5568; font-size: 0.75em; text-transform: uppercase; letter-spacing: 0.05em; border-bottom: 2px solid #e2e8f0; width: 25%;">Usage</th>
                  <th style="padding: 12px 15px; text-align: center; color: #4a5568; font-size: 0.75em; text-transform: uppercase; letter-spacing: 0.05em; border-bottom: 2px solid #e2e8f0; width: 15%;">Ext/Int</th>
                </tr>
              </thead>
              <tbody>
                ${allRows.join('')}
              </tbody>
            </table>
          </div>
        </div>
      `;

      return `
        <div class="history-date-section" style="margin-bottom: 35px; border-left: 4px solid #48bb78; padding-left: 20px;">
          <div style="display: flex; align-items: center; margin-bottom: 15px; padding: 6px 12px; background: #f0f9f1; border-radius: 6px; display: inline-flex;">
            <i class="fas fa-calendar-alt" style="margin-right: 8px; color: #48bb78; font-size: 0.9em;"></i>
            <span style="font-size: 1.1em; font-weight: 850; color: #1e293b;">${date}</span>
            <span style="margin-left: 12px; font-size: 0.8em; color: #64748b; font-weight: 600;">(${dateGroup.prescriptions.reduce((acc, p) => acc + p.items.length, 0)} Items)</span>
          </div>
          ${tableHtml}
          ${dateIdx < historyData.length - 1 ? '<hr style="border: 0; border-top: 1px dashed #e2e8f0; margin: 30px 0 20px -20px;">' : ''}
        </div>
      `;
    }).join('');

    $('#history-list').html(doaHtml + (html || '<div class="empty-state" style="text-align:center; padding: 60px 20px; color: #94a3b8;"><i class="fas fa-notes-medical fa-4x" style="margin-bottom: 20px; opacity: 0.3;"></i><h3>No Prescription History Found</h3><p>Records will appear here once the patient has received prescriptions.</p></div>'));
  }

  function triggerDownload(url) {
    const frame = document.createElement('iframe');
    frame.style.display = 'none';
    frame.src = url;
    document.body.appendChild(frame);
    setTimeout(() => frame.remove(), 1000 * 60); // Clean up after 1 min
  }

  $('#download-history-pdf').on('click', function () {
    if (!selectedPatient) return;
    const regNo = selectedPatient.pat_reg_no || selectedPatient.pat_op_reg_no;
    triggerDownload(`/sheduling/prescription/api/download-history/?registration_no=${encodeURIComponent(regNo)}&format=pdf`);
  });

  $('#download-history-excel').on('click', function () {
    if (!selectedPatient) return;
    const regNo = selectedPatient.pat_reg_no || selectedPatient.pat_op_reg_no;
    triggerDownload(`/sheduling/prescription/api/download-history/?registration_no=${encodeURIComponent(regNo)}&format=excel`);
  });

  // expose for debug
  window._prescriptionApp = { addedPrescriptions, itemGroups, renderAll };

  // ========== STATUS MODAL LOGIC ==========
  const $statusModalBackdrop = $('#status-modal-backdrop');
  $('#status-modal-close').on('click', () => $statusModalBackdrop.hide().removeClass('show'));

  $prescriptionsTableBody.on('click', '.status-prescription', function () {
    const rx = addedPrescriptions[$(this).data('i')];
    if (!rx) return;
    const allocationId = rx.allocation_id || rx.id;
    if (!allocationId) {
      alert('Cannot fetch status for unsaved prescription.');
      return;
    }
    
    // Set info text
    const patientName = selectedPatient ? (selectedPatient.pat_name || '') : '';
    $('#status-modal-info').html(`
      <strong>Patient:</strong> ${esc(patientName)} &bull; 
      <strong>Medicine:</strong> ${esc(rx.prescription_name || 'Prescription')}
    `);
    
    const $tbody = $('#status-modal-tbody');
    $tbody.html('<tr><td colspan="5" style="text-align:center;"><i class="fas fa-spinner fa-spin"></i> Loading day-by-day history...</td></tr>');
    $statusModalBackdrop.show().addClass('show');
    
    ajax({ action: 'status_history', allocation_id: allocationId }).then(res => {
      if (res.status === 'ok' && res.history) {
        $tbody.empty();
        if (res.history.length === 0) {
          $tbody.html('<tr><td colspan="5" style="text-align:center;">No history found.</td></tr>');
          return;
        }
        res.history.forEach(item => {
          // Format date as DD-MM-YYYY
          const dateParts = item.date.split('-');
          const displayDate = dateParts.length === 3 ? `${dateParts[2]}-${dateParts[1]}-${dateParts[0]}` : item.date;
          
          let statusBadgeClass = '';
          const s = item.status || 'Original';
          if (s.includes('Original')) statusBadgeClass = 'status-active';
          else if (s.includes('Updated')) statusBadgeClass = 'status-draft';
          else if (s.includes('Cancelled')) statusBadgeClass = 'status-cancelled';
          else if (s.includes('Dispatched')) statusBadgeClass = 'status-active';
          else statusBadgeClass = 'status-draft';
          
          // Render row with combined medicine and ingredients
          $tbody.append(`
            <tr>
              <td style="white-space:nowrap;">${esc(displayDate)}</td>
              <td style="line-height:1.4; font-weight:500; color:var(--primary);">${item.medicine}</td>
              <td style="font-size:0.85em; color:#666;">${esc(item.ingredients || '—')}</td>
              <td>${esc(item.usage || '')}</td>
              <td><span class="status-pill ${statusBadgeClass}">${esc(s)}</span></td>
            </tr>
          `);
        });
      } else {
        $tbody.html(`<tr><td colspan="5" style="text-align:center;color:red;">Failed to load history: ${esc(res.error || 'Unknown error')}</td></tr>`);
      }

    }).catch(err => {
      $tbody.html(`<tr><td colspan="5" style="text-align:center;color:red;">Error fetching history</td></tr>`);
      console.error(err);
    });
  });

});