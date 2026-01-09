$(function () {
  // --- config/fallbacks ---
  const API_URL = window.location.pathname;
  const FALLBACK_PROCURED = [{ name: 'IP Pharmacy' }, { name: 'Kashaya room' }];

  // --- helpers ---
  function ajax(params) {
    const url = API_URL + '?' + $.param(params);
    return fetch(url).then(r => { if (!r.ok) throw new Error('Network'); return r.json(); });
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
  function rememberPrescriptionAction(id, action) {
    if (!id) return;
    // Store with string key to ensure matching
    const key = String(id);
    prescriptionActionById[key] = action;
  }
  function decoratePrescriptionList(list) {
    return (list || []).map(p => {
      // Try multiple key formats to match what we stored
      const key1 = p.allocation_id ? String(p.allocation_id) : null;
      const key2 = p.id ? String(p.id) : null;
      const remembered = (key1 && prescriptionActionById[key1]) ||
        (key2 && prescriptionActionById[key2]) || '';
      // Only use derived from server if it's 'cancelled' (server knows cancellation state)
      // Otherwise, ignore server's last_action and use remembered
      const derived = (p.status === 'cancelled' ? 'cancelled' : '') ||
        (p.last_action === 'cancelled' ? 'cancelled' : '');
      // Priority: remembered > derived (only cancelled)
      let finalAction = remembered || derived;
      return { ...p, last_action: finalAction };
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
    // Clear previous patient's data first
    addedPrescriptions = [];
    itemGroups = [];
    editPrescriptionIndex = null;
    cancelingPrescriptionIndex = null;
    resumingPrescriptionIndex = null;
    // Clear remembered actions when switching patients to avoid stale data
    prescriptionActionById = {};

    // Reset form state
    resetFormState();

    $('#header-patient-select').val(patient.pat_op_reg_no || patient.pat_reg_no);
    // Make patient name bold/highlighted
    $('#hdr-pat-name').html(`<strong style="font-weight: bold; color: var(--primary);">${patient.pat_name || 'Unknown'}</strong>`);
    updatePatientAvatar(patient);

    // Load patient prescriptions
    const patientRegNo = patient.pat_op_reg_no || patient.pat_reg_no;
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
          // Format for Select2
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
    }
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
    setTimeout(updateProcuredFromField, 100);
  });

  // Add Group
  $('#add-item-group-btn').on('click', function () {
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
      return;
    }

    const items = selected.length > 0 ? selected.map(s => ({ item_code: s.id, item_name: s.text || s.id })) : [];
    const grp = { id: Math.random().toString(36).slice(2, 9), items, dosage, time, uno, oil_class: oilClass, procured_from: procuredFrom, ingredients, ingredient_ids: ingredientIds };
    itemGroups.push(grp);
    $itemBuilder.val(null).trigger('change');
    $('#item-builder-dosage').val('');
    $('#item-builder-time').val('');
    $('#item-builder-uno').val('');
    $itemBuilderOilClass.val('');
    $itemBuilderProcuredFrom.val('');
    ingredientInput.val(''); // Clear text input
    renderItemGroups();
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

  $itemGroupsList.on('click', '.remove-group', function () {
    const id = $(this).data('id');
    itemGroups = itemGroups.filter(g => g.id !== id);
    renderItemGroups();
  });

  $itemGroupsList.on('click', '.edit-group', function () {
    const id = $(this).data('id');
    const g = itemGroups.find(x => x.id === id);
    if (!g) return;
    $itemBuilder.val(null).trigger('change');
    g.items.forEach(it => {
      const opt = new Option(it.item_name, it.item_code, true, true);
      $itemBuilder.append(opt);
    });
    $itemBuilder.trigger('change');
    $('#item-builder-dosage').val(g.dosage || '');
    $('#item-builder-time').val(g.time || '');
    $('#item-builder-uno').val(g.uno || '');
    $itemBuilderOilClass.val(g.oil_class || '');
    $itemBuilderProcuredFrom.val(g.procured_from || '');
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
    itemGroups = itemGroups.filter(x => x.id !== id);
    renderItemGroups();
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

    // Save directly to server as draft
    const payload = {
      patient_reg_no: selectedPatient.pat_op_reg_no || selectedPatient.pat_reg_no,
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

        // Reload patient prescriptions from server to get accurate status counts
        // Use the same registration number format that was used to save
        if (selectedPatient) {
          const patientRegNo = selectedPatient.pat_op_reg_no || selectedPatient.pat_reg_no;
          // Small delay to ensure server has processed the save
          setTimeout(() => {
            ajax({ action: 'patient_prescriptions', patient_reg_no: patientRegNo }).then(list => {
              if (list && Array.isArray(list)) {
                addedPrescriptions = decoratePrescriptionList(list);
                renderAll();
                alert('Prescription saved to server as Draft.');
              } else {
                // If list is empty or invalid, show error but don't break
                addedPrescriptions = [];
                renderAll();
                alert('Prescription saved to server as Draft. (Note: Could not load updated prescription list - please refresh)');
              }
            }).catch(err => {
              console.error('Error reloading prescriptions:', err);
              // Clear and show empty state if reload fails
              addedPrescriptions = [];
              renderAll();
              alert('Prescription saved to server as Draft. (Note: Could not refresh prescription list - please refresh page)');
            });
          }, 300); // 300ms delay to ensure server has processed
        } else {
          addedPrescriptions = [];
          renderAll();
          alert('Prescription saved to server as Draft.');
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
    const today = new Date().toISOString().slice(0, 10);

    const inMainRange =
      p.from_date && p.to_date &&
      today >= String(p.from_date) && today <= String(p.to_date);

    if (!inMainRange) {
      return '';
    }

    // Get the last action - this is the CURRENT state set by user actions
    const lastAction = String(p.last_action || '').toLowerCase().trim();

    // PRIORITY 1: If last_action is explicitly set, it ALWAYS wins
    // This ensures Cancel → Resume → Cancel works correctly
    if (lastAction === 'cancelled') return 'action-cancelled';
    if (lastAction === 'resumed') return 'action-resumed';
    if (lastAction === 'updated') return 'action-updated';
    if (lastAction === 'added') return 'action-added';

    // PRIORITY 2: Fall back to checking if today is in cancelled range
    const inCancelledRange =
      p.cancelled_date_from && p.cancelled_date_to &&
      p.cancelled_date_from !== 'null' && p.cancelled_date_to !== 'null' &&
      today >= String(p.cancelled_date_from) && today <= String(p.cancelled_date_to);

    if (inCancelledRange) {
      return 'action-cancelled';
    }

    // PRIORITY 3: Check timestamps from server for "today" actions (only if no last_action)
    const isTodayResumed = p.resumed_at && p.resumed_at.slice(0, 10) === today;
    const isTodayCancelled = p.cancelled_at && p.cancelled_at.slice(0, 10) === today;
    const isTodayUpdated = p.updated_at && p.updated_at.slice(0, 10) === today &&
      p.updated_at !== p.created_at;
    const isTodayAdded = p.created_at && p.created_at.slice(0, 10) === today;

    if (isTodayResumed) return 'action-resumed';
    if (isTodayCancelled) return 'action-cancelled';
    if (isTodayUpdated) return 'action-updated';
    if (isTodayAdded) return 'action-added';

    return '';
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

    itemGroups = (p.items_groups || []).map(g => ({
      id: Math.random().toString(36).slice(2, 9),
      items: g.items || [],
      dosage: g.dosage || '',
      time: g.time || '',
      uno: g.uno || '',
      oil_class: g.oil_class || '',
      procured_from: g.procured_from || '',
      ingredient_ids: g.ingredient_ids || [],
      ingredients: g.ingredients || []
    }));
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

      fetch(API_URL + '?action=update_prescription', {
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
        if (j.status === 'ok') {
          // Check if today is cancelled or resumed BEFORE marking as updated
          const today = new Date().toISOString().slice(0, 10);
          const todayIsCancelled = p.cancelled_date_from && p.cancelled_date_to &&
            p.cancelled_date_from !== 'null' && p.cancelled_date_to !== 'null' &&
            today >= p.cancelled_date_from && today <= p.cancelled_date_to;
          const todayIsResumed = p.resumed_at && p.resumed_at.slice(0, 10) === today;

          // Priority: Cancelled > Resumed > Updated
          if (todayIsCancelled) {
            // Today is cancelled - keep RED color
            p.last_action = 'cancelled';
            rememberPrescriptionAction(p.allocation_id || p.id, 'cancelled');
          } else if (todayIsResumed) {
            // Today is resumed - keep GREEN color
            p.last_action = 'resumed';
            rememberPrescriptionAction(p.allocation_id || p.id, 'resumed');
          } else {
            // Today is not cancelled/resumed - mark as updated (YELLOW)
            p.last_action = 'updated';
            rememberPrescriptionAction(p.allocation_id || p.id, 'updated');
          }

          // Render immediately to show correct color
          renderAll();
          alert('Prescription updated successfully on server.');
          resetFormState();

          // Reload from server to get updated data, but preserve last_action
          if (selectedPatient && p.allocation_id) {
            const patientRegNo = selectedPatient.pat_op_reg_no || selectedPatient.pat_reg_no;
            if (patientRegNo) {
              ajax({ action: 'patient_prescriptions', patient_reg_no: patientRegNo }).then(list => {
                if (list && Array.isArray(list)) {
                  // Use decoratePrescriptionList to preserve remembered actions
                  const decoratedList = decoratePrescriptionList(list);
                  // Find and update the specific prescription to preserve the reference
                  const updatedPrescription = decoratedList.find(pr => pr.allocation_id === p.allocation_id);
                  if (updatedPrescription) {
                    // Update all fields from server, but preserve last_action
                    Object.assign(p, updatedPrescription);
                    // Ensure last_action is preserved (decoratePrescriptionList should have set it)
                    const rememberedAction = prescriptionActionById[String(p.allocation_id || p.id || '')];
                    if (rememberedAction) {
                      p.last_action = rememberedAction;
                    }
                  } else {
                    // If not found, replace entire array
                    addedPrescriptions = decoratedList;
                  }
                  renderAll();
                } else {
                  renderAll();
                }
              }).catch(() => {
                // If reload fails, use local values (already rendered above)
                renderAll();
              });
            } else {
              renderAll();
            }
          } else {
            renderAll();
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
    itemGroups = []; renderItemGroups();
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

    // Only set last_action to 'cancelled' if TODAY is in the cancelled range
    // This ensures cancelling future dates doesn't turn the row red
    const today = new Date().toISOString().slice(0, 10);
    const todayIsCancelled = today >= cfrom && today <= cto;

    if (todayIsCancelled) {
      // Today is cancelled - turn row RED
      p.last_action = 'cancelled';
      rememberPrescriptionAction(p.allocation_id || p.id, 'cancelled');
    }
    // If today is NOT cancelled, don't change last_action
    // This preserves the previous color (green/yellow/blue)

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

          // Then reload from server to get merged cancellation dates (in background)
          if (p.allocation_id && selectedPatient) {
            const patientRegNo = selectedPatient.pat_op_reg_no || selectedPatient.pat_reg_no;
            if (patientRegNo) {
              setTimeout(() => {
                ajax({ action: 'patient_prescriptions', patient_reg_no: patientRegNo }).then(list => {
                  if (list && Array.isArray(list)) {
                    const updated = list.find(pr => pr.allocation_id === p.allocation_id);
                    if (updated) {
                      // Get the remembered action before updating
                      const rememberedAction = prescriptionActionById[p.allocation_id || p.id];

                      // Update all fields from server response
                      Object.assign(p, updated);

                      // Explicitly set cancelled dates (handle null/undefined/string 'null')
                      p.cancelled_date_from = (updated.cancelled_date_from && updated.cancelled_date_from !== 'null') ? updated.cancelled_date_from : null;
                      p.cancelled_date_to = (updated.cancelled_date_to && updated.cancelled_date_to !== 'null') ? updated.cancelled_date_to : null;
                      p.cancellation_reason = updated.cancellation_reason || '';
                      p.status = updated.status || p.status;

                      // Update status_summary if available
                      if (updated.status_summary) {
                        p.status_summary = updated.status_summary;
                      }

                      // Check if today is in the cancelled range
                      const today = new Date().toISOString().slice(0, 10);
                      const todayIsCancelled = p.cancelled_date_from && p.cancelled_date_to &&
                        p.cancelled_date_from !== 'null' && p.cancelled_date_to !== 'null' &&
                        today >= p.cancelled_date_from && today <= p.cancelled_date_to;

                      // If today is cancelled, override any previous action with 'cancelled'
                      if (todayIsCancelled) {
                        p.last_action = 'cancelled';
                        rememberPrescriptionAction(p.allocation_id || p.id, 'cancelled');
                      } else if (rememberedAction && rememberedAction !== 'cancelled') {
                        // If today is NOT cancelled, restore the remembered action (updated/resumed/added)
                        // but only if it's not 'cancelled' (we just cancelled, so don't restore old cancelled state)
                        p.last_action = rememberedAction;
                      }

                      // Update UI again with server data
                      renderAll();
                    }
                  }
                }).catch(() => {
                  // Silently fail - UI already updated with local values
                  console.log('Failed to reload prescription data from server, using local values');
                });
              }, 500);
            }
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

  // expose for debug
  window._prescriptionApp = { addedPrescriptions, itemGroups, renderAll };
});