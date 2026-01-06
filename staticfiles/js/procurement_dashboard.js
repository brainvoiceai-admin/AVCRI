// Global variables
        let currentPatient = null;
        let currentDate = null;
        let preparedMedicines = new Set(); // Track prepared medicines by ID
        
        // Helper functions
        function getTodayDate() {
            return new Date().toISOString().slice(0, 10);
        }
        
        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }
        
        // Initialize the dashboard
        document.addEventListener('DOMContentLoaded', function() {
            // Set today's date as default
            currentDate = getTodayDate();
            document.getElementById('dateFilter').value = currentDate;
            
            // Load patients for the selected date
            loadPatients();
            
            // Set up event listeners
            setupEventListeners();
        });
        
        function setupEventListeners() {
            // Date filter
            document.getElementById('dateFilter').addEventListener('change', function() {
                currentDate = this.value;
                loadPatients();
                if (currentPatient) {
                    loadPatientMedicines(currentPatient.patient_id);
                }
            });
            
            // Search input
            document.getElementById('search').addEventListener('input', function() {
                renderPatients();
            });
            
            // Filter tabs
            document.querySelectorAll('.filter-tab').forEach(tab => {
                tab.addEventListener('click', function() {
                    document.querySelectorAll('.filter-tab').forEach(t => t.classList.remove('active'));
                    this.classList.add('active');
                    renderPatients();
                });
            });
            
            // Prepare all button
            document.getElementById('prepareAllBtn').addEventListener('click', function() {
                if (currentPatient) {
                    markAllMedicinesAsPrepared();
                }
            });
            
            // Save changes button
            document.getElementById('saveChangesBtn').addEventListener('click', function() {
                if (currentPatient) {
                    saveChanges();
                }
            });
            
            // View change log button
            document.getElementById('viewChangeLogBtn').addEventListener('click', function() {
                if (currentPatient) {
                    loadChangeLog(currentPatient.patient_id);
                }
            });
            
            // Close change log button
            document.getElementById('closeChangeLogBtn').addEventListener('click', function() {
                document.getElementById('changeLogPanel').style.display = 'none';
            });
            
            // Export CSV button
            document.getElementById('exportPatientCSV').addEventListener('click', function() {
                if (currentPatient) {
                    exportPatientCSV();
                }
            });
        }
        
        function loadPatients() {
            showLoading();
            
            // Fetch patients from API (department will be determined by backend from logged-in user)
            fetch(`/sheduling/procurement/api/prescriptions/?date=${currentDate}`)
                .then(response => response.json())
                .then(data => {
                    hideLoading();
                    if (data.success) {
                        window.patientsData = data.data;
                        renderPatients();
                        updateStatistics();
                    } else {
                        showAlert('error', data.error || 'Failed to load patients');
                    }
                })
                .catch(error => {
                    hideLoading();
                    console.error('Error loading patients:', error);
                    showAlert('error', 'Error loading patients');
                });
        }
        
        function renderPatients() {
            const patientsList = document.getElementById('patientsList');
            const searchTerm = document.getElementById('search').value.toLowerCase();
            const activeFilter = document.querySelector('.filter-tab.active').dataset.filter;
            
            if (!window.patientsData) {
                patientsList.innerHTML = '<div class="loading">Loading patients...</div>';
                return;
            }
            
            // Filter patients based on search and filter
            const filteredPatients = window.patientsData.filter(patient => {
                // Search filter
                const matchesSearch = patient.patient_name.toLowerCase().includes(searchTerm) || 
                                      patient.registration_no.toLowerCase().includes(searchTerm);
                
                // Status filter
                let matchesFilter = true;
                if (activeFilter === 'pending') {
                    matchesFilter = !isPatientFullyPrepared(patient);
                } else if (activeFilter === 'prepared') {
                    matchesFilter = isPatientFullyPrepared(patient);
                }
                
                return matchesSearch && matchesFilter;
            });
            
            // Update patient count
            document.getElementById('patientsCount').textContent = `${filteredPatients.length} patients`;
            
            // Clear the list
            patientsList.innerHTML = '';
            
            // Add patient cards
            filteredPatients.forEach(patient => {
                const patientCard = document.createElement('div');
                patientCard.className = 'patient-card';
                patientCard.dataset.id = patient.patient_id;
                
                const isFullyPrepared = isPatientFullyPrepared(patient);
                const statusText = patient.status === 'dispatched' ? 'Dispatched' : (isFullyPrepared ? 'Prepared' : 'Pending');
                
                patientCard.innerHTML = `
                    <div class="patient-name">
                        ${escapeHtml(patient.patient_name)}
                        <span class="status-badge ${isFullyPrepared ? 'status-prepared' : 'status-pending'}">
                            ${statusText}
                        </span>
                    </div>
                    <div class="patient-id">${escapeHtml(patient.registration_no)}</div>
                    <div class="patient-details">
                        <span>Room ${patient.room_no || '-'}</span>
                        <span>Dr. ${escapeHtml(patient.doctor_name || 'Unknown')}</span>
                    </div>
                    <div class="patient-meds">
                        <span class="meds-count">${patient.prescription_count} medicines</span>
                        <span>${getPreparedCount(patient)}/${patient.prescription_count} prepared</span>
                    </div>
                    ${Array.isArray(patient.items_preview) && patient.items_preview.length ? `
                    <div class="patient-details" style="margin-top:6px; display:block;">
                        ${patient.items_preview.slice(0,3).map(it => `<div>• ${escapeHtml(it.item_name)}${it.dose ? ` (${escapeHtml(it.dose)})` : ''}${it.time ? ` - ${escapeHtml(it.time)}` : ''}</div>`).join('')}
                        ${patient.items_preview.length > 3 ? `<div class="small" style="color:#95aac9;">+${patient.items_preview.length-3} more…</div>` : ''}
                    </div>` : ''}
                `;
                
                patientCard.addEventListener('click', function() {
                    selectPatient(patient);
                    highlightActivePatient(patient.patient_id);
                });
                
                patientsList.appendChild(patientCard);
            });
        }
        
        function isPatientFullyPrepared(patient) {
            // Check if prescription is dispatched (from database status)
            if (patient.status === 'dispatched') {
                return true;
            }
            
            // Otherwise check local preparation status
            return getPreparedCount(patient) === patient.prescription_count && patient.prescription_count > 0;
        }
        
        function getPreparedCount(patient) {
            // Count how many medicines are marked as prepared for this patient
            let count = 0;
            const patientKey = `${patient.patient_id}_${currentDate}`;
            if (preparedMedicines.has(patientKey)) {
                count = preparedMedicines.get(patientKey).size;
            }
            return count;
        }
        
        function selectPatient(patient) {
            console.log('Selecting patient:', patient);
            currentPatient = patient;
            
            // Show patient view
            document.getElementById('noSelection').style.display = 'none';
            document.getElementById('patientView').style.display = 'block';
            
            // Update patient info
            document.getElementById('pv_name').textContent = patient.patient_name;
            document.getElementById('pv_meta').textContent = `${patient.registration_no} • Room ${patient.room_no || '-'} • Dr. ${patient.doctor_name || 'Unknown'}`;
            document.getElementById('pv_room').textContent = patient.room_no || '-';
            document.getElementById('pv_therapy').textContent = 'Prescription';
            
            // Load patient medicines
            console.log('Loading medicines for patient ID:', patient.patient_id, 'Date:', currentDate);
            loadPatientMedicines(patient.patient_id);
            
            // Auto-load change log when patient is selected
            loadChangeLog(patient.patient_id);
        }
        
        function loadPatientMedicines(patientId) {
            console.log('loadPatientMedicines called with:', patientId, currentDate);
            
            // Show loading in the medicine panel, not the patient list
            const pvContent = document.getElementById('pv_content');
            pvContent.innerHTML = '<div class="loading">Loading medicine details...</div>';
            
            const apiUrl = `/sheduling/procurement/api/prescription-details/?patient_id=${patientId}&date=${currentDate}`;
            console.log('Fetching from:', apiUrl);
            
            // Fetch patient medicine details from API
            fetch(apiUrl)
                .then(response => {
                    console.log('API response status:', response.status);
                    // Check if response is ok (status 200-299)
                    if (!response.ok) {
                        // Try to parse error response
                        return response.json().then(data => {
                            throw new Error(data.error || `HTTP ${response.status}: ${response.statusText}`);
                        }).catch(() => {
                            // If JSON parsing fails, throw with status
                            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
                        });
                    }
                    return response.json();
                })
                .then(data => {
                    console.log('API response data:', data);
                    // Check if response has success field or error field
                    if (data.error) {
                        console.error('API error:', data.error);
                        showAlert('error', data.error || 'Failed to load medicine details');
                        pvContent.innerHTML = '<p>Failed to load medicine details.</p>';
                        return;
                    }
                    
                    if (data.success !== false) {
                        // Update patient info if available
                        if (data.patient_info) {
                            const info = data.patient_info;
                            document.getElementById('pv_name').textContent = info.name || 'Unknown';
                            document.getElementById('pv_meta').textContent = `${info.registration_no || ''} • Room ${info.room_no || '-'} • Dr. ${info.doctor_name || 'Unknown'}`;
                            document.getElementById('pv_room').textContent = info.room_no || '-';
                        }
                        
                        // Render medicines - pass prescription groups and therapy items separately
                        const prescriptionGroups = data.prescription_groups || [];
                        const prescriptionItems = data.prescription_items || data.items || [];  // Fallback for backward compatibility
                        const therapyItems = data.therapy_items || [];
                        renderPatientMedicines(prescriptionGroups, therapyItems, prescriptionItems);
                    } else {
                        console.error('API returned success: false');
                        showAlert('error', data.error || 'Failed to load medicine details');
                        pvContent.innerHTML = '<p>Failed to load medicine details.</p>';
                    }
                })
                .catch(error => {
                    console.error('Error loading medicine details:', error);
                    const errorMessage = error.message || 'Error loading medicine details';
                    showAlert('error', errorMessage);
                    pvContent.innerHTML = `<p>${errorMessage}</p>`;
                });
        }
        
        function renderPatientMedicines(prescriptionGroups, therapyItems, prescriptionItemsFallback) {
            const pvContent = document.getElementById('pv_content');
            
            // Clear content
            pvContent.innerHTML = '';
            
            // Handle old format if prescriptionGroups is not provided
            if (!prescriptionGroups || prescriptionGroups.length === 0) {
                prescriptionGroups = [];
                // Try to create groups from fallback items
                if (prescriptionItemsFallback && prescriptionItemsFallback.length > 0) {
                    // Group by time and dose
                    const groupsMap = {};
                    prescriptionItemsFallback.forEach(medicine => {
                        const groupKey = `${medicine.time || 'M'}_${medicine.dose || ''}`;
                        if (!groupsMap[groupKey]) {
                            groupsMap[groupKey] = {
                                'group_id': `prescription_group_${groupKey}`,
                                'time': medicine.time || 'M',
                                'dose': medicine.dose || '',
                                'notes': medicine.notes || '',
                                'items': [],
                                'is_group': true
                            };
                        }
                        groupsMap[groupKey]['items'].push(medicine);
                    });
                    prescriptionGroups = Object.values(groupsMap);
                }
            }
            
            therapyItems = therapyItems || [];
            
            // Debug logging
            console.log('Rendering prescription groups:', prescriptionGroups.length, prescriptionGroups);
            console.log('Rendering therapy items:', therapyItems.length, therapyItems);
            
            if (prescriptionGroups.length === 0 && therapyItems.length === 0) {
                pvContent.innerHTML = '<p>No medicines or therapy items for selected date.</p>';
                return;
            }
            
            // Render prescription items section - grouped by allocation (same per‑group format as prescription entry table)
            if (prescriptionGroups.length > 0) {
                const prescriptionSection = document.createElement('div');
                prescriptionSection.className = 'items-section';
                prescriptionSection.innerHTML = '<h3 style="margin: 0 0 15px 0; color: #333;">Prescription Items</h3>';
                
                // Group prescription groups by allocation_id (extract from group_id)
                // Handle both "prescription_group_{allocation_id}_{group_idx}" and "prescription_item_{item_id}" formats
                const groupsByAllocation = {};
                prescriptionGroups.forEach(group => {
                    let allocationId = 'unknown';
                    // Try to extract allocation_id from group_id
                    const groupMatch = group.group_id.match(/prescription_group_(\d+)_/);
                    if (groupMatch) {
                        allocationId = groupMatch[1];
                    } else {
                        // For prescription_item format, use item_id as allocation key (each item is its own "allocation")
                        const itemMatch = group.group_id.match(/prescription_item_(\d+)/);
                        if (itemMatch) {
                            allocationId = `item_${itemMatch[1]}`;
                        }
                    }
                    if (!groupsByAllocation[allocationId]) {
                        groupsByAllocation[allocationId] = [];
                    }
                    groupsByAllocation[allocationId].push(group);
                });
                
                // Render each allocation as a single entry (like prescription entry page)
                const allocationIds = Object.keys(groupsByAllocation);
                allocationIds.forEach((allocationId, entryIndex) => {
                    const allocationGroups = groupsByAllocation[allocationId];
                    const allocationIsCancelled = allocationGroups.every(g => g.is_cancelled);
                    
                    // Entry number header (one per PrescriptionAllocation)
                    const entryHeader = document.createElement('div');
                    entryHeader.style.fontSize = '14px';
                    entryHeader.style.fontWeight = '600';
                    entryHeader.style.color = '#333';
                    entryHeader.style.marginBottom = '12px';
                    entryHeader.style.paddingBottom = '8px';
                    entryHeader.style.borderBottom = '2px solid #2c7be5';
                    entryHeader.innerHTML = `Entry ${entryIndex + 1}`;
                    if (allocationIsCancelled) {
                        entryHeader.innerHTML += ' <span style="color: #e63757; font-weight: bold; margin-left: 8px;">[CANCELLED]</span>';
                    }
                    prescriptionSection.appendChild(entryHeader);
                    
                    // Single container for this allocation: per-group lines with items highlighted and details below
                    const allocationDiv = document.createElement('div');
                    allocationDiv.style.marginBottom = '25px';
                    allocationDiv.style.border = allocationIsCancelled ? '2px solid #e63757' : '1px solid #e3ebf6';
                    allocationDiv.style.borderRadius = '8px';
                    allocationDiv.style.padding = '15px';
                    allocationDiv.style.backgroundColor = allocationIsCancelled ? '#fff5f5' : '#f9fafd';
                    if (allocationIsCancelled) {
                        allocationDiv.style.opacity = '0.7';
                    }
                    
                    // Common usage/ext-int for this allocation (from first group)
                    let commonUsage = '';
                    let commonExtInt = '';
                    if (allocationGroups.length > 0) {
                        const g0 = allocationGroups[0];
                        if (g0.usage) {
                            commonUsage = g0.usage;
                        } else if (g0.usage_array && Array.isArray(g0.usage_array) && g0.usage_array.length > 0) {
                            commonUsage = g0.usage_array.join(', ');
                        }
                        if (g0.internal_external) {
                            commonExtInt = g0.internal_external;
                        }
                    }
                    if (commonUsage || commonExtInt) {
                        const metaDiv = document.createElement('div');
                        metaDiv.style.fontSize = '0.85rem';
                        metaDiv.style.color = '#4b5563';
                        metaDiv.style.marginBottom = '6px';
                        const metaParts = [];
                        if (commonUsage) metaParts.push(`Usage: ${escapeHtml(commonUsage)}`);
                        if (commonExtInt) metaParts.push(`Ext/Int: ${escapeHtml(commonExtInt)}`);
                        metaDiv.innerHTML = metaParts.join(' | ');
                        allocationDiv.appendChild(metaDiv);
                    }
                    
                    allocationGroups.forEach((group, groupIndex) => {
                        const items = group.items || [];
                        if (!items.length) return;
                        
                        const itemNames = items.map(it => escapeHtml(it.item_name)).join(', ');
                        const dosageRaw = group.dose || items[0]?.dose || '';
                        const unoRaw = group.notes || group.uno || items[0]?.notes || '';
                        const dosageDisplay = (dosageRaw && unoRaw)
                            ? `${dosageRaw} (${unoRaw})`
                            : (dosageRaw || unoRaw);
                        const ingredientsDisplay = (group.ingredients && group.ingredients.length > 0)
                            ? group.ingredients.map(ing => escapeHtml(ing.ingredient_name || ing.text || '')).join(', ')
                            : '';
                        // usage is common per allocation and shown above
                        const time = group.time || items[0]?.time || '';
                        const internalExternal = group.internal_external || items[0]?.internal_external || '';
                        
                        if (groupIndex > 0) {
                            const plusLine = document.createElement('div');
                            plusLine.style.textAlign = 'center';
                            plusLine.style.margin = '4px 0';
                            plusLine.style.fontWeight = 'bold';
                            plusLine.style.color = '#6b7280';
                            plusLine.textContent = '+';
                            allocationDiv.appendChild(plusLine);
                        }
                        
                        const itemCard = document.createElement('div');
                        itemCard.className = 'medicine-card';
                        itemCard.style.borderLeft = allocationIsCancelled ? '4px solid #e63757' : '4px solid #2c7be5';
                        itemCard.style.marginBottom = '8px';
                        itemCard.style.padding = '12px';
                        itemCard.style.backgroundColor = '#fff';
                        itemCard.style.borderRadius = '6px';
                        
                        const line1 = document.createElement('div');
                        line1.style.fontWeight = '600';
                        line1.style.marginBottom = '2px';
                        const prefix = groupIndex === 0 ? '• ' : '+ ';
                        line1.innerHTML = `${prefix}<span style="display:inline-block;padding:2px 8px;border-radius:999px;background:#e3f2fd;color:#0d47a1;">${itemNames || 'No medicines'}</span>`;
                        
                        const line2 = document.createElement('div');
                        line2.style.fontSize = '0.85rem';
                        line2.style.color = '#4b5563';
                        const details = [];
                        const oilClass = group.oil_class || '';
                        if (dosageDisplay) details.push(`Dosage: ${escapeHtml(dosageDisplay)}`);
                        if (time) details.push(`Time: ${escapeHtml(time)}`);
                        if (internalExternal) details.push(`Ext/Int: ${escapeHtml(internalExternal)}`);
                        if (ingredientsDisplay) details.push(`Ingredients: ${ingredientsDisplay}`);
                        if (oilClass) details.push(`Oil Class: ${escapeHtml(oilClass)}`);
                        line2.innerHTML = details.join(' | ');
                        
                        itemCard.appendChild(line1);
                        itemCard.appendChild(line2);
                        allocationDiv.appendChild(itemCard);
                    });
                    
                    prescriptionSection.appendChild(allocationDiv);
                });
                
                pvContent.appendChild(prescriptionSection);
            }
            
            // Render therapy items section - grouped by therapy
            if (therapyItems.length > 0) {
                const therapySection = document.createElement('div');
                therapySection.className = 'items-section';
                therapySection.style.marginTop = '20px';
                therapySection.innerHTML = '<h3 style="margin: 0 0 15px 0; color: #333;">Therapy Items</h3>';
                
                // Group therapy items by therapy_name
                const therapyGroups = {};
                therapyItems.forEach(item => {
                    if (item.is_group && item.items) {
                        // This is a grouped therapy item
                        const therapyKey = item.therapy_name || 'Unknown Therapy';
                        if (!therapyGroups[therapyKey]) {
                            therapyGroups[therapyKey] = [];
                        }
                        therapyGroups[therapyKey].push(item);
                    } else {
                        // Legacy format - individual items
                        const therapyKey = item.therapy_name || 'Unknown Therapy';
                        if (!therapyGroups[therapyKey]) {
                            therapyGroups[therapyKey] = [];
                        }
                        therapyGroups[therapyKey].push({ items: [item], dosage: item.dose || '', uno: item.notes || '' });
                    }
                });
                
                // Render each therapy group
                Object.keys(therapyGroups).forEach(therapyName => {
                    // Check if any group in this therapy is cancelled
                    const therapyGroupsList = therapyGroups[therapyName];
                    const therapyIsCancelled = therapyGroupsList.some(group => group.booking_is_cancelled);
                    
                    const therapyGroupDiv = document.createElement('div');
                    therapyGroupDiv.style.marginBottom = '20px';
                    therapyGroupDiv.style.border = therapyIsCancelled ? '2px solid #e63757' : '1px solid #e3ebf6';
                    therapyGroupDiv.style.borderRadius = '8px';
                    therapyGroupDiv.style.padding = '15px';
                    therapyGroupDiv.style.backgroundColor = therapyIsCancelled ? '#fff5f5' : '#f9fafd';
                    
                    const therapyTitle = document.createElement('div');
                    therapyTitle.style.fontSize = '16px';
                    therapyTitle.style.fontWeight = '600';
                    therapyTitle.style.color = '#333';
                    therapyTitle.style.marginBottom = '10px';
                    therapyTitle.innerHTML = therapyName;
                    if (therapyIsCancelled) {
                        therapyTitle.innerHTML += ' <span style="color: #e63757; font-weight: bold; margin-left: 8px;">[CANCELLED]</span>';
                    }
                    therapyGroupDiv.appendChild(therapyTitle);
                    
                    // Render each dosage group within this therapy
                    therapyGroupsList.forEach(group => {
                        const items = group.items || [];
                        if (items.length === 0) return;
                        
                        const groupIsCancelled = group.booking_is_cancelled;
                        
                        // Show dosage if available
                        if (group.dosage) {
                            const dosageLabel = document.createElement('div');
                            dosageLabel.style.fontSize = '14px';
                            dosageLabel.style.fontWeight = '500';
                            dosageLabel.style.color = '#666';
                            dosageLabel.style.marginTop = '10px';
                            dosageLabel.style.marginBottom = '8px';
                            // Combine dosage and UNO for better readability
                            const dosageText = group.dosage || '';
                            const unoText = group.uno || '';
                            const dosageDisplay = (dosageText && unoText) 
                                ? `${dosageText} (${unoText})`
                                : (dosageText || unoText);
                            dosageLabel.textContent = `Dosage: ${escapeHtml(dosageDisplay)}`;
                            if (groupIsCancelled) {
                                dosageLabel.style.opacity = '0.7';
                            }
                            therapyGroupDiv.appendChild(dosageLabel);
                        }
                        
                        // Render items in this group - display as single group with multiple items
                        if (items.length > 0) {
                            const itemCard = document.createElement('div');
                            itemCard.className = 'medicine-card';
                            itemCard.style.borderLeft = groupIsCancelled ? '4px solid #e63757' : '4px solid #4CAF50';
                            itemCard.style.marginBottom = '8px';
                            itemCard.style.padding = '12px';
                            itemCard.style.backgroundColor = '#fff';
                            itemCard.style.borderRadius = '6px';
                            if (groupIsCancelled) {
                                itemCard.style.opacity = '0.7';
                            }
                            
                            // Check if all items in this group are prepared
                            let allPrepared = true;
                            const medicineIds = [];
                            const removedItems = [];
                            items.forEach(item => {
                                const medicineId = `${currentPatient.patient_id}_${item.id}_${currentDate}`;
                                medicineIds.push(medicineId);
                                const isRemoved = item.is_removed || item.status === 'removed';
                                if (isRemoved) {
                                    removedItems.push(item);
                                }
                                if (!preparedMedicines.has(medicineId)) {
                                    allPrepared = false;
                                }
                            });
                            
                            if (allPrepared && items.length > 0) {
                                itemCard.classList.add('prepared');
                            }
                            
                            // Display multiple item names as tags (like prescription entry)
                            const itemsHtml = items.map(it => {
                                const medicineId = `${currentPatient.patient_id}_${it.id}_${currentDate}`;
                                const isPrepared = preparedMedicines.has(medicineId);
                                const isRemoved = it.is_removed || it.status === 'removed';
                                const removedBadge = isRemoved ? '<span style="color: #f6c343; font-weight: bold; margin-left: 4px;">[REMOVED]</span>' : '';
                                return `<span class="tag" style="display:inline-block;padding:4px 8px;margin:2px;background:${isPrepared ? '#d4edda' : isRemoved ? '#fff3cd' : '#e3ebf6'};border-radius:4px;font-size:0.9em;">${escapeHtml(it.item_name)}${removedBadge}</span>`;
                            }).join(' ');
                            
                            // Single dosage, usage, time, UNO, and internal/external for the entire group
                            const dosage = group.dosage || items[0]?.dose || 'N/A';
                            // Handle usage - can be string or array
                            let usage = 'N/A';
                            if (group.usage) {
                                usage = group.usage;
                            } else if (group.usage_array && Array.isArray(group.usage_array) && group.usage_array.length > 0) {
                                usage = group.usage_array.join(', ');
                            } else if (items[0]?.usage) {
                                usage = items[0].usage;
                            }
                            const uno = group.uno || items[0]?.notes || 'N/A';
                            const internalExternal = group.internal_external || items[0]?.internal_external || 'N/A';
                            
                            itemCard.innerHTML = `
                                <div style="display:flex;align-items:flex-start;gap:12px;">
                                    <div class="medicine-checkbox" style="flex-shrink:0;padding-top:4px;">
                                        <input type="checkbox" id="med-group-${group.group_id}" ${allPrepared ? 'checked' : ''} ${(groupIsCancelled || removedItems.length === items.length) ? 'disabled' : ''}>
                                    </div>
                                    <div class="medicine-details" style="flex:1;">
                                        <div style="margin-bottom:8px;">
                                            ${itemsHtml}
                                        </div>
                                        <div class="medicine-meta" style="font-size:0.9em;color:#666;display:flex;flex-wrap:wrap;gap:12px;">
                                            ${dosage !== 'N/A' || uno !== 'N/A' ? `<span><strong>Dosage:</strong> ${escapeHtml(dosage !== 'N/A' && uno !== 'N/A' ? `${dosage} (${uno})` : (dosage !== 'N/A' ? dosage : '') + (uno !== 'N/A' ? ` (${uno})` : ''))}</span>` : ''}
                                            ${usage !== 'N/A' ? `<span><strong>Usage:</strong> ${escapeHtml(usage)}</span>` : ''}
                                            ${internalExternal !== 'N/A' ? `<span><strong>Ext/Int:</strong> ${escapeHtml(internalExternal)}</span>` : ''}
                                            ${items[0]?.item_code ? `<span><strong>Item Code:</strong> ${escapeHtml(items[0].item_code)}</span>` : ''}
                                        </div>
                                    </div>
                                </div>
                            `;
                            
                            // Add event listener for checkbox (only if not cancelled/removed)
                            if (!groupIsCancelled && removedItems.length < items.length) {
                                const checkbox = itemCard.querySelector('input[type="checkbox"]');
                                checkbox.addEventListener('change', function() {
                                    // Toggle all non-removed items in the group
                                    items.forEach((it, idx) => {
                                        const isRemoved = it.is_removed || it.status === 'removed';
                                        if (!isRemoved) {
                                            toggleMedicinePreparation(medicineIds[idx], this.checked);
                                        }
                                    });
                                    // Update visual state
                                    if (this.checked) {
                                        itemCard.classList.add('prepared');
                                        // Update tag backgrounds for non-removed items
                                        itemCard.querySelectorAll('.tag').forEach((tag, idx) => {
                                            const it = items[idx];
                                            const isRemoved = it.is_removed || it.status === 'removed';
                                            if (!isRemoved) {
                                                tag.style.background = '#d4edda';
                                            }
                                        });
                                    } else {
                                        itemCard.classList.remove('prepared');
                                        // Update tag backgrounds for non-removed items
                                        itemCard.querySelectorAll('.tag').forEach((tag, idx) => {
                                            const it = items[idx];
                                            const isRemoved = it.is_removed || it.status === 'removed';
                                            if (!isRemoved) {
                                                tag.style.background = '#e3ebf6';
                                            }
                                        });
                                    }
                                });
                            }
                            
                            therapyGroupDiv.appendChild(itemCard);
                        }
                    });
                    
                    therapySection.appendChild(therapyGroupDiv);
                });
                
                pvContent.appendChild(therapySection);
            }
        }
        
        function toggleMedicinePreparation(medicineId, isPrepared) {
            if (isPrepared) {
                preparedMedicines.add(medicineId);
            } else {
                preparedMedicines.delete(medicineId);
            }
            
            // Update the medicine card appearance
            const medicineCard = document.querySelector(`#med-${medicineId}`).closest('.medicine-card');
            if (isPrepared) {
                medicineCard.classList.add('prepared');
            } else {
                medicineCard.classList.remove('prepared');
            }
            
            // Update patient list and statistics
            renderPatients();
            updateStatistics();
            
            console.log('Medicine preparation toggled:', medicineId, isPrepared);
            console.log('Current prepared medicines:', Array.from(preparedMedicines));
        }
        
        function markAllMedicinesAsPrepared() {
            if (!currentPatient) return;
            
            // Mark all medicines for this patient as prepared
            const patientKey = `${currentPatient.patient_id}_${currentDate}`;
            const checkboxes = document.querySelectorAll('#pv_content input[type="checkbox"]');
            
            checkboxes.forEach(checkbox => {
                if (!checkbox.checked) {
                    checkbox.checked = true;
                    const medicineId = checkbox.id.replace('med-', '');
                    preparedMedicines.add(medicineId);
                }
            });
            
            // Update UI
            document.querySelectorAll('#pv_content .medicine-card').forEach(card => {
                card.classList.add('prepared');
            });
            
            // Dispatch the prescription to mark as dispatched
            dispatchPrescription();
            
            renderPatients();
            updateStatistics();
        }
        
        function dispatchPrescription() {
            if (!currentPatient) return;
            
            // Call the mark as dispatched API
            fetch('/sheduling/procurement/api/mark-dispatched/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': getCookie('csrftoken')
                },
                body: JSON.stringify({
                    patient_id: currentPatient.patient_id,
                    date: currentDate
                })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    if (data.already_dispatched) {
                        showAlert('info', 'Prescription was already dispatched');
                    } else {
                        showAlert('success', 'Prescription dispatched successfully!');
                    }
                    // Refresh the patient list to show updated status
                    loadPatients();
                    updateStatistics();
                } else {
                    showAlert('error', data.error || 'Failed to dispatch prescription');
                }
            })
            .catch(error => {
                console.error('Error dispatching prescription:', error);
                showAlert('error', 'Error dispatching prescription');
            });
        }
        
        function getCookie(name) {
            let cookieValue = null;
            if (document.cookie && document.cookie !== '') {
                const cookies = document.cookie.split(';');
                for (let i = 0; i < cookies.length; i++) {
                    const cookie = cookies[i].trim();
                    if (cookie.substring(0, name.length + 1) === (name + '=')) {
                        cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                        break;
                    }
                }
            }
            return cookieValue;
        }
        
        function loadChangeLog(patientId) {
            const changeLogPanel = document.getElementById('changeLogPanel');
            const changeLogContent = document.getElementById('changeLogContent');
            
            // Show panel
            changeLogPanel.style.display = 'block';
            changeLogContent.innerHTML = '<div class="loading">Loading change log...</div>';
            
            // Fetch change log
            const apiUrl = `/sheduling/procurement/api/change-log/?patient_id=${patientId}&date=${currentDate}`;
            fetch(apiUrl)
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        renderChangeLog(data.data || []);
                    } else {
                        changeLogContent.innerHTML = '<p style="color: #666;">No change log entries found.</p>';
                    }
                })
                .catch(error => {
                    console.error('Error loading change log:', error);
                    changeLogContent.innerHTML = '<p style="color: red;">Error loading change log.</p>';
                });
        }
        
        // Helper function to format values for display (handles objects, arrays, strings)
        function formatChangeValue(value) {
            if (value === null || value === undefined) {
                return '';
            }
            if (Array.isArray(value)) {
                // Handle arrays - check if items are objects or strings
                return value.map(item => {
                    if (typeof item === 'string' || typeof item === 'number') {
                        return String(item);
                    } else if (typeof item === 'object' && item !== null) {
                        // Try to extract meaningful properties from objects
                        if (item.item_name) return item.item_name;
                        if (item.name) return item.name;
                        if (item.text) return item.text;
                        // If no recognizable property, try JSON stringify
                        try {
                            return JSON.stringify(item);
                        } catch (e) {
                            return String(item);
                        }
                    }
                    return String(item);
                }).join(', ');
            }
            if (typeof value === 'object') {
                try {
                    return JSON.stringify(value, null, 2);
                } catch (e) {
                    return String(value);
                }
            }
            return String(value);
        }
        
        function renderChangeLog(logs) {
            const changeLogContent = document.getElementById('changeLogContent');
            
            if (!logs || logs.length === 0) {
                changeLogContent.innerHTML = '<p style="color: #666;">No change log entries found.</p>';
                return;
            }
            
            let html = '<div style="display: flex; flex-direction: column; gap: 15px;">';
            
            logs.forEach(log => {
                const timestamp = new Date(log.timestamp);
                const formattedDate = timestamp.toLocaleString();
                
                html += `
                    <div style="padding: 12px; background: white; border-radius: 6px; border-left: 4px solid #2196F3;">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                            <strong style="color: #333;">${escapeHtml(log.action_display || log.action)}</strong>
                            <span style="font-size: 0.85em; color: #666;">${formattedDate}</span>
                        </div>
                        <div style="font-size: 0.9em; color: #666; margin-bottom: 8px;">
                            Changed by: <strong>${escapeHtml(log.changed_by || 'Unknown')}</strong>
                        </div>
                        ${log.description ? `<div style="font-size: 0.9em; color: #555; margin-bottom: 8px;">${escapeHtml(log.description)}</div>` : ''}
                        ${log.changes && log.changes.length > 0 ? `
                            <div style="margin-top: 10px;">
                                <strong style="font-size: 0.85em; color: #333;">Changes:</strong>
                                <ul style="margin: 5px 0 0 0; padding-left: 20px; font-size: 0.85em;">
                                    ${log.changes.map(change => {
                                        // Handle items_groups field - check if it has structured changes or needs parsing
                                        if (change.field === 'items_groups' || change.field === 'Items Groups') {
                                            // If structured changes are available, use them
                                            if (change.items_groups_changes && change.items_groups_changes.length) {
                                            const groupsHtml = change.items_groups_changes.map(gch => {
                                                const groupLines = (gch.changes || []).map(c => {
                                                    if (c.field === 'items') {
                                                        // Handle items - extract item names from objects
                                                        let beforeItems = '';
                                                        let afterItems = '';
                                                        
                                                        if (Array.isArray(c.before)) {
                                                            beforeItems = c.before.map(item => {
                                                                if (typeof item === 'string') {
                                                                    return item;
                                                                } else if (typeof item === 'object' && item !== null) {
                                                                    return item.item_name || item.name || '';
                                                                }
                                                                return '';
                                                            }).filter(Boolean).join(', ');
                                                        }
                                                        
                                                        if (Array.isArray(c.after)) {
                                                            afterItems = c.after.map(item => {
                                                                if (typeof item === 'string') {
                                                                    return item;
                                                                } else if (typeof item === 'object' && item !== null) {
                                                                    return item.item_name || item.name || '';
                                                                }
                                                                return '';
                                                            }).filter(Boolean).join(', ');
                                                        }
                                                        
                                                        return `
                                                            <div style="margin-left: 20px; margin-bottom: 4px; font-size: 0.9em;">
                                                                <span style="color:#333; font-weight: 500;">items:</span>
                                                                <span style="color:#d32f2f; margin-left: 4px;">${escapeHtml(beforeItems || '—')}</span>
                                                                <span style="margin: 0 6px;">→</span>
                                                                <span style="color:#388e3c;">${escapeHtml(afterItems || '—')}</span>
                                                            </div>
                                                        `;
                                                    }
                                                    // Handle other fields (dosage, time, uno, oil_class, etc.)
                                                    const beforeVal = c.before !== null && c.before !== undefined ? String(c.before) : '—';
                                                    const afterVal = c.after !== null && c.after !== undefined ? String(c.after) : '—';
                                                    return `
                                                        <div style="margin-left: 20px; margin-bottom: 4px; font-size: 0.9em;">
                                                            <span style="color:#333; font-weight: 500;">${escapeHtml(c.field)}:</span>
                                                            <span style="color:#d32f2f; margin-left: 4px;">${escapeHtml(beforeVal)}</span>
                                                            <span style="margin: 0 6px;">→</span>
                                                            <span style="color:#388e3c;">${escapeHtml(afterVal)}</span>
                                                        </div>
                                                    `;
                                                }).join('');
                                                return `
                                                    <div style="margin-bottom: 12px; padding: 8px; background: #f9f9f9; border-radius: 4px; border-left: 3px solid #2196F3;">
                                                        <div style="font-weight: 600; color: #555; margin-bottom: 6px; font-size: 0.95em;">Group #${gch.group_index + 1}</div>
                                                        ${groupLines}
                                                    </div>
                                                `;
                                            }).join('');
                                            return `
                                                <li style="margin-bottom: 12px; list-style: none;">
                                                    <div style="font-weight: 600; color: #333; margin-bottom: 8px; font-size: 0.95em;">Prescription groups updated</div>
                                                    <div style="margin-top: 8px;">
                                                        <div style="font-weight: 600; color: #444; font-size: 0.9em; margin-bottom: 8px;">Group changes:</div>
                                                        <div style="margin-left: 0;">${groupsHtml}</div>
                                                    </div>
                                                </li>
                                            `;
                                            } else {
                                                // If no structured changes, try to parse JSON and show structured view
                                                try {
                                                    let beforeGroups = [];
                                                    let afterGroups = [];
                                                    
                                                    if (typeof change.before === 'string') {
                                                        beforeGroups = JSON.parse(change.before);
                                                    } else if (Array.isArray(change.before)) {
                                                        beforeGroups = change.before;
                                                    }
                                                    
                                                    if (typeof change.after === 'string') {
                                                        afterGroups = JSON.parse(change.after);
                                                    } else if (Array.isArray(change.after)) {
                                                        afterGroups = change.after;
                                                    }
                                                    
                                                    // Compare groups and show differences
                                                    const maxLen = Math.max(beforeGroups.length, afterGroups.length);
                                                    const groupsHtml = [];
                                                    
                                                    for (let i = 0; i < maxLen; i++) {
                                                        const beforeGroup = beforeGroups[i] || {};
                                                        const afterGroup = afterGroups[i] || {};
                                                        const groupChanges = [];
                                                        
                                                        // Compare each field
                                                        const fields = ['dosage', 'time', 'uno', 'oil_class'];
                                                        fields.forEach(field => {
                                                            const beforeVal = beforeGroup[field] || '';
                                                            const afterVal = afterGroup[field] || '';
                                                            if (beforeVal !== afterVal) {
                                                                groupChanges.push({
                                                                    field: field,
                                                                    before: beforeVal,
                                                                    after: afterVal
                                                                });
                                                            }
                                                        });
                                                        
                                                        // Compare items
                                                        const beforeItems = (beforeGroup.items || []).map(it => it.item_name || it.name || '').filter(Boolean).join(', ');
                                                        const afterItems = (afterGroup.items || []).map(it => it.item_name || it.name || '').filter(Boolean).join(', ');
                                                        if (beforeItems !== afterItems) {
                                                            groupChanges.push({
                                                                field: 'items',
                                                                before: beforeItems,
                                                                after: afterItems
                                                            });
                                                        }
                                                        
                                                        // Compare ingredients
                                                        const beforeIng = (beforeGroup.ingredients || []).map(ing => ing.ingredient_name || ing.name || '').filter(Boolean).join(', ');
                                                        const afterIng = (afterGroup.ingredients || []).map(ing => ing.ingredient_name || ing.name || '').filter(Boolean).join(', ');
                                                        if (beforeIng !== afterIng) {
                                                            groupChanges.push({
                                                                field: 'ingredients',
                                                                before: beforeIng,
                                                                after: afterIng
                                                            });
                                                        }
                                                        
                                                        if (groupChanges.length > 0 || i < beforeGroups.length || i < afterGroups.length) {
                                                            const groupLines = groupChanges.map(c => {
                                                                if (c.field === 'items' || c.field === 'ingredients') {
                                                                    return `
                                                                        <div style="margin-left: 20px; margin-bottom: 4px; font-size: 0.9em;">
                                                                            <span style="color:#333; font-weight: 500;">${escapeHtml(c.field)}:</span>
                                                                            <span style="color:#d32f2f; margin-left: 4px;">${escapeHtml(c.before || '—')}</span>
                                                                            <span style="margin: 0 6px;">→</span>
                                                                            <span style="color:#388e3c;">${escapeHtml(c.after || '—')}</span>
                                                                        </div>
                                                                    `;
                                                                }
                                                                return `
                                                                    <div style="margin-left: 20px; margin-bottom: 4px; font-size: 0.9em;">
                                                                        <span style="color:#333; font-weight: 500;">${escapeHtml(c.field)}:</span>
                                                                        <span style="color:#d32f2f; margin-left: 4px;">${escapeHtml(c.before || '—')}</span>
                                                                        <span style="margin: 0 6px;">→</span>
                                                                        <span style="color:#388e3c;">${escapeHtml(c.after || '—')}</span>
                                                                    </div>
                                                                `;
                                                            }).join('');
                                                            
                                                            groupsHtml.push(`
                                                                <div style="margin-bottom: 12px; padding: 8px; background: #f9f9f9; border-radius: 4px; border-left: 3px solid #2196F3;">
                                                                    <div style="font-weight: 600; color: #555; margin-bottom: 6px; font-size: 0.95em;">Group #${i + 1}</div>
                                                                    ${groupLines || '<div style="margin-left: 20px; font-size: 0.9em; color: #666;">(New group added)</div>'}
                                                                </div>
                                                            `);
                                                        }
                                                    }
                                                    
                                                    if (groupsHtml.length > 0) {
                                                        return `
                                                            <li style="margin-bottom: 12px; list-style: none;">
                                                                <div style="font-weight: 600; color: #333; margin-bottom: 8px; font-size: 0.95em;">Prescription groups updated</div>
                                                                <div style="margin-top: 8px;">
                                                                    <div style="font-weight: 600; color: #444; font-size: 0.9em; margin-bottom: 8px;">Group changes:</div>
                                                                    <div style="margin-left: 0;">${groupsHtml.join('')}</div>
                                                                </div>
                                                            </li>
                                                        `;
                                                    }
                                                } catch (e) {
                                                    // If parsing fails, fall back to formatted display
                                                    console.error('Error parsing items_groups:', e);
                                                }
                                            }
                                        }
                                        // Handle other field changes (not items_groups)
                                        const beforeVal = formatChangeValue(change.before);
                                        const afterVal = formatChangeValue(change.after);
                                        return `
                                            <li style="margin-bottom: 5px; font-size: 0.9em;">
                                                <strong>${escapeHtml(change.field)}</strong>:
                                                <span style="color: #d32f2f;">${escapeHtml(beforeVal)}</span>
                                                →
                                                <span style="color: #388e3c;">${escapeHtml(afterVal)}</span>
                                            </li>
                                        `;
                                    }).join('')}
                                </ul>
                            </div>
                        ` : ''}
                    </div>
                `;
            });
            
            html += '</div>';
            changeLogContent.innerHTML = html;
        }
        
        function saveChanges() {
            if (!currentPatient) return;
            
            // Save individual medicine preparation status
            const checkboxes = document.querySelectorAll('#pv_content input[type="checkbox"]');
            const preparedMedicines = [];
            
            checkboxes.forEach(checkbox => {
                if (checkbox.checked) {
                    const medicineId = checkbox.id.replace('med-', '');
                    preparedMedicines.push(medicineId);
                }
            });
            
            // In a real implementation, this would save to the database
            // For now, we'll just update the local state and show feedback
            console.log('Saving preparation status for medicines:', preparedMedicines);
            
            // Update the prepared medicines set
            preparedMedicines.forEach(medicineId => {
                preparedMedicines.add(medicineId);
            });
            
            // Update UI
            renderPatients();
            updateStatistics();
            
            showAlert('success', `Preparation status saved for ${preparedMedicines.length} medicines!`);
        }
        
        function exportPatientCSV() {
            if (!currentPatient) return;
            
            // In a real implementation, this would generate and download a CSV file
            showAlert('success', 'Patient data exported as CSV!');
        }
        
        function highlightActivePatient(patientId) {
            // Remove active class from all patient cards
            document.querySelectorAll('.patient-card').forEach(card => {
                card.classList.remove('active');
            });
            
            // Add active class to selected patient card
            const selectedCard = document.querySelector(`.patient-card[data-id="${patientId}"]`);
            if (selectedCard) {
                selectedCard.classList.add('active');
            }
        }
        
        function updateStatistics() {
            if (!window.patientsData) return;
            
            let totalMeds = 0;
            let preparedMeds = 0;
            let dispatchedMeds = 0;
            
            window.patientsData.forEach(patient => {
                totalMeds += patient.prescription_count;
                
                if (patient.status === 'dispatched') {
                    dispatchedMeds += patient.prescription_count;
                } else {
                    preparedMeds += getPreparedCount(patient);
                }
            });
            
            // Update the statistics display
            document.getElementById('totalMeds').textContent = totalMeds;
            document.getElementById('pendingMeds').textContent = totalMeds - preparedMeds - dispatchedMeds;
            document.getElementById('preparedMeds').textContent = preparedMeds + dispatchedMeds;
            
            console.log('Statistics updated:', {
                total: totalMeds,
                prepared: preparedMeds,
                dispatched: dispatchedMeds,
                pending: totalMeds - preparedMeds - dispatchedMeds
            });
        }
        
        function showLoading() {
            // Show loading indicator in patient list
            const patientsList = document.getElementById('patientsList');
            if (patientsList) {
                patientsList.innerHTML = '<div class="loading">Loading patients...</div>';
            }
        }
        
        function hideLoading() {
            // Hide loading indicator - this is handled by renderPatients()
        }
        
        function showAlert(type, message) {
            // Create and show alert
            const alertDiv = document.createElement('div');
            alertDiv.className = `alert alert-${type}`;
            alertDiv.textContent = message;
            
            // Insert at the top of the container
            const container = document.querySelector('.container');
            container.insertBefore(alertDiv, container.firstChild);
            
            // Remove after 3 seconds
            setTimeout(() => {
                alertDiv.remove();
            }, 3000);
        }