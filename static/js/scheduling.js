// Initialize the dashboard
        document.addEventListener('DOMContentLoaded', function() {
            // Set up event listeners
            setupEventListeners();
        });

        // Tab switching
        function setupEventListeners() {
            // Tab switching
            document.querySelectorAll('.tab').forEach(tab => {
                tab.addEventListener('click', function() {
                    // Remove active class from all tabs and contents
                    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
                    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
                    
                    // Add active class to clicked tab and corresponding content
                    this.classList.add('active');
                    document.getElementById(this.dataset.tab).classList.add('active');
                });
            });
            
            // Final Schedule button
            document.getElementById('final-schedule-btn').addEventListener('click', triggerFinalSchedule);
            
            // Schedule all drafts (hidden by default)
            document.getElementById('schedule-all').addEventListener('click', scheduleAllDrafts);
            
            // Reschedule all failed
            document.getElementById('reschedule-all').addEventListener('click', rescheduleAllFailed);
            
            // Modal event listeners
            document.getElementById('confirmScheduleBtn').addEventListener('click', confirmSchedule);
            // Reschedule no longer uses modal - it uses the date filter directly
            // document.getElementById('confirmRescheduleBtn') is kept for potential future use
            
            // Date filters - show therapies scheduled for the selected date
            document.getElementById('draft-date').addEventListener('change', function() {
                if (this.value) {
                    loadTherapyData('draft', this.value);
                    checkFinalScheduleStatus(this.value);
                } else {
                    // If no date selected, show all draft therapies
                    loadTherapyData('draft', '');
                    resetFinalScheduleButton();
                }
            });
            document.getElementById('failed-date').addEventListener('change', function() {
                if (this.value) {
                    loadTherapyData('failed', this.value);
                } else {
                    // If no date selected, show all failed therapies
                    loadTherapyData('failed', '');
                }
            });
            document.getElementById('scheduled-date').addEventListener('change', function() {
                const selectedDate = this.value || '';
                activateScheduledTab();
                const patientFilter = getPatientSearchValue();
                loadTherapyData('allocated', selectedDate, patientFilter);
            });
            
            const patientSearchInput = document.getElementById('patient-search');
            const patientSearchBtn = document.getElementById('patient-search-btn');
            const clearPatientSearchBtn = document.getElementById('clear-patient-search');
            
            if (patientSearchBtn) {
                patientSearchBtn.addEventListener('click', () => applyPatientNameFilter());
            }
            if (patientSearchInput) {
                patientSearchInput.addEventListener('keyup', (event) => {
                    if (event.key === 'Enter') {
                        event.preventDefault();
                        applyPatientNameFilter();
                    }
                });
            }
            if (clearPatientSearchBtn) {
                clearPatientSearchBtn.addEventListener('click', () => {
                    if (patientSearchInput) {
                        patientSearchInput.value = '';
                    }
                    applyPatientNameFilter('');
                });
            }
            
            // Export to Excel button
            document.getElementById('export-therapy-excel').addEventListener('click', function() {
                exportTherapyScheduleToExcel();
            });
            
            // Print to PDF button
            document.getElementById('print-therapy-pdf').addEventListener('click', function() {
                printTherapyScheduleToPDF();
            });
            
            // Individual reschedule buttons (schedule buttons removed)
            document.addEventListener('click', function(e) {
                // Use closest to handle clicks on button children (text, icons, etc.)
                const rescheduleBtn = e.target.closest ? e.target.closest('.reschedule-single') : null;
                if (rescheduleBtn) {
                    const id = parseInt(rescheduleBtn.dataset.id);
                    if (!isNaN(id)) {
                        rescheduleSingleFailed(id);
                    } else {
                        console.error('Invalid allocation ID:', rescheduleBtn.dataset.id);
                        alert('Error: Invalid therapy ID. Please refresh the page and try again.');
                    }
                    return;
                }
                
                const patientLink = e.target.closest ? e.target.closest('.patient-name-link') : null;
                if (patientLink) {
                    const patientName = patientLink.dataset.patientName || '';
                    const scheduleDate = patientLink.dataset.scheduleDate || '';
                    if (patientName) {
                        applyPatientNameFilter(patientName, scheduleDate);
                    }
                }
            });
        }

        function getPatientSearchValue() {
            const input = document.getElementById('patient-search');
            return input ? input.value.trim() : '';
        }

        function activateScheduledTab() {
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
            const scheduledTab = document.querySelector('[data-tab="scheduled"]');
            const scheduledContent = document.getElementById('scheduled');
            if (scheduledTab) {
                scheduledTab.classList.add('active');
            }
            if (scheduledContent) {
                scheduledContent.classList.add('active');
            }
        }

        function applyPatientNameFilter(patientNameOverride = null, scheduleDateOverride = null) {
            const searchInput = document.getElementById('patient-search');
            const patientValue = patientNameOverride !== null ? patientNameOverride : getPatientSearchValue();
            if (patientNameOverride !== null && searchInput) {
                searchInput.value = patientNameOverride;
            }

            const dateInput = document.getElementById('scheduled-date');
            let targetDate = scheduleDateOverride || (dateInput ? dateInput.value : '');
            if (dateInput && scheduleDateOverride && dateInput.value !== scheduleDateOverride) {
                dateInput.value = scheduleDateOverride;
            }

            activateScheduledTab();
            loadTherapyData('allocated', targetDate, patientValue);
        }

        function loadTherapyData(status, date, patientName = '') {
            const params = new URLSearchParams();
            params.append('status', status || '');
            if (date) {
                params.append('date', date);
            }
            if (patientName) {
                params.append('patient_name', patientName);
            }
            const queryString = params.toString();
            const url = `/sheduling/scheduling/api/therapy-data/?${queryString}`;
            
            fetch(url)
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        updateTable(status, data.data);
                        updateStats(data.data);
                    }
                })
                .catch(error => {
                    console.error('Error loading therapy data:', error);
                });
        }

        // Helper function to convert 24-hour time to 12-hour format
        function format12Hour(time24) {
            if (!time24) return '—';
            const parts = String(time24).split(':');
            if (parts.length !== 2) return time24;
            let hours = parseInt(parts[0], 10);
            const minutes = parts[1];
            const period = hours >= 12 ? 'PM' : 'AM';
            hours = hours % 12;
            hours = hours ? hours : 12; // 0 should be 12
            return `${hours}:${minutes} ${period}`;
        }

        function updateTable(status, data) {
            // For draft status, separate into therapist and nurse treatments
            if (status === 'draft') {
                const therapistTbody = document.getElementById('draft-therapist-body');
                const nurseTbody = document.getElementById('draft-nurse-body');
                
                if (!therapistTbody || !nurseTbody) {
                    console.error('Table bodies not found for draft therapies');
                    return;
                }
                
                // Separate therapist and nurse treatments
                const therapistData = [];
                const nurseData = [];
                
                data.forEach(item => {
                    const nurseFlag = typeof item.is_nurse_treatment !== 'undefined'
                        ? (item.is_nurse_treatment === true || item.is_nurse_treatment === 'true')
                        : false;
                    const isNurseTreatment = nurseFlag;
                    
                    if (isNurseTreatment) {
                        nurseData.push(item);
                    } else {
                        therapistData.push(item);
                    }
                });
                
                // Update therapist table
                therapistTbody.innerHTML = '';
                if (therapistData.length === 0) {
                    therapistTbody.innerHTML = `
                        <tr>
                            <td colspan="5" class="empty-state">
                                <div class="empty-state-icon">📋</div>
                                <div>No draft therapist treatments found for this date.</div>
                            </td>
                        </tr>
                    `;
                } else {
                    therapistData.forEach(item => {
                        const displayDate = item.date || (item.from_date + ' to ' + item.to_date);
                        const row = document.createElement('tr');
                        row.innerHTML = `
                            <td>
                                <div style="font-weight: 500;">${escapeHtml(item.patient_name)}</div>
                                <div style="font-size: 12px; color: var(--gray);">${escapeHtml(item.patient_reg_no)}</div>
                            </td>
                            <td>${escapeHtml(item.therapy_name)}</td>
                            <td>${displayDate}</td>
                            <td>${format12Hour(item.timeslot) || '—'}</td>
                            <td>${item.room_no || '—'}</td>
                        `;
                        therapistTbody.appendChild(row);
                    });
                }
                
                // Update nurse table
                nurseTbody.innerHTML = '';
                if (nurseData.length === 0) {
                    nurseTbody.innerHTML = `
                        <tr>
                            <td colspan="4" class="empty-state">
                                <div class="empty-state-icon">📋</div>
                                <div>No draft nurse treatments found for this date.</div>
                            </td>
                        </tr>
                    `;
                } else {
                    nurseData.forEach(item => {
                        const displayDate = item.date || (item.from_date + ' to ' + item.to_date);
                        const row = document.createElement('tr');
                        row.innerHTML = `
                            <td>
                                <div style="font-weight: 500;">${escapeHtml(item.patient_name)}</div>
                                <div style="font-size: 12px; color: var(--gray);">${escapeHtml(item.patient_reg_no)}</div>
                            </td>
                            <td>${escapeHtml(item.therapy_name)}</td>
                            <td>${displayDate}</td>
                            <td>${item.patient_room_no || '—'}</td>
                        `;
                        nurseTbody.appendChild(row);
                    });
                }
                
                // Update counts
                document.getElementById('draft-therapist-count').textContent = therapistData.length;
                document.getElementById('draft-nurse-count').textContent = nurseData.length;
                
                return;
            }
            
            // For scheduled/allocated status, separate into therapist and nurse schedules
            if (status === 'allocated' || status === 'scheduled') {
                const therapistTbody = document.getElementById('therapist-scheduled-body');
                const nurseTbody = document.getElementById('nurse-scheduled-body');
                
                if (!therapistTbody || !nurseTbody) {
                    console.error('Table bodies not found for scheduled therapies');
                    return;
                }
                
                // Separate therapist and nurse treatments
                const therapistData = [];
                const nurseData = [];
                
                data.forEach(item => {
                    const hasNurses = item.nurses && item.nurses.length > 0;
                    const hasTherapists = item.therapists && item.therapists.length > 0;
                    const nurseFlag = typeof item.is_nurse_treatment !== 'undefined'
                        ? (item.is_nurse_treatment === true || item.is_nurse_treatment === 'true')
                        : false;
                    const isNurseTreatment = nurseFlag || (hasNurses && !hasTherapists);
                    
                    if (isNurseTreatment) {
                        nurseData.push(item);
                    } else {
                        therapistData.push(item);
                    }
                });
                
                // Update therapist table
                therapistTbody.innerHTML = '';
                if (therapistData.length === 0) {
                    therapistTbody.innerHTML = `
                        <tr>
                            <td colspan="8" class="empty-state">
                                <div class="empty-state-icon">✅</div>
                                <div>No therapist schedules found for this date.</div>
                            </td>
                        </tr>
                    `;
                } else {
                    therapistData.forEach(item => {
                        const hasNurses = item.nurses && item.nurses.length > 0;
                        const hasTherapists = item.therapists && item.therapists.length > 0;
                        const nurseFlag = typeof item.is_nurse_treatment !== 'undefined'
                            ? (item.is_nurse_treatment === true || item.is_nurse_treatment === 'true')
                            : false;
                        const isNurseTreatment = nurseFlag || (hasNurses && !hasTherapists);
                        const slotDisplay = (isNurseTreatment && (!item.timeslot || item.timeslot === '00:00'))
                            ? '—'
                            : format12Hour(item.timeslot);
                        const scheduleDate = item.date || item.from_date || '';
                const therapistsHtml = item.therapists && item.therapists.length > 0 
                    ? `<div class="therapist-list">${item.therapists.map(t => {
                        const rawName = t.name || t.code || t;
                        const cleanedName = rawName.replace(/\(bathing\)/gi, '').replace(/^\*/, '').trim();
                        const isBathing = t.is_bathing === true || rawName.startsWith('*') || /\(bathing\)/i.test(rawName);
                        const isSenior = t.is_senior === true;
                        let displayName = cleanedName;
                        // Add (senior) prefix for Dhara & Pizichil senior therapists
                        if (isSenior) {
                            displayName = `${cleanedName} (senior)`;
                        }
                        if (isBathing) {
                            displayName = `*${displayName}`;
                        }
                        let badgeClass = 'therapist-badge';
                        if (isSenior) {
                            badgeClass += ' senior-therapist';
                        }
                        if (isBathing) {
                            badgeClass += ' bathing-therapist';
                        }
                        return `<span class="${badgeClass}">${escapeHtml(displayName)}</span>`;
                    }).join('')}</div>`
                            : '<span class="muted">Not assigned</span>';
                        
                        const row = document.createElement('tr');
                        row.innerHTML = `
                            <td>
                                <button type="button" class="patient-name-link" data-patient-name="${escapeHtml(item.patient_name)}" data-schedule-date="${escapeHtml(scheduleDate)}">
                                    <div style="font-weight: 500;">${escapeHtml(item.patient_name)}</div>
                                    <div style="font-size: 12px; color: var(--gray);">${escapeHtml(item.patient_reg_no)}</div>
                                </button>
                            </td>
                            <td>${escapeHtml(item.therapy_name)}</td>
                            <td>${slotDisplay}</td>
                            <td>${item.date || item.from_date}</td>
                            <td>${escapeHtml(item.room_no || '—')}</td>
                            <td>${escapeHtml(item.patient_room_no || '—')}</td>
                            <td>${therapistsHtml}</td>
                            <td>${escapeHtml(item.allocated_by || 'System')}</td>
                        `;
                        therapistTbody.appendChild(row);
                    });
                }
                
                // Update nurse table
                nurseTbody.innerHTML = '';
                if (nurseData.length === 0) {
                    nurseTbody.innerHTML = `
                        <tr>
                            <td colspan="5" class="empty-state">
                                <div class="empty-state-icon">✅</div>
                                <div>No nurse schedules found for this date.</div>
                            </td>
                        </tr>
                    `;
                } else {
                    nurseData.forEach(item => {
                        const scheduleDate = item.date || item.from_date || '';
                        const nursesHtml = item.nurses && item.nurses.length > 0 
                            ? `<div class="nurse-list">${item.nurses.map(n => `<span class="nurse-badge">${n.name || n.code || n}</span>`).join('')}</div>`
                            : '<span class="muted">Not assigned</span>';
                        
                        const row = document.createElement('tr');
                        row.innerHTML = `
                            <td>
                                <button type="button" class="patient-name-link" data-patient-name="${escapeHtml(item.patient_name)}" data-schedule-date="${escapeHtml(scheduleDate)}">
                                    <div style="font-weight: 500;">${escapeHtml(item.patient_name)}</div>
                                    <div style="font-size: 12px; color: var(--gray);">${escapeHtml(item.patient_reg_no)}</div>
                                </button>
                            </td>
                            <td>${escapeHtml(item.therapy_name)}</td>
                            <td>${scheduleDate || '—'}</td>
                            <td>${escapeHtml(item.patient_room_no || '—')}</td>
                            <td>${nursesHtml}</td>
                        `;
                        nurseTbody.appendChild(row);
                    });
                }
                
                return;
            }
            
            // For other statuses (failed), use the original logic
            let tbodyId = `${status}-body`;
            const tbody = document.getElementById(tbodyId);
            if (!tbody) {
                console.error(`Table body not found: ${tbodyId}`);
                return;
            }
            
            tbody.innerHTML = '';
            
            if (data.length === 0) {
                let message = '';
                let colspan = 7;
                if (status === 'failed') {
                    message = 'No failed therapies found. Failed therapies will appear here after scheduling attempts.';
                    colspan = 7;
                } else {
                    message = `No ${status} therapies found. Use date filter to view therapies for specific dates.`;
                    colspan = 6;
                }
                
                tbody.innerHTML = `
                    <tr>
                        <td colspan="${colspan}" class="empty-state">
                            <div class="empty-state-icon">📋</div>
                            <div>${message}</div>
                        </td>
                    </tr>
                `;
                return;
            }
            
            data.forEach(item => {
                const row = document.createElement('tr');
                const therapistsHtml = item.therapists && item.therapists.length > 0 
                    ? `<div class="therapist-list">${item.therapists.map(t => {
                        const rawName = t.name || t.code || t;
                        const cleanedName = rawName.replace(/\(bathing\)/gi, '').replace(/^\*/, '').trim();
                        const isBathing = t.is_bathing === true || rawName.startsWith('*') || /\(bathing\)/i.test(rawName);
                        const isSenior = t.is_senior === true;
                        let displayName = cleanedName;
                        // Add (senior) prefix for Dhara & Pizichil senior therapists
                        if (isSenior) {
                            displayName = `${cleanedName} (senior)`;
                        }
                        if (isBathing) {
                            displayName = `*${displayName}`;
                        }
                        let badgeClass = 'therapist-badge';
                        if (isSenior) {
                            badgeClass += ' senior-therapist';
                        }
                        if (isBathing) {
                            badgeClass += ' bathing-therapist';
                        }
                        return `<span class="${badgeClass}">${escapeHtml(displayName)}</span>`;
                    }).join('')}</div>`
                    : '<span class="muted">Not assigned</span>';
                
                if (status === 'failed') {
                    row.innerHTML = `
                        <td>
                            <div style="font-weight: 500;">${escapeHtml(item.patient_name)}</div>
                            <div style="font-size: 12px; color: var(--gray);">${escapeHtml(item.patient_reg_no)}</div>
                        </td>
                        <td>${escapeHtml(item.therapy_name)}</td>
                        <td>${format12Hour(item.timeslot) || '—'}</td>
                        <td>${item.patient_room_no || '—'}</td>
                        <td>
                            <span class="status-badge status-failed">Slot Conflict</span>
                        </td>
                        <td>Try different time slot</td>
                        <td>
                            <button class="btn btn-outline btn-small reschedule-single" data-id="${item.id}">
                                Reschedule
                            </button>
                        </td>
                    `;
                } else if (status === 'allocated' || status === 'scheduled') {
                    // Show booking date if available, otherwise show from_date
                    const displayDate = item.date || item.from_date;
                    row.innerHTML = `
                        <td>
                            <div style="font-weight: 500;">${escapeHtml(item.patient_name)}</div>
                            <div style="font-size: 12px; color: var(--gray);">${escapeHtml(item.patient_reg_no)}</div>
                        </td>
                        <td>${escapeHtml(item.therapy_name)}</td>
                        <td>${format12Hour(item.timeslot) || '—'}</td>
                        <td>${displayDate}</td>
                        <td>${item.room_no || '—'}</td>
                        <td>${item.patient_room_no || '—'}</td>
                        <td>${therapistsHtml}</td>
                        <td>${escapeHtml(item.allocated_by || 'System')}</td>
                    `;
                }
                
                tbody.appendChild(row);
            });
        }

        function updateStats(data) {
            const draftCount = data.filter(item => item.status === 'draft').length;
            const failedCount = data.filter(item => item.status === 'failed').length;
            const scheduledCount = data.filter(item => item.status === 'allocated').length;
            
            document.getElementById('draft-count').textContent = draftCount;
            document.getElementById('failed-count').textContent = failedCount;
            document.getElementById('allocated-count').textContent = scheduledCount;
        }

        let currentScheduleId = null;
        
        function scheduleSingleDraft(id) {
            currentScheduleId = id;
            document.getElementById('scheduleDate').value = '';
            document.getElementById('scheduleModal').style.display = 'block';
        }
        
        function confirmSchedule() {
            const targetDate = document.getElementById('scheduleDate').value;
            
            if (!targetDate) {
                alert('Please select a date');
                return;
            }
            
            closeScheduleModal();
            
            showLoading('draft');
            
            fetch('/sheduling/scheduling/api/schedule-therapies/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    date: targetDate,
                    allocation_ids: currentScheduleId ? [currentScheduleId] : []
                })
            })
            .then(response => response.json())
            .then(data => {
                hideLoading('draft');
                if (data.success) {
                    showAlert('success', data.message);
                    // Reload the data
                    loadTherapyData('draft', targetDate);
                    loadTherapyData('failed', targetDate);
                    loadTherapyData('allocated', targetDate, getPatientSearchValue());
                } else {
                    showAlert('error', data.error || 'Scheduling failed');
                }
            })
            .catch(error => {
                hideLoading('draft');
                showAlert('error', 'Error scheduling therapy: ' + error.message);
            });
        }

        function triggerFinalSchedule() {
            const selectedDate = document.getElementById('draft-date').value;
            
            if (!selectedDate) {
                alert('Please select a date first using the date filter');
                return;
            }
            
            if (!confirm(`Are you sure you want to run Final Schedule for ${selectedDate}? This will update emergency leave data and allocate all draft therapies for this date.`)) {
                return;
            }
            
            showLoading('draft');
            
            fetch('/sheduling/scheduling/api/final-schedule/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    date: selectedDate
                })
            })
            .then(response => response.json())
            .then(data => {
                hideLoading('draft');
                if (data.success) {
                    // Extract success and failure counts
                    let successful = 0;
                    let failed = 0;
                    
                    if (data.allocation_update && data.allocation_update.success && data.allocation_update.result) {
                        successful = data.allocation_update.result.successful || 0;
                        failed = data.allocation_update.result.failed || 0;
                    }
                    
                    // Show confirmation popup
                    alert(`Schedule is done.\n${successful} treatments successful, ${failed} treatments failed`);
                    
                    // Also show detailed alert for additional info
                    let message = `Final Schedule completed for ${selectedDate}\n\n`;
                    
                    if (data.leave_update && data.leave_update.success) {
                        message += `Emergency Leave Update: ${data.leave_update.count} employees on leave\n`;
                    } else if (data.leave_update && !data.leave_update.success) {
                        message += `Emergency Leave Update: Failed - ${data.leave_update.error}\n`;
                    }
                    
                    if (data.allocation_update && data.allocation_update.success) {
                        const result = data.allocation_update.result;
                        message += `Allocation Results: ${result.successful} successful, ${result.failed} failed out of ${result.total_processed} total`;
                    } else if (data.allocation_update && !data.allocation_update.success) {
                        message += `Allocation Update: Failed - ${data.allocation_update.error}`;
                    }
                    
                    showAlert('success', message);
                    
                    // Reload all data
                    loadTherapyData('draft', selectedDate);
                    loadTherapyData('failed', selectedDate);
                    loadTherapyData('allocated', selectedDate, getPatientSearchValue());
                } else {
                    // Check if it's the "already run" error
                    if (data.already_run) {
                        showAlert('warning', data.error);
                        // Disable the Final Schedule button for this date
                        const finalScheduleBtn = document.getElementById('final-schedule-btn');
                        finalScheduleBtn.disabled = true;
                        finalScheduleBtn.textContent = 'Final Schedule (Already Run)';
                        finalScheduleBtn.classList.remove('btn-primary');
                        finalScheduleBtn.classList.add('btn-secondary');
                    } else {
                        showAlert('error', data.error || 'Final Schedule failed');
                    }
                }
            })
            .catch(error => {
                hideLoading('draft');
                showAlert('error', 'Error running Final Schedule: ' + error.message);
            });
        }

        function scheduleAllDrafts() {
            currentScheduleId = null; // null means schedule all
            document.getElementById('scheduleDate').value = '';
            document.getElementById('scheduleModalMessage').textContent = 'Select the date when you want to schedule all draft therapies.';
            document.getElementById('scheduleModal').style.display = 'block';
        }

        function rescheduleSingleFailed(id) {
            // Get the selected date from the date filter
            const targetDate = document.getElementById('failed-date').value;
            
            if (!targetDate) {
                alert('Please select a date using the date filter first');
                return;
            }
            
            if (!id || isNaN(id)) {
                console.error('Invalid allocation ID:', id);
                alert('Error: Invalid therapy ID. Please refresh the page and try again.');
                return;
            }
            
            showLoading('failed');
            
            const requestData = {
                allocation_id: id,
                date: targetDate
            };
            
            console.log('Rescheduling single therapy:', requestData);
            
            fetch('/sheduling/scheduling/api/reschedule-therapy/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(requestData)
            })
            .then(response => {
                if (!response.ok) {
                    return response.json().then(err => {
                        throw new Error(err.error || `Server error: ${response.status}`);
                    });
                }
                return response.json();
            })
            .then(data => {
                hideLoading('failed');
                if (data.success) {
                    let message = data.message || 'Therapy successfully rescheduled';
                    if (data.tasks && data.tasks.length > 0) {
                        message += ` (${data.tasks.length} booking(s) created)`;
                    }
                    showAlert('success', message);
                    // Reload all data to show updated status
                    loadTherapyData('failed', targetDate);
                    loadTherapyData('draft', targetDate);
                    loadTherapyData('allocated', targetDate, getPatientSearchValue());
                } else {
                    showAlert('error', data.error || 'Rescheduling failed');
                    // Reload failed data to show updated status
                    loadTherapyData('failed', targetDate);
                }
            })
            .catch(error => {
                hideLoading('failed');
                console.error('Error rescheduling therapy:', error);
                showAlert('error', 'Error rescheduling therapy: ' + (error.message || error));
                // Reload failed data to show current status
                if (targetDate) {
                    loadTherapyData('failed', targetDate);
                }
            });
        }

        function rescheduleAllFailed() {
            // Get the selected date from the date filter
            const targetDate = document.getElementById('failed-date').value;
            
            if (!targetDate) {
                alert('Please select a date using the date filter first');
                return;
            }
            
            if (!confirm(`Are you sure you want to reschedule all failed therapies for ${targetDate}?`)) {
                return;
            }
            
            showLoading('failed');
            
            const requestData = {
                date: targetDate
            };
            
            console.log('Rescheduling all failed therapies for date:', targetDate);
            
            fetch('/sheduling/scheduling/api/reschedule-all-failed/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(requestData)
            })
            .then(response => response.json())
            .then(data => {
                hideLoading('failed');
                if (data.success) {
                    // Extract success and failure counts
                    let successful = 0;
                    let failed = 0;
                    
                    if (data.stats) {
                        successful = data.stats.successful || 0;
                        failed = data.stats.failed || 0;
                    }
                    
                    // Show confirmation popup
                    alert(`Schedule is done.\n${successful} treatments successful, ${failed} treatments failed`);
                    
                    // Also show detailed alert for additional info
                    let message = data.message || 'Rescheduling completed';
                    if (data.stats) {
                        message += ` - ${data.stats.successful} successful, ${data.stats.failed} failed out of ${data.stats.total} total`;
                    }
                    showAlert('success', message);
                    // Reload all data to show updated status
                    loadTherapyData('failed', targetDate);
                    loadTherapyData('draft', targetDate);
                    loadTherapyData('allocated', targetDate, getPatientSearchValue());
                } else {
                    showAlert('error', data.error || 'Rescheduling failed');
                    // Reload failed data
                    loadTherapyData('failed', targetDate);
                }
            })
            .catch(error => {
                hideLoading('failed');
                showAlert('error', 'Error rescheduling therapies: ' + error.message);
            });
        }

        function showLoading(tab) {
            const loading = document.getElementById(`${tab}-loading`);
            if (loading) {
                loading.classList.add('show');
            }
        }

        function hideLoading(tab) {
            const loading = document.getElementById(`${tab}-loading`);
            if (loading) {
                loading.classList.remove('show');
            }
        }

        function showAlert(type, message) {
            // Remove existing alerts
            document.querySelectorAll('.alert').forEach(alert => alert.remove());
            
            const alert = document.createElement('div');
            alert.className = `alert alert-${type}`;
            alert.textContent = message;
            
            // Insert at the top of the dashboard
            const dashboard = document.querySelector('.dashboard');
            dashboard.insertBefore(alert, dashboard.firstChild);
            
            // Auto-remove after 5 seconds
            setTimeout(() => {
                alert.remove();
            }, 5000);
        }

        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }
        
        // Modal functions
        function closeScheduleModal() {
            document.getElementById('scheduleModal').style.display = 'none';
            currentScheduleId = null;
        }
        
        function closeRescheduleModal() {
            document.getElementById('rescheduleModal').style.display = 'none';
            currentRescheduleId = null;
        }
        
        function checkFinalScheduleStatus(selectedDate) {
            // Check if Final Schedule has already been run for this date (GET, read-only)
            fetch(`/sheduling/scheduling/api/final-schedule/status/?date=${encodeURIComponent(selectedDate)}`)
            .then(response => response.json())
            .then(data => {
                if (data.already_run) {
                    // Final Schedule already run for this date
                    const finalScheduleBtn = document.getElementById('final-schedule-btn');
                    finalScheduleBtn.disabled = true;
                    finalScheduleBtn.textContent = 'Final Schedule (Already Run)';
                    finalScheduleBtn.classList.remove('btn-primary');
                    finalScheduleBtn.classList.add('btn-secondary');
                } else {
                    // Final Schedule not run yet, enable button
                    resetFinalScheduleButton();
                }
            })
            .catch(error => {
                console.error('Error checking Final Schedule status:', error);
                // On error, assume it's available
                resetFinalScheduleButton();
            });
        }

        function resetFinalScheduleButton() {
            const finalScheduleBtn = document.getElementById('final-schedule-btn');
            finalScheduleBtn.disabled = false;
            finalScheduleBtn.innerHTML = '<span>🎯</span> Final Schedule';
            finalScheduleBtn.classList.remove('btn-secondary');
            finalScheduleBtn.classList.add('btn-primary');
        }

        // Close modals when clicking outside
        window.onclick = function(event) {
            const scheduleModal = document.getElementById('scheduleModal');
            const rescheduleModal = document.getElementById('rescheduleModal');
            
            if (event.target === scheduleModal) {
                closeScheduleModal();
            }
            if (event.target === rescheduleModal) {
                closeRescheduleModal();
            }
        }
        
        // Export Therapy Schedule to Excel
        function exportTherapyScheduleToExcel() {
            const selectedDate = document.getElementById('scheduled-date').value;
            const patientFilter = getPatientSearchValue();
            
            if (!selectedDate) {
                alert('Please select a date first using the date filter');
                return;
            }
            
            // Show loading
            const exportBtn = document.getElementById('export-therapy-excel');
            const originalText = exportBtn.innerHTML;
            exportBtn.disabled = true;
            exportBtn.innerHTML = '<span>⏳</span> Exporting...';
            
            // Fetch scheduled therapies data
            const patientQuery = patientFilter ? `&patient_name=${encodeURIComponent(patientFilter)}` : '';
            fetch(`/sheduling/scheduling/api/therapy-data/?status=allocated&date=${selectedDate}${patientQuery}`)
                .then(response => response.json())
                .then(data => {
                    exportBtn.disabled = false;
                    exportBtn.innerHTML = originalText;
                    
                    if (data.success && data.data.length > 0) {
                        generateTherapyExcel(data.data, selectedDate, patientFilter);
                    } else {
                        alert('No scheduled therapies found for the selected date.');
                    }
                })
                .catch(error => {
                    exportBtn.disabled = false;
                    exportBtn.innerHTML = originalText;
                    alert('Error exporting to Excel: ' + error.message);
                });
        }
        
        function generateTherapyExcel(therapyData, date, patientFilter) {
            // Separate therapist and nurse treatments
            const therapistData = [];
            const nurseData = [];
            
            therapyData.forEach(item => {
                const hasNurses = item.nurses && item.nurses.length > 0;
                const hasTherapists = item.therapists && item.therapists.length > 0;
                const nurseFlag = typeof item.is_nurse_treatment !== 'undefined'
                    ? (item.is_nurse_treatment === true || item.is_nurse_treatment === 'true')
                    : false;
                const isNurseTreatment = nurseFlag || (hasNurses && !hasTherapists);
                
                if (isNurseTreatment) {
                    nurseData.push(item);
                } else {
                    therapistData.push(item);
                }
            });
            
            // Helper function to format time in 12-hour format
            function format12Hour(time24) {
                if (!time24) return '—';
                const parts = String(time24).split(':');
                if (parts.length !== 2) return time24;
                let hours = parseInt(parts[0], 10);
                const minutes = parts[1];
                const period = hours >= 12 ? 'PM' : 'AM';
                hours = hours % 12;
                hours = hours ? hours : 12;
                return `${hours}:${minutes} ${period}`;
            }
            
            // Prepare therapist schedule data
            const therapistRows = therapistData.map(item => {
                const hasNurses = item.nurses && item.nurses.length > 0;
                const hasTherapists = item.therapists && item.therapists.length > 0;
                const nurseFlag = typeof item.is_nurse_treatment !== 'undefined'
                    ? (item.is_nurse_treatment === true || item.is_nurse_treatment === 'true')
                    : false;
                const isNurseTreatment = nurseFlag || (hasNurses && !hasTherapists);
                const slotDisplay = (isNurseTreatment && (!item.timeslot || item.timeslot === '00:00'))
                    ? '—'
                    : format12Hour(item.timeslot);
                const therapists = item.therapists && item.therapists.length > 0
                    ? item.therapists.map(t => {
                        const rawName = t.name || t.code || t;
                        const cleanedName = rawName.replace(/\(bathing\)/gi, '').replace(/^\*/, '').trim();
                        const isBathing = t.is_bathing === true || rawName.startsWith('*') || /\(bathing\)/i.test(rawName);
                        const isSenior = t.is_senior === true;
                        let displayName = cleanedName;
                        // Add (senior) prefix for Dhara & Pizichil senior therapists
                        if (isSenior) {
                            displayName = `${cleanedName} (senior)`;
                        }
                        if (isBathing) {
                            displayName = `*${displayName}`;
                        }
                        return displayName;
                    }).join(', ')
                    : 'Not assigned';
                
                return {
                    'Patient Name': item.patient_name || '—',
                    'Patient Reg No': item.patient_reg_no || '—',
                    'Therapy': item.therapy_name || '—',
                    'Time Slot': slotDisplay,
                    'Date': item.date || item.from_date || '—',
                    'Treatment Room No': item.room_no || '—',
                    'Patient Room No': item.patient_room_no || '—',
                    'Therapist Assigned': therapists,
                    'Scheduled By': item.allocated_by || 'System'
                };
            });
            
            // Prepare nurse schedule data
            const nurseRows = nurseData.map(item => {
                const nurses = item.nurses && item.nurses.length > 0
                    ? item.nurses.map(n => n.name || n.code || n).join(', ')
                    : 'Not assigned';
                
                return {
                    'Patient Name': item.patient_name || '—',
                    'Patient Reg No': item.patient_reg_no || '—',
                    'Treatment Name': item.therapy_name || '—',
                    'Date': item.date || item.from_date || '—',
                    'Patient Room No': item.patient_room_no || '—',
                    'Nurse Assigned': nurses
                };
            });
            
            // Create workbook
            const wb = XLSX.utils.book_new();
            
            // Add therapist schedule sheet
            if (therapistRows.length > 0) {
                const therapistWs = XLSX.utils.json_to_sheet(therapistRows);
                XLSX.utils.book_append_sheet(wb, therapistWs, 'Therapist Schedule');
            }
            
            // Add nurse schedule sheet
            if (nurseRows.length > 0) {
                const nurseWs = XLSX.utils.json_to_sheet(nurseRows);
                XLSX.utils.book_append_sheet(wb, nurseWs, 'Nurse Schedule');
            }
            
            // Generate filename
            let filename = `Therapy_Schedule_${date.replace(/-/g, '_')}`;
            if (patientFilter) {
                filename += `_${patientFilter.replace(/[^a-zA-Z0-9]/g, '_')}`;
            }
            filename += '.xlsx';
            
            // Write and download
            XLSX.writeFile(wb, filename);
        }
        
        // Print Therapy Schedule to PDF
        function printTherapyScheduleToPDF() {
            const selectedDate = document.getElementById('scheduled-date').value;
            const patientFilter = getPatientSearchValue();
            
            if (!selectedDate) {
                alert('Please select a date first using the date filter');
                return;
            }
            
            // Show loading
            const printBtn = document.getElementById('print-therapy-pdf');
            const originalText = printBtn.innerHTML;
            printBtn.disabled = true;
            printBtn.innerHTML = '<span>⏳</span> Generating PDF...';
            
            // Fetch scheduled therapies data
            const patientQuery = patientFilter ? `&patient_name=${encodeURIComponent(patientFilter)}` : '';
            fetch(`/sheduling/scheduling/api/therapy-data/?status=allocated&date=${selectedDate}${patientQuery}`)
                .then(response => response.json())
                .then(data => {
                    printBtn.disabled = false;
                    printBtn.innerHTML = originalText;
                    
                    if (data.success && data.data.length > 0) {
                        generateTherapyPDF(data.data, selectedDate);
                    } else {
                        alert('No scheduled therapies found for the selected date.');
                    }
                })
                .catch(error => {
                    printBtn.disabled = false;
                    printBtn.innerHTML = originalText;
                    alert('Error generating PDF: ' + error.message);
                });
        }
        
        function generateTherapyPDF(therapyData, date) {
            try {
                // Check if jsPDF is loaded
                if (typeof window.jspdf === 'undefined') {
                    alert('PDF library not loaded. Please refresh the page and try again.');
                    console.error('jsPDF library not found');
                    return;
                }
                
                const { jsPDF } = window.jspdf;
                const doc = new jsPDF('p', 'mm', 'a4');
                
                const pageWidth = doc.internal.pageSize.getWidth();
                const pageHeight = doc.internal.pageSize.getHeight();
                const margin = 15;
                const contentWidth = pageWidth - (margin * 2);
                let yPos = margin;
                let currentPage = 1;
                
                // Remove duplicates based on booking_id
                const uniqueData = [];
                const seenBookingIds = new Set();
                therapyData.forEach(item => {
                    const bookingId = item.booking_id || item.id;
                    if (!seenBookingIds.has(bookingId)) {
                        seenBookingIds.add(bookingId);
                        uniqueData.push(item);
                    }
                });
                
                // Separate therapist and nurse treatments
                const therapistTreatments = [];
                const nurseTreatments = [];
                uniqueData.forEach(item => {
                    const hasNurses = item.nurses && item.nurses.length > 0;
                    const hasTherapists = item.therapists && item.therapists.length > 0;
                    const nurseFlag = typeof item.is_nurse_treatment !== 'undefined'
                        ? (item.is_nurse_treatment === true || item.is_nurse_treatment === 'true')
                        : false;
                    const isNurseTreatment = nurseFlag || (hasNurses && !hasTherapists);
                    
                    if (isNurseTreatment) {
                        nurseTreatments.push(item);
                    } else {
                        therapistTreatments.push(item);
                    }
                });
                
                // Group therapist treatments by time slot
                const slotGroups = {};
                therapistTreatments.forEach(item => {
                    const slot = item.timeslot || '00:00';
                    if (!slotGroups[slot]) {
                        slotGroups[slot] = [];
                    }
                    slotGroups[slot].push(item);
                });
                
                // Helper function to format time in 12-hour format for PDF
                function format12HourPDF(time24) {
                    if (!time24) return '—';
                    const parts = String(time24).split(':');
                    if (parts.length !== 2) return time24;
                    let hours = parseInt(parts[0], 10);
                    const minutes = parts[1];
                    const period = hours >= 12 ? 'PM' : 'AM';
                    hours = hours % 12;
                    hours = hours ? hours : 12; // 0 should be 12
                    return `${hours}:${minutes} ${period}`;
                }
                
                // Sort slots chronologically (morning to evening)
                const sortedSlots = Object.keys(slotGroups).sort((a, b) => {
                    const timeA = a.split(':').map(Number);
                    const timeB = b.split(':').map(Number);
                    const minutesA = timeA[0] * 60 + (timeA[1] || 0);
                    const minutesB = timeB[0] * 60 + (timeB[1] || 0);
                    return minutesA - minutesB;
                });
                
                // Sort treatments within each slot by patient name
                sortedSlots.forEach(slot => {
                    slotGroups[slot].sort((a, b) => {
                        return (a.patient_name || '').localeCompare(b.patient_name || '');
                    });
                });
                
                // Helper function to format date
                function formatDate(dateStr) {
                    const d = new Date(dateStr + 'T00:00:00');
                    const options = { year: 'numeric', month: 'long', day: 'numeric' };
                    return d.toLocaleDateString('en-US', options);
                }
                
                // Header function
                function addHeader() {
                    doc.setFontSize(20);
                    doc.setFont(undefined, 'bold');
                    doc.text('Therapy Final Schedule', pageWidth / 2, yPos, { align: 'center' });
                    yPos += 8;
                    
                    doc.setFontSize(16);
                    doc.setFont(undefined, 'bold');
                    doc.text(`Date: ${formatDate(date)}`, pageWidth / 2, yPos, { align: 'center' });
                    yPos += 10;
                    
                    // Draw line
                    doc.setLineWidth(0.5);
                    doc.line(margin, yPos, pageWidth - margin, yPos);
                    yPos += 8;
                }
                
                // Footer function
                function addFooter(pageNum) {
                    const footerY = pageHeight - 10;
                    doc.setFontSize(8);
                    doc.setFont(undefined, 'normal');
                    doc.text(`Page ${pageNum}`, pageWidth / 2, footerY, { align: 'center' });
                    doc.text(`Date: ${date}`, margin, footerY);
                }
                
                // Check if new page needed
                function checkNewPage(requiredSpace) {
                    if (yPos + requiredSpace > pageHeight - 20) {
                        addFooter(currentPage);
                        doc.addPage();
                        currentPage++;
                        yPos = margin;
                        addHeader();
                        return true;
                    }
                    return false;
                }
                
                // Add header
                addHeader();
                
                // ========== THERAPIST TREATMENTS SECTION ==========
                if (therapistTreatments.length > 0) {
                    // Section heading for Therapist Treatments
                    checkNewPage(15);
                    doc.setFontSize(16);
                    doc.setFont(undefined, 'bold');
                    doc.setFillColor(59, 130, 246);
                    doc.rect(margin, yPos - 5, contentWidth, 10, 'F');
                    doc.setTextColor(255, 255, 255);
                    doc.text('Therapist Treatments', margin + 5, yPos + 3);
                    yPos += 12;
                    doc.setTextColor(0, 0, 0);
                    
                    // Process each time slot for therapist treatments
                    sortedSlots.forEach((slot, slotIndex) => {
                        const treatments = slotGroups[slot];
                        if (!treatments || treatments.length === 0) return;
                        
                        // Check if we need a new page for the slot header
                        checkNewPage(15);
                        
                        // Slot header
                        doc.setFontSize(14);
                        doc.setFont(undefined, 'bold');
                        doc.setFillColor(59, 130, 246);
                        doc.rect(margin, yPos - 5, contentWidth, 8, 'F');
                        doc.setTextColor(255, 255, 255);
                        doc.text(`Time Slot: ${format12HourPDF(slot)}`, margin + 5, yPos);
                        yPos += 10;
                        doc.setTextColor(0, 0, 0);
                        
                        // Prepare table data for this slot
                        const tableData = treatments.map(item => {
                            // Build therapist string with senior highlighting
                            // This matches the dashboard display logic exactly
                            let therapistStr = '—';
                            if (item.therapists && item.therapists.length > 0) {
                                therapistStr = item.therapists.map(t => {
                                    const rawName = t.name || t.code || t;
                                    const cleanedName = rawName.replace(/\(bathing\)/gi, '').replace(/^\*/, '').trim();
                                    const isBathing = t.is_bathing === true || rawName.startsWith('*') || /\(bathing\)/i.test(rawName);
                                    // Check for senior tag - only one senior (non-bathing) should have is_senior=true
                                    const isSenior = t.is_senior === true;
                                    let displayName = cleanedName;
                                    // Add (senior) prefix for special treatments (Dhara & Pizhichil, Thakradhara, etc.)
                                    // Only one senior therapist who is NOT bathing will have is_senior=true
                                    if (isSenior) {
                                        displayName = `${cleanedName} (senior)`;
                                    }
                                    // Add * prefix for bathing therapist
                                    if (isBathing) {
                                        displayName = `*${displayName}`;
                                    }
                                    return displayName;
                                }).join(', ');
                            }
                            
                            return [
                                item.patient_room_no || '—',
                                item.patient_name || 'N/A',
                                item.room_no || '—',
                                item.therapy_name || 'N/A',
                                therapistStr
                            ];
                        });
                        
                        // Generate table for this slot with custom cell styling for senior therapists
                        const columnStyles = {
                            4: { // Therapist Assigned column
                                cellWidth: 50,
                            }
                        };
                        
                        // Custom cell styling function to highlight senior therapists
                        const didParseCell = function(data) {
                            // Check if this cell contains (senior) marker
                            if (data.column.index === 4 && data.cell.text && data.cell.text[0]) {
                                const cellText = data.cell.text[0];
                                if (typeof cellText === 'string' && cellText.includes('(senior)')) {
                                    // Highlight senior therapist cells with yellow background
                                    data.cell.styles.fillColor = [254, 243, 199]; // Light yellow/amber
                                    data.cell.styles.textColor = [146, 64, 14]; // Dark brown text
                                    data.cell.styles.fontStyle = 'bold';
                                }
                            }
                        };
                        
                        // Store the starting page number before this table
                        // Get current page number from the document
                        const tableStartPage = doc.internal.getNumberOfPages();
                        
                        doc.autoTable({
                            head: [['Patient Room', 'Patient Name', 'Treatment Room', 'Therapy', 'Therapist Assigned']],
                            body: tableData,
                            startY: yPos,
                            margin: { left: margin, right: margin },
                            styles: {
                                fontSize: 8,
                                cellPadding: 2.5,
                            },
                            headStyles: {
                                fillColor: [100, 116, 139],
                                textColor: 255,
                                fontStyle: 'bold',
                                fontSize: 9,
                            },
                            alternateRowStyles: {
                                fillColor: [248, 250, 252],
                            },
                            columnStyles: columnStyles,
                            didParseCell: didParseCell,
                            didDrawPage: function(data) {
                                // Calculate actual page number: tableStartPage is the page we're starting on
                                // data.pageNumber is 1-based relative to the table start
                                // So actual page = tableStartPage + data.pageNumber - 1
                                const actualPageNumber = tableStartPage + data.pageNumber - 1;
                                // Add footer on each page with correct page number
                                addFooter(actualPageNumber);
                                // Update currentPage to the last page of this table
                                currentPage = actualPageNumber;
                            },
                        });
                        
                        // Update yPos after table
                        yPos = doc.lastAutoTable.finalY + 8;
                        // Update currentPage to reflect the actual number of pages after this table
                        currentPage = doc.internal.getNumberOfPages();
                        
                        // Add spacing between slots (except for last slot)
                        if (slotIndex < sortedSlots.length - 1) {
                            yPos += 5;
                            doc.setLineWidth(0.3);
                            doc.setDrawColor(200, 200, 200);
                            doc.line(margin, yPos, pageWidth - margin, yPos);
                            yPos += 8;
                        }
                    });
                }
                
                // ========== NURSE TREATMENTS SECTION ==========
                if (nurseTreatments.length > 0) {
                    // Add spacing before nurse section
                    checkNewPage(20);
                    yPos += 10;
                    doc.setLineWidth(0.5);
                    doc.setDrawColor(100, 100, 100);
                    doc.line(margin, yPos, pageWidth - margin, yPos);
                    yPos += 10;
                    
                    // Section heading for Nurse Treatments
                    checkNewPage(15);
                    doc.setFontSize(16);
                    doc.setFont(undefined, 'bold');
                    doc.setFillColor(16, 185, 129); // Green color for nurse section
                    doc.rect(margin, yPos - 5, contentWidth, 10, 'F');
                    doc.setTextColor(255, 255, 255);
                    doc.text('Nurse Treatments', margin + 5, yPos + 3);
                    yPos += 12;
                    doc.setTextColor(0, 0, 0);
                    
                    // Sort nurse treatments by patient name
                    nurseTreatments.sort((a, b) => {
                        return (a.patient_name || '').localeCompare(b.patient_name || '');
                    });
                    
                    // Prepare table data for nurse treatments
                    const nurseTableData = nurseTreatments.map(item => [
                        item.patient_room_no || '—',
                        item.patient_name || 'N/A',
                        item.therapy_name || 'N/A',
                        item.date || item.from_date || '—',
                        item.nurses && item.nurses.length > 0 
                            ? item.nurses.map(n => n.name || n.code || n).join(', ') 
                            : '—'
                    ]);
                    
                    // Store the starting page number before this table
                    // Get current page number from the document
                    const nurseTableStartPage = doc.internal.getNumberOfPages();
                    
                    // Generate table for nurse treatments
                    doc.autoTable({
                        head: [['Patient Room', 'Patient Name', 'Treatment Name', 'Date', 'Nurse Assigned']],
                        body: nurseTableData,
                        startY: yPos,
                        margin: { left: margin, right: margin },
                        styles: {
                            fontSize: 8,
                            cellPadding: 2.5,
                        },
                        headStyles: {
                            fillColor: [16, 185, 129], // Green header for nurse section
                            textColor: 255,
                            fontStyle: 'bold',
                            fontSize: 9,
                        },
                        alternateRowStyles: {
                            fillColor: [240, 253, 244], // Light green alternate rows
                        },
                        didDrawPage: function(data) {
                            // Calculate actual page number: nurseTableStartPage is the page we're starting on
                            // data.pageNumber is 1-based relative to the table start
                            // So actual page = nurseTableStartPage + data.pageNumber - 1
                            const actualPageNumber = nurseTableStartPage + data.pageNumber - 1;
                            // Add footer on each page with correct page number
                            addFooter(actualPageNumber);
                            // Update currentPage to the last page of this table
                            currentPage = actualPageNumber;
                        },
                    });
                    
                    // Update yPos after table
                    yPos = doc.lastAutoTable.finalY + 8;
                    // Update currentPage to reflect the actual number of pages after this table
                    currentPage = doc.internal.getNumberOfPages();
                }
                
                // Save PDF
                const fileName = `Therapy_Schedule_${date.replace(/-/g, '_')}.pdf`;
                doc.save(fileName);
            } catch (error) {
                console.error('Error generating PDF:', error);
                alert('Error generating PDF: ' + error.message + '\nPlease check the browser console for details.');
            }
        }