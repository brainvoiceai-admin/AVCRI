// Initialize the dashboard
document.addEventListener('DOMContentLoaded', function () {
    // Set today's date as default
    const today = new Date().toISOString().slice(0, 10);
    document.getElementById('draft-date').value = today;
    document.getElementById('scheduled-date').value = today;
    document.getElementById('dispatched-date').value = today;

    // Set up event listeners
    setupEventListeners();

    // Load initial data
    loadPrescriptionData('draft', today);
    loadPrescriptionData('scheduled', today);
    loadPrescriptionData('dispatched', today);
});

function setupEventListeners() {
    // Tab switching
    document.querySelectorAll('.tab').forEach(tab => {
        tab.addEventListener('click', function () {
            // Remove active class from all tabs and contents
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));

            // Add active class to clicked tab and corresponding content
            this.classList.add('active');
            document.getElementById(this.dataset.tab).classList.add('active');
        });
    });

    // Send final prescription
    document.getElementById('send-final-prescription').addEventListener('click', sendFinalPrescription);

    // Date filters
    document.getElementById('draft-date').addEventListener('change', function () {
        loadPrescriptionData('draft', this.value);
    });
    document.getElementById('scheduled-date').addEventListener('change', function () {
        loadPrescriptionData('scheduled', this.value);
    });
    document.getElementById('dispatched-date').addEventListener('change', function () {
        loadPrescriptionData('dispatched', this.value);
    });

    // Search functionality
    ['draft', 'scheduled', 'dispatched'].forEach(status => {
        const searchInput = document.getElementById(`${status}-search`);
        const searchBtn = document.getElementById(`btn-search-${status}`);
        const clearBtn = document.getElementById(`btn-clear-${status}`);
        const dateInput = document.getElementById(`${status}-date`);

        if (searchBtn) {
            searchBtn.addEventListener('click', () => {
                loadPrescriptionData(status, dateInput.value, searchInput.value);
            });
        }

        if (clearBtn) {
            clearBtn.addEventListener('click', () => {
                searchInput.value = '';
                loadPrescriptionData(status, dateInput.value, '');
            });
        }

        if (searchInput) {
            searchInput.addEventListener('keypress', (e) => {
                if (e.key === 'Enter') {
                    loadPrescriptionData(status, dateInput.value, searchInput.value);
                }
            });
        }
    });

    // Print to PDF button
    document.getElementById('print-prescription-pdf').addEventListener('click', function () {
        printPrescriptionScheduleToPDF();
    });

    // Close modals when clicking outside
    window.onclick = function (event) {
        const prescriptionModal = document.getElementById('prescriptionModal');
        const changeLogModal = document.getElementById('changeLogModal');

        if (event.target === prescriptionModal) {
            closePrescriptionModal();
        }
        if (event.target === changeLogModal) {
            closeChangeLogModal();
        }
    }
}

function loadPrescriptionData(status, date, search = '') {
    let url = `/sheduling/prescription/api/prescription-data/?status=${status}&date=${date}`;
    if (search) {
        url += `&search=${encodeURIComponent(search)}`;
    }

    fetch(url)
        .then(response => {
            const contentType = response.headers.get('content-type');
            if (contentType && contentType.includes('application/json')) {
                return response.json();
            } else if (response.status === 401 || response.status === 403 || response.status === 400) {
                // If it's a known error status but not JSON, it's likely a session timeout or Django error page
                throw new Error('Session might have expired or server error occurred. Please refresh the page.');
            } else {
                return response.text().then(text => {
                    throw new Error('Unexpected response from server. If this persists, please re-login.');
                });
            }
        })
        .then(data => {
            if (data.success) {
                updateTable(status, data.data, date);
                updateStats(data.data, status);

                // Update final schedule button state if in draft tab
                if (status === 'draft') {
                    updateFinalScheduleButtonState(data.final_schedule_generated);
                }
            } else {
                console.error('API Error:', data.error);
                if (status === 'scheduled') {
                    alert('Error: ' + (data.error || 'Failed to load data'));
                }
            }
        })
        .catch(error => {
            console.error('Error loading prescription data:', error);
        });
}

function updateTable(status, data, date) {
    const tbody = document.getElementById(`${status}-body`);
    if (!tbody) return;

    tbody.innerHTML = '';

    if (data.length === 0) {
        let message = '';
        if (status === 'draft') {
            message = 'No draft prescriptions found. Create new prescriptions to see them here.';
        } else if (status === 'scheduled') {
            message = 'No scheduled prescriptions found. Scheduled prescriptions will appear here after sending final prescriptions.';
        } else if (status === 'dispatched') {
            message = 'No dispatched prescriptions found. Dispatched prescriptions will appear here after procurement departments mark them as dispatched.';
        }

        const colspan = (status === 'draft') ? 7 : 9;
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

        let statusSpecificCells = '';
        if (status === 'draft') {
            statusSpecificCells = '';
        } else if (status === 'scheduled') {
            statusSpecificCells = `
                <td>${escapeHtml(item.entered_by || '-')}</td>
                <td>${escapeHtml(item.sent_to || '-')}</td>
            `;
        } else if (status === 'dispatched') {
            statusSpecificCells = `
                <td>${escapeHtml(item.entered_by || '-')}</td>
                <td>${escapeHtml(item.dispatched_from || '-')}</td>
                <td>${formatDate(item.dispatched_at) || '-'}</td>
            `;
        }

        if (status === 'scheduled' && item.has_changes) {
            row.classList.add('row-modified');
        }

        row.innerHTML = `
                    <td>
                        <div class="patient-details">
                            <div class="patient-name">${escapeHtml(item.patient_name)}</div>
                            <div class="patient-meta">ID: ${escapeHtml(item.patient_id_display || item.patient_id)}</div>
                        </div>
                    </td>
                    <td>${escapeHtml(item.registration_no || '-')}</td>
                    <td>${escapeHtml(item.room_no || '-')}</td>
                    <td>${escapeHtml(item.doctor_name || '-')}</td>
                    <td>
                        <div style="display: flex; align-items: center; gap: 8px;">
                            <span class="prescription-name" style="font-weight: 500;">${escapeHtml(item.prescription_name)}</span>
                            ${(status === 'scheduled' && item.has_changes) ? `
                                <button class="btn-change-log" onclick="viewChangeLog(${item.patient_id}, '${date}')" title="View Change Log" style="background: #3b82f6; color: white; border: none; padding: 4px 10px; border-radius: 4px; cursor: pointer; font-size: 11px; font-weight: 600; white-space: nowrap;">
                                    📋 Change Log
                                </button>
                            ` : ''}
                        </div>
                    </td>
                    <td>
                        <div style="display: flex; align-items: center; gap: 5px;">
                            <span class="status-badge status-${status}">${getStatusLabel(status)}</span>
                        </div>
                    </td>
                    ${statusSpecificCells}
                    <td>
                        <div style="display: flex; gap: 8px;">
                            <button class="btn btn-outline btn-small" onclick="viewPrescriptionDetails(${item.patient_id}, '${date}')">
                                View Details
                            </button>
                        </div>
                    </td>
                `;
        tbody.appendChild(row);
    });
}

// Global stats storage
let globalStats = {
    draft: 0,
    scheduled: 0,
    dispatched: 0
};

function updateStats(data, status) {
    // Update the global stats for this specific status
    globalStats[status] = data.length;

    // Update the display immediately
    if (status === 'draft') {
        document.getElementById('draft-count').textContent = data.length;
    } else if (status === 'scheduled') {
        document.getElementById('scheduled-count').textContent = data.length;
    } else if (status === 'dispatched') {
        document.getElementById('dispatched-count').textContent = data.length;
    }
}

function updateStatsDisplay() {
    document.getElementById('draft-count').textContent = globalStats.draft;
    document.getElementById('scheduled-count').textContent = globalStats.scheduled;
    document.getElementById('dispatched-count').textContent = globalStats.dispatched;
}

function getStatusLabel(status) {
    const labels = {
        'draft': 'Draft',
        'scheduled': 'Scheduled',
        'dispatched': 'Dispatched'
    };
    return labels[status] || status;
}

function updateFinalScheduleButtonState(isGenerated) {
    const btn = document.getElementById('send-final-prescription');
    if (!btn) return;

    if (isGenerated) {
        btn.disabled = true;
        btn.classList.remove('btn-primary');
        btn.classList.add('btn-secondary');
        btn.style.opacity = '1';
        btn.title = 'Final Schedule has already been generated for this date';
        btn.innerHTML = '<span>✔️</span> Final Schedule (Already Run)';
    } else {
        btn.disabled = false;
        btn.classList.add('btn-primary');
        btn.classList.remove('btn-secondary');
        btn.style.opacity = '1';
        btn.title = '';
        btn.innerHTML = '<span>📤</span> Send Final Prescription';
    }
}

function sendFinalPrescription() {
    const date = document.getElementById('draft-date').value;
    sendFinalPrescriptionWithDate(date);
}

function sendFinalPrescriptionWithDate(date) {
    if (!date) {
        alert('Please select a date first');
        return;
    }

    const isSync = document.activeElement && (document.activeElement.id === 'resend-scheduled-prescriptions');
    const msg = isSync
        ? `Syncing will update the procurement records with the LATEST medicines for ${formatDate(date)}. This updates the PDF records too. Continue?`
        : `Are you sure you want to send all draft prescriptions for ${formatDate(date)} to procurement departments?`;

    if (!confirm(msg)) {
        return;
    }

    const loaderStatus = isSync ? 'scheduled' : 'draft';
    showLoading(loaderStatus);

    fetch('/sheduling/prescription/api/send-final-prescription/', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            date: date
        })
    })
        .then(response => {
            const contentType = response.headers.get('content-type');
            if (contentType && contentType.includes('application/json')) {
                return response.json();
            } else {
                throw new Error('Session expired or server error. Please refresh and login again.');
            }
        })
        .then(data => {
            hideLoading(loaderStatus);
            if (data.success) {
                showAlert('success', data.message);
                // Reload all data
                loadPrescriptionData('draft', date);
                loadPrescriptionData('scheduled', date);
                loadPrescriptionData('dispatched', date);
            } else {
                showAlert('error', data.error || 'Failed to send final prescription');
            }
        })
        .catch(error => {
            hideLoading(loaderStatus);
            showAlert('error', 'Error sending final prescription: ' + error.message);
        });
}

function viewPrescriptionDetails(patientId, date) {
    fetch(`/sheduling/prescription/api/prescription-details/?patient_id=${patientId}&date=${date}`)
        .then(response => {
            const contentType = response.headers.get('content-type');
            if (contentType && contentType.includes('application/json')) {
                return response.json();
            } else {
                throw new Error('Session expired. Please refresh and login again.');
            }
        })
        .then(data => {
            if (data.success) {
                showPrescriptionModal(data.patient_info, data.prescription_groups || [], data.therapy_items || []);
            } else {
                alert('Error loading prescription details: ' + data.error);
            }
        })
        .catch(error => {
            alert('Error loading prescription details: ' + error.message);
        });
}

function showPrescriptionModal(patientInfo, prescriptionGroups, therapyItems) {
    const modal = document.getElementById('prescriptionModal');
    const patientInfoDiv = document.getElementById('patient-info');
    const prescriptionItemsDiv = document.getElementById('prescription-items');

    // Update patient info
    patientInfoDiv.innerHTML = `
                <h4>${escapeHtml(patientInfo.name)}</h4>
                <p><strong>Registration No:</strong> ${escapeHtml(patientInfo.registration_no)}</p>
                <p><strong>Room No:</strong> ${escapeHtml(patientInfo.room_no || 'N/A')}</p>
                <p><strong>Doctor:</strong> ${escapeHtml(patientInfo.doctor_name || 'N/A')} ${patientInfo.doctor_team ? `(${escapeHtml(patientInfo.doctor_team)})` : ''}</p>
                <p><strong>DOA:</strong> ${escapeHtml(patientInfo.doa || '—')}</p>
                ${patientInfo.entered_by ? `<p><strong>Entered By:</strong> ${escapeHtml(patientInfo.entered_by)}</p>` : ''}
            `;

    // Clear and render prescription items in grouped format (like procurement dashboard)
    prescriptionItemsDiv.innerHTML = '';

    // Render prescription items section - grouped by allocation (same text format as prescription entry page)
    if (prescriptionGroups.length > 0) {
        const prescriptionSection = document.createElement('div');
        prescriptionSection.className = 'items-section';
        prescriptionSection.innerHTML = '<h3 style="margin: 0 0 15px 0; color: #333;">Prescription Items</h3>';

        // Group prescription groups by allocation_id (extract from group_id)
        // Handle both "prescription_group_{allocation_id}_{group_idx}" and "prescription_item_{item_id}" formats
        const groupsByAllocation = {};
        prescriptionGroups.forEach(group => {
            let allocationId = 'unknown';
            if (group.change_type === 'removed') {
                allocationId = 'removed_items';
            } else {
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

            if (allocationId === 'removed_items') {
                entryHeader.innerHTML = '<span style="color: #e63757;">⚠️ Removed from Scheduled Prescription</span>';
                entryHeader.style.borderBottom = '2px solid #e63757';
            } else {
                entryHeader.innerHTML = `Entry ${entryIndex + 1}`;
                if (allocationIsCancelled) {
                    entryHeader.innerHTML += ' <span style="color: #e63757; font-weight: bold; margin-left: 8px;">[CANCELLED]</span>';
                }
            }
            prescriptionSection.appendChild(entryHeader);

            // Single container for this allocation: per-group lines with items highlighted and details below
            const allocationDiv = document.createElement('div');
            allocationDiv.style.marginBottom = '25px';

            if (allocationId === 'removed_items') {
                allocationDiv.style.border = '2px solid #e63757';
                allocationDiv.style.backgroundColor = '#fff5f5';
            } else {
                allocationDiv.style.border = allocationIsCancelled ? '2px solid #e63757' : '1px solid #e3ebf6';
                allocationDiv.style.backgroundColor = allocationIsCancelled ? '#fff5f5' : '#f9fafd';
            }

            allocationDiv.style.borderRadius = '8px';
            allocationDiv.style.padding = '15px';

            if (allocationIsCancelled && allocationId !== 'removed_items') {
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
                if (commonUsage) metaParts.push(`Usage: ${commonUsage}`);
                if (commonExtInt) metaParts.push(`Ext/Int: ${commonExtInt}`);
                metaDiv.textContent = metaParts.join(' | ');
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
                const time = group.time || items[0]?.time || '';
                // usage and Ext/Int are common per allocation and shown above

                if (groupIndex > 0) {
                    const plusLine = document.createElement('div');
                    plusLine.style.textAlign = 'center';
                    plusLine.style.margin = '4px 0';
                    plusLine.style.fontWeight = 'bold';
                    plusLine.style.color = '#6b7280';
                    plusLine.textContent = '+';
                    allocationDiv.appendChild(plusLine);
                }

                const groupWrapper = document.createElement('div');
                groupWrapper.style.marginBottom = '6px';

                // Highlight logic based on change_type
                let badgeBg = '#e3f2fd'; // default blue
                let badgeColor = '#0d47a1';
                let changeStatusText = '';

                if (group.change_type === 'added') {
                    badgeBg = '#dcfce7'; // green
                    badgeColor = '#166534';
                    changeStatusText = ' <span style="font-size:0.75rem; color:#166534; font-weight:bold; background:#dcfce7; padding:2px 6px; border-radius:4px; margin-left:8px;">[ADDED]</span>';
                } else if (group.change_type === 'modified') {
                    badgeBg = '#fef9c3'; // yellow
                    badgeColor = '#854d0e';
                    changeStatusText = ' <span style="font-size:0.75rem; color:#854d0e; font-weight:bold; background:#fef9c3; padding:2px 6px; border-radius:4px; margin-left:8px;">[MODIFIED]</span>';
                } else if (group.change_type === 'removed') {
                    badgeBg = '#fee2e2'; // red
                    badgeColor = '#991b1b';
                    changeStatusText = ' <span style="font-size:0.75rem; color:#991b1b; font-weight:bold; background:#fee2e2; padding:2px 6px; border-radius:4px; margin-left:8px;">[REMOVED]</span>';
                }

                const line1 = document.createElement('div');
                line1.style.fontWeight = '600';
                line1.style.marginBottom = '2px';
                const prefix = groupIndex === 0 ? '• ' : '+ ';
                line1.innerHTML = `${prefix}<span style="display:inline-block;padding:2px 8px;border-radius:999px;background:${badgeBg};color:${badgeColor};">${itemNames || 'No medicines'}</span>${changeStatusText}`;

                const line2 = document.createElement('div');
                line2.style.fontSize = '0.85rem';
                line2.style.color = '#4b5563';
                const oilClass = group.oil_class || '';
                const details = [];
                if (dosageDisplay) details.push(`Dosage: ${dosageDisplay}`);
                if (time) details.push(`Time: ${time}`);
                if (ingredientsDisplay) details.push(`Ingredients: ${ingredientsDisplay}`);
                if (oilClass) details.push(`Oil Class: ${oilClass}`);
                line2.textContent = details.join(' | ');

                groupWrapper.appendChild(line1);
                groupWrapper.appendChild(line2);
                allocationDiv.appendChild(groupWrapper);
            });

            prescriptionSection.appendChild(allocationDiv);
        });

        prescriptionItemsDiv.appendChild(prescriptionSection);
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
                const therapyKey = item.therapy_name || 'Unknown Therapy';
                if (!therapyGroups[therapyKey]) {
                    therapyGroups[therapyKey] = [];
                }
                therapyGroups[therapyKey].push(item);
            }
        });

        // Render each therapy group
        Object.keys(therapyGroups).forEach(therapyName => {
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

                // Render items as single group
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

                // Display multiple item names as tags
                const itemsHtml = items.map(it => {
                    const isRemoved = it.is_removed || it.status === 'removed';
                    const removedBadge = isRemoved ? '<span style="color: #f6c343; font-weight: bold; margin-left: 4px;">[REMOVED]</span>' : '';
                    return `<span class="tag" style="display:inline-block;padding:4px 8px;margin:2px;background:${isRemoved ? '#fff3cd' : '#e3ebf6'};border-radius:4px;font-size:0.9em;">${escapeHtml(it.item_name)}${removedBadge}</span>`;
                }).join(' ');

                // Single dosage, usage, UNO, and internal/external for the entire group
                const dosage = group.dosage || items[0]?.dose || 'N/A';
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

                therapyGroupDiv.appendChild(itemCard);
            });

            therapySection.appendChild(therapyGroupDiv);
        });

        prescriptionItemsDiv.appendChild(therapySection);
    }

    if (prescriptionGroups.length === 0 && therapyItems.length === 0) {
        prescriptionItemsDiv.innerHTML = '<p style="color: #666; font-style: italic; padding: 20px;">No prescription or therapy items found for this patient on the selected date.</p>';
    }

    modal.style.display = 'block';
}

function viewChangeLog(patientId, date) {
    fetch(`/sheduling/prescription/api/change-log/?patient_id=${patientId}&date=${date}`)
        .then(response => {
            const contentType = response.headers.get('content-type');
            if (contentType && contentType.includes('application/json')) {
                return response.json();
            } else {
                throw new Error('Session expired. Please refresh and login again.');
            }
        })
        .then(data => {
            if (data.success) {
                showChangeLogModal(data.change_log);
            } else {
                alert('Error loading change log: ' + data.error);
            }
        })
        .catch(error => {
            alert('Error loading change log: ' + error.message);
        });
}

function formatChangeLogValues(values) {
    if (values === null || values === undefined || values === '') {
        return '';
    }
    if (typeof values === 'string') {
        return values;
    }

    // Special handling for prescription structures so normal users can understand
    // Example: { items_groups: [ { items: [...], dosage, time, procured_from, oil_class, ... }, ... ] }
    if (typeof values === 'object' && Array.isArray(values.items_groups)) {
        const groups = values.items_groups;
        const lines = [];

        groups.forEach((group, index) => {
            const entryNo = index + 1;
            const items = Array.isArray(group.items)
                ? group.items.map(it => it.item_name || '').filter(Boolean).join(', ')
                : '';
            const dosage = group.dosage || '';
            const time = group.time || '';
            const oilClass = group.oil_class || '';
            const procuredFrom = group.procured_from || '';
            const ingredients = Array.isArray(group.ingredients)
                ? group.ingredients.map(ing => ing.ingredient_name || ing.text || '').filter(Boolean).join(', ')
                : '';

            lines.push(`Entry ${entryNo}:`);
            if (items) {
                lines.push(`  Medicines: ${items}`);
            }
            if (dosage) {
                lines.push(`  Dosage: ${dosage}`);
            }
            if (time) {
                lines.push(`  Time: ${time}`);
            }
            if (procuredFrom) {
                lines.push(`  Procured From: ${procuredFrom}`);
            }
            if (oilClass) {
                lines.push(`  Oil Class: ${oilClass}`);
            }
            if (ingredients) {
                lines.push(`  Ingredients: ${ingredients}`);
            }
            // Blank line between entries
            if (index !== groups.length - 1) {
                lines.push('');
            }
        });

        return lines.join('\n');
    }

    try {
        // Pretty-print objects/arrays so they are readable in the UI
        return JSON.stringify(values, null, 2);
    } catch (e) {
        // Fallback to default string conversion
        return String(values);
    }
}

function showChangeLogModal(changeLog) {
    const modal = document.getElementById('changeLogModal');
    const content = document.getElementById('change-log-content');

    if (changeLog.length === 0) {
        content.innerHTML = '<p>No changes recorded for this prescription.</p>';
    } else {
        const filteredLog = changeLog.filter(entry => entry.action !== 'Status Change');

        if (filteredLog.length === 0) {
            content.innerHTML = '<p>No modifications recorded for this prescription.</p>';
        } else {
            content.innerHTML = filteredLog.map(entry => `
                    <div style="border: 1px solid var(--border); border-radius: 8px; padding: 15px; margin-bottom: 10px;">
                        <h4>${escapeHtml(entry.action)}</h4>
                        <p><strong>Patient:</strong> ${escapeHtml(entry.patient_name)}</p>
                        <p><strong>Date:</strong> ${formatDate(entry.date)}</p>
                        <p><strong>Changed By:</strong> ${escapeHtml(entry.changed_by)}</p>
                        <p><strong>Time:</strong> ${formatDate(entry.timestamp, true)}</p>
                        ${entry.before_values ? `<p><strong>Before:</strong><br><pre style="white-space: pre-wrap; background:#f8fafc; padding:8px; border-radius:4px; margin-top:4px;">${escapeHtml(formatChangeLogValues(entry.before_values))}</pre></p>` : ''}
                        ${entry.after_values ? `<p><strong>After:</strong><br><pre style="white-space: pre-wrap; background:#f8fafc; padding:8px; border-radius:4px; margin-top:4px;">${escapeHtml(formatChangeLogValues(entry.after_values))}</pre></p>` : ''}
                    </div>
                `).join('');
        }
    }

    modal.style.display = 'block';
}

function closePrescriptionModal() {
    document.getElementById('prescriptionModal').style.display = 'none';
}

function closeChangeLogModal() {
    document.getElementById('changeLogModal').style.display = 'none';
}

function showLoading(status) {
    document.getElementById(`${status}-loading`).style.display = 'block';
}

function hideLoading(status) {
    document.getElementById(`${status}-loading`).style.display = 'none';
}

function showAlert(type, message) {
    const alertDiv = document.createElement('div');
    alertDiv.className = `alert alert-${type}`;
    alertDiv.textContent = message;

    const container = document.querySelector('.container');
    container.insertBefore(alertDiv, container.firstChild);

    setTimeout(() => {
        alertDiv.remove();
    }, 5000);
}

// Format date as DD/MM/YYYY HH:mm
function formatDate(dateStr, includeTime = false) {
    if (!dateStr) return '';
    try {
        let date;
        if (typeof dateStr === 'string') {
            // Check if it's already an ISO timestamp (has T)
            if (dateStr.includes('T')) {
                date = new Date(dateStr);
            } else {
                // For YYYY-MM-DD format
                date = new Date(dateStr + 'T00:00:00');
            }
        } else if (dateStr instanceof Date) {
            date = dateStr;
        } else {
            return dateStr;
        }

        if (isNaN(date.getTime())) return dateStr;

        const day = String(date.getDate()).padStart(2, '0');
        const month = String(date.getMonth() + 1).padStart(2, '0');
        const year = date.getFullYear();
        let formattedDate = `${day}/${month}/${year}`;

        if (includeTime || (typeof dateStr === 'string' && dateStr.includes('T'))) {
            let hours = date.getHours();
            const minutes = String(date.getMinutes()).padStart(2, '0');
            const ampm = hours >= 12 ? 'PM' : 'AM';
            hours = hours % 12;
            hours = hours ? hours : 12; // the hour '0' should be '12'
            formattedDate += ` ${String(hours).padStart(2, '0')}:${minutes} ${ampm}`;
        }

        return formattedDate;
    } catch (e) {
        return dateStr;
    }
}
// Return original if error
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Print Prescription Schedule to PDF
function printPrescriptionScheduleToPDF() {
    console.log('[PDF] Button clicked, starting PDF generation...');
    const selectedDate = document.getElementById('scheduled-date').value;

    if (!selectedDate) {
        alert('Please select a date first using the date filter');
        return;
    }

    console.log('[PDF] Selected date:', selectedDate);

    // Check if jsPDF is available
    if (typeof window.jspdf === 'undefined') {
        alert('PDF library not loaded. Please refresh the page and try again.');
        console.error('[PDF] jsPDF library not found');
        return;
    }

    // Show loading
    const printBtn = document.getElementById('print-prescription-pdf');
    const originalText = printBtn.innerHTML;
    printBtn.disabled = true;
    printBtn.innerHTML = '<span>⏳</span> Generating PDF...';

    console.log('[PDF] Fetching prescription data...');
    // Fetch prescription data
    fetch(`/sheduling/prescription/api/prescription-data/?status=scheduled&date=${selectedDate}`)
        .then(response => {
            const contentType = response.headers.get('content-type');
            if (contentType && contentType.includes('application/json')) {
                return response.json();
            } else {
                throw new Error('Session expired or server connection lost. Please refresh the page and login again.');
            }
        })
        .then(data => {
            console.log('[PDF] Prescription data received:', data.success, 'patients:', data.data?.length || 0);
            // Also fetch therapy data to get ALL scheduled therapies (with therapists, nurse treatments, and zero-therapist)
            // Fetch both 'allocated' and 'scheduled' status to get all scheduled therapies
            // Use include_zero_therapist=true to get zero-therapist therapies for prescription PDF
            console.log('[PDF] Fetching therapy data...');
            console.log('[PDF] Therapy API URLs:');
            console.log('[PDF]   - Allocated:', `/sheduling/scheduling/api/therapy-data/?status=allocated&date=${selectedDate}&include_zero_therapist=true`);
            console.log('[PDF]   - Scheduled:', `/sheduling/scheduling/api/therapy-data/?status=scheduled&date=${selectedDate}&include_zero_therapist=true`);

            Promise.all([
                fetch(`/sheduling/scheduling/api/therapy-data/?status=allocated&date=${selectedDate}&include_zero_therapist=true`).then(r => r.headers.get('content-type').includes('json') ? r.json() : Promise.reject('Session expired')),
                fetch(`/sheduling/scheduling/api/therapy-data/?status=scheduled&date=${selectedDate}&include_zero_therapist=true`).then(r => r.headers.get('content-type').includes('json') ? r.json() : Promise.reject('Session expired')),
                fetch(`/sheduling/scheduling/api/therapy-data/?status=draft&date=${selectedDate}&include_zero_therapist=true`).then(r => r.headers.get('content-type').includes('json') ? r.json() : Promise.reject('Session expired'))
            ]).then(([allocatedData, scheduledData, draftData]) => {
                console.log('[PDF] Therapy API Response - Allocated:', allocatedData.success, 'count:', allocatedData.data?.length || 0);
                console.log('[PDF] Therapy API Response - Scheduled:', scheduledData.success, 'count:', scheduledData.data?.length || 0);
                console.log('[PDF] Therapy API Response - Draft:', draftData.success, 'count:', draftData.data?.length || 0);

                if (allocatedData.data && allocatedData.data.length > 0) {
                    console.log('[PDF] Sample allocated therapy:', allocatedData.data[0]);
                }
                if (scheduledData.data && scheduledData.data.length > 0) {
                    console.log('[PDF] Sample scheduled therapy:', scheduledData.data[0]);
                }
                if (draftData.data && draftData.data.length > 0) {
                    console.log('[PDF] Sample draft therapy:', draftData.data[0]);
                }

                // Combine all responses
                const therapyData = {
                    success: allocatedData.success || scheduledData.success || draftData.success,
                    data: [...(allocatedData.data || []), ...(scheduledData.data || []), ...(draftData.data || [])]
                };

                // Deduplicate by booking_id or id
                const seen = new Set();
                therapyData.data = therapyData.data.filter(t => {
                    const key = t.booking_id || t.id;
                    if (seen.has(key)) return false;
                    seen.add(key);
                    return true;
                });

                console.log('[PDF Debug] Combined therapy data - allocated:', allocatedData.data?.length || 0, 'scheduled:', scheduledData.data?.length || 0, 'total unique:', therapyData.data.length);

                return therapyData;
            }).then(therapyData => {
                // Get all patients from prescriptions
                const prescriptionPatients = new Set();
                if (data.success && data.data.length > 0) {
                    data.data.forEach(item => {
                        prescriptionPatients.add(item.registration_no);
                    });
                }

                // Get ALL patients with ANY therapies who don't have prescriptions
                // This ensures we include patients with only therapies in the PDF
                const therapyOnlyPatients = new Set();
                const prescriptionRegNos = new Set();
                if (data.success && data.data.length > 0) {
                    data.data.forEach(item => {
                        if (item.registration_no) prescriptionRegNos.add(item.registration_no.trim().toUpperCase());
                    });
                }

                if (therapyData.success && therapyData.data) {
                    therapyData.data.forEach(therapy => {
                        const regNo = therapy.patient_reg_no;
                        if (regNo) {
                            const trimmedReg = regNo.trim().toUpperCase();
                            // Add patient if they have therapy but NO prescription
                            if (!prescriptionRegNos.has(trimmedReg)) {
                                therapyOnlyPatients.add(trimmedReg);
                            }
                        }
                    });
                }

                console.log('[PDF] Prescription patients:', prescriptionRegNos.size);
                console.log('[PDF] Therapy-only patients:', therapyOnlyPatients.size);

                // Add placeholder entries for patients with only therapies
                const additionalPatientsPromises = Array.from(therapyOnlyPatients).map(regNo => {
                    const therapyForPatient = therapyData.data.find(t => t.patient_reg_no?.trim().toUpperCase() === regNo);
                    const patientId = therapyForPatient ? (therapyForPatient.patient_id || therapyForPatient.id) : null;

                    if (patientId) {
                        return fetch(`/sheduling/prescription/api/prescription-details/?patient_id=${patientId}&date=${selectedDate}&only_scheduled=true`)
                            .then(res => res.headers.get('content-type').includes('json') ? res.json() : Promise.reject('Session expired'))
                            .then(detailData => {
                                if (detailData.success && detailData.patient_info) {
                                    return {
                                        patient_id: patientId,
                                        scheduling_id: null,
                                        patient_name: detailData.patient_info.name || therapyForPatient.patient_name || 'Unknown',
                                        registration_no: therapyForPatient.patient_reg_no,
                                        room_no: detailData.patient_info.room_no || therapyForPatient.patient_room_no || null,
                                        doctor_name: detailData.patient_info.doctor_name || '',
                                        doctor_team: detailData.patient_info.doctor_team || '',
                                        doa: detailData.patient_info.doa || '',
                                        age: detailData.patient_info.age || '',
                                        sex: detailData.patient_info.sex || '',
                                        prescription_count: 0,
                                        status: 'scheduled',
                                        details: {
                                            success: true,
                                            patient_info: detailData.patient_info,
                                            prescription_groups: detailData.prescription_groups || [],
                                            therapy_items: detailData.therapy_items || []
                                        }
                                    };
                                } else {
                                    // Fallback if details not available
                                    return {
                                        patient_id: patientId,
                                        scheduling_id: null,
                                        patient_name: therapyForPatient ? therapyForPatient.patient_name : 'Unknown',
                                        registration_no: regNo,
                                        room_no: therapyForPatient ? therapyForPatient.patient_room_no : null,
                                        doctor_name: '',
                                        doctor_team: '',
                                        prescription_count: 0,
                                        status: 'scheduled',
                                        details: {
                                            success: true,
                                            patient_info: {
                                                name: therapyForPatient ? therapyForPatient.patient_name : 'Unknown',
                                                registration_no: regNo,
                                                room_no: therapyForPatient ? therapyForPatient.patient_room_no : null,
                                                age: '',
                                                sex: '',
                                                doctor_name: '',
                                                doctor_team: '',
                                                doa: ''
                                            },
                                            prescription_groups: [],
                                            therapy_items: []
                                        }
                                    };
                                }
                            })
                            .catch(error => {
                                console.error(`Error fetching details for patient ${regNo}:`, error);
                                // Fallback on error
                                return {
                                    patient_id: patientId,
                                    scheduling_id: null,
                                    patient_name: therapyForPatient ? therapyForPatient.patient_name : 'Unknown',
                                    registration_no: regNo,
                                    room_no: therapyForPatient ? therapyForPatient.patient_room_no : null,
                                    doctor_name: '',
                                    doctor_team: '',
                                    prescription_count: 0,
                                    status: 'scheduled',
                                    details: {
                                        success: true,
                                        patient_info: {
                                            name: therapyForPatient ? therapyForPatient.patient_name : 'Unknown',
                                            registration_no: regNo,
                                            room_no: therapyForPatient ? therapyForPatient.patient_room_no : null,
                                            age: '',
                                            sex: '',
                                            doctor_name: '',
                                            doctor_team: '',
                                            doa: ''
                                        },
                                        prescription_groups: [],
                                        therapy_items: []
                                    }
                                };
                            });
                    } else {
                        // No patient ID, return basic info
                        return Promise.resolve({
                            patient_id: null,
                            scheduling_id: null,
                            patient_name: therapyForPatient ? therapyForPatient.patient_name : 'Unknown',
                            registration_no: regNo,
                            room_no: therapyForPatient ? therapyForPatient.patient_room_no : null,
                            doctor_name: '',
                            doctor_team: '',
                            prescription_count: 0,
                            status: 'scheduled',
                            details: {
                                success: true,
                                patient_info: {
                                    name: therapyForPatient ? therapyForPatient.patient_name : 'Unknown',
                                    registration_no: regNo,
                                    room_no: therapyForPatient ? therapyForPatient.patient_room_no : null,
                                    age: '',
                                    sex: '',
                                    doctor_name: '',
                                    doctor_team: ''
                                },
                                prescription_groups: [],
                                therapy_items: []
                            }
                        });
                    }
                });

                // Wait for all patient details to be fetched, then continue
                Promise.all(additionalPatientsPromises).then(additionalPatients => {
                    const prescriptionPatientsData = data.success && data.data.length > 0 ? data.data : [];
                    const patientsMap = new Map();
                    const nameRoomMap = new Map(); // Fallback map for name+room matching

                    const normalizeStrict = (val) => (val || '').toString().trim().toUpperCase();
                    const normalizeFuzzy = (val) => (val || '').toString().toLowerCase().replace(/[^a-z0-9]/g, '').trim();

                    // 1. Add prescription patients (primary source)
                    prescriptionPatientsData.forEach(p => {
                        const reg = normalizeStrict(p.registration_no);
                        const name = normalizeFuzzy(p.patient_name);
                        const room = normalizeFuzzy(p.room_no);
                        const nrKey = `${name}_${room}`;

                        if (reg) patientsMap.set(reg, p);
                        if (nrKey) nameRoomMap.set(nrKey, p);
                    });

                    // 2. Merge/Add therapy-only patients
                    additionalPatients.forEach(p => {
                        if (!p) return;
                        const reg = normalizeStrict(p.registration_no);
                        const name = normalizeFuzzy(p.patient_name);
                        const room = normalizeFuzzy(p.room_no);
                        const nrKey = `${name}_${room}`;

                        let existing = null;
                        if (reg && patientsMap.has(reg)) {
                            existing = patientsMap.get(reg);
                        } else if (nrKey && nameRoomMap.has(nrKey)) {
                            existing = nameRoomMap.get(nrKey);
                            console.log('[PDF Debug] Merged patient by Name+Room instead of RegNo:', p.patient_name);
                        }

                        if (!existing) {
                            if (reg) patientsMap.set(reg, p);
                            if (nrKey) nameRoomMap.set(nrKey, p);
                        } else {
                            // Merge details if the existing one is missing them
                            if (!existing.details && p.details) existing.details = p.details;

                            // Merge age/sex/doctor if missing
                            if (!existing.age && p.age) existing.age = p.age;
                            if (!existing.sex && p.sex) existing.sex = p.sex;
                            if (!existing.doctor_name && p.doctor_name) {
                                existing.doctor_name = p.doctor_name;
                            }
                            if (!existing.doctor_team && p.doctor_team) {
                                existing.doctor_team = p.doctor_team;
                            }
                            if (!existing.doa && p.doa) {
                                existing.doa = p.doa;
                            }

                            // Ensure we don't lose the registration number if one source had a better one
                            if (!existing.registration_no && p.registration_no) {
                                existing.registration_no = p.registration_no;
                            }
                        }
                    });

                    // Get unique patients from patientsMap and nameRoomMap
                    const allPatientsSet = new Set();
                    patientsMap.forEach(p => allPatientsSet.add(p));
                    nameRoomMap.forEach(p => allPatientsSet.add(p));
                    const allPatients = Array.from(allPatientsSet);

                    console.log('[PDF Debug] Total unique patients for PDF:', allPatients.length);

                    if (allPatients.length > 0) {
                        // Fetch fresh details for each patient to ensure combined data is captured
                        const patientPromises = allPatients.map(item => {
                            // We trigger a fresh fetch for everyone to guarantee consistency
                            return fetch(`/sheduling/prescription/api/prescription-details/?patient_id=${item.patient_id}&date=${selectedDate}&only_scheduled=true`)
                                .then(res => res.headers.get('content-type').includes('json') ? res.json() : Promise.reject('Session expired'))
                                .then(detailData => {
                                    const merged = { ...item };
                                    if (detailData.success && detailData.patient_info) {
                                        merged.details = detailData;
                                        if (detailData.time_order_map) {
                                            window.PRESCRIPTION_TIME_ORDER_MAP = detailData.time_order_map;
                                        }
                                        merged.age = merged.age || detailData.patient_info.age;
                                        merged.sex = merged.sex || detailData.patient_info.sex;
                                        if (!merged.doctor_name && detailData.patient_info.doctor_name) {
                                            merged.doctor_name = detailData.patient_info.doctor_name;
                                        }
                                        if (!merged.doctor_team && detailData.patient_info.doctor_team) {
                                            merged.doctor_team = detailData.patient_info.doctor_team;
                                        }
                                        if (!merged.doa && detailData.patient_info.doa) {
                                            merged.doa = detailData.patient_info.doa;
                                        }
                                    }
                                    return merged;
                                })
                                .catch(err => {
                                    console.error('[PDF Error] Fetching details failed:', err);
                                    return item;
                                });
                        });

                        Promise.all(patientPromises)
                            .then(patientsWithDetails => {
                                // Map therapies by patient registration number and Name+Room
                                const therapiesByReg = {};
                                const therapiesByNameRoom = {};
                                const zeroTherapiesByReg = {};
                                const zeroTherapiesByNameRoom = {};

                                if (therapyData.success && therapyData.data) {
                                    therapyData.data.forEach(therapy => {
                                        const reg = normalizeStrict(therapy.patient_reg_no);
                                        const nrKey = `${normalizeFuzzy(therapy.patient_name)}_${normalizeFuzzy(therapy.patient_room_no)}`;

                                        const therapistsCount = therapy.therapists ? therapy.therapists.length : 0;
                                        const isNurse = therapy.is_nurse_treatment === true;
                                        const isZeroTherapist = !isNurse && therapistsCount === 0;

                                        if (isZeroTherapist) {
                                            if (reg) {
                                                if (!zeroTherapiesByReg[reg]) zeroTherapiesByReg[reg] = [];
                                                zeroTherapiesByReg[reg].push(therapy);
                                            }
                                            if (nrKey) {
                                                if (!zeroTherapiesByNameRoom[nrKey]) zeroTherapiesByNameRoom[nrKey] = [];
                                                zeroTherapiesByNameRoom[nrKey].push(therapy);
                                            }
                                        } else {
                                            if (reg) {
                                                if (!therapiesByReg[reg]) therapiesByReg[reg] = [];
                                                therapiesByReg[reg].push(therapy);
                                            }
                                            if (nrKey) {
                                                if (!therapiesByNameRoom[nrKey]) therapiesByNameRoom[nrKey] = [];
                                                therapiesByNameRoom[nrKey].push(therapy);
                                            }
                                        }
                                    });
                                }

                                // Create a map of therapy times by therapy name and patient for lookup
                                const therapyTimeMap = {};
                                if (therapyData.success && therapyData.data) {
                                    therapyData.data.forEach(therapy => {
                                        const regNo = therapy.patient_reg_no;
                                        const therapyName = therapy.therapy_name;
                                        const timeslot = therapy.timeslot || '';
                                        if (regNo && therapyName && timeslot) {
                                            const key = `${normalizeStrict(regNo)}_${therapyName}`;
                                            therapyTimeMap[key] = timeslot;
                                        }
                                    });
                                }

                                // Convert therapies from therapy API to therapy items format
                                const convertTherapyToTherapyItem = (therapy) => {
                                    const therapyName = therapy.therapy_name || 'Unknown Therapy';
                                    const timeslot = therapy.timeslot || '';

                                    // Extract items from therapy if available
                                    // Therapies from API might have items_groups or items structure
                                    let itemsArray = [];
                                    if (therapy.items_groups && Array.isArray(therapy.items_groups)) {
                                        // If items_groups exists, use it
                                        itemsArray = therapy.items_groups.map(group => ({
                                            items: group.items || [],
                                            dosage: group.dosage || '',
                                            uno: group.uno || '',
                                            usage: group.usage || '',
                                            usage_array: group.usage_array || [],
                                            oil_class: group.oil_class || '',
                                            ingredients: group.ingredients || []
                                        }));
                                    } else if (therapy.items && Array.isArray(therapy.items)) {
                                        // If items array exists, wrap it
                                        itemsArray = [{
                                            items: therapy.items,
                                            dosage: therapy.dosage || '',
                                            uno: therapy.uno || '',
                                            usage: therapy.usage || '',
                                            usage_array: therapy.usage_array || [],
                                            oil_class: therapy.oil_class || '',
                                            ingredients: therapy.ingredients || []
                                        }];
                                    } else {
                                        // If no items structure, create a minimal entry with just therapy name
                                        // This handles therapies that don't have items in the API response
                                        itemsArray = [{
                                            items: [{
                                                item_name: therapyName,
                                                item_code: therapy.therapy_code || '',
                                                type: 'therapy'
                                            }],
                                            dosage: therapy.dosage || '',
                                            uno: therapy.uno || '',
                                            usage: therapy.usage || '',
                                            usage_array: therapy.usage_array || [],
                                            oil_class: therapy.oil_class || '',
                                            ingredients: therapy.ingredients || []
                                        }];
                                    }

                                    // Create a therapy item structure similar to prescription details API
                                    return {
                                        group_id: `therapy_api_${therapy.booking_id || therapy.id}`,
                                        therapy_name: therapyName,
                                        therapy_id: therapy.id || therapy.booking_id,
                                        dosage: therapy.dosage || '',
                                        usage: therapy.usage || '',
                                        usage_array: therapy.usage_array || [],
                                        internal_external: therapy.internal_external || '',
                                        uno: therapy.uno || '',
                                        oil_class: therapy.oil_class || '',
                                        ingredients: therapy.ingredients || [],
                                        booking_id: therapy.booking_id,
                                        booking_status: therapy.status || therapy.booking_status || 'scheduled',
                                        booking_is_cancelled: false,
                                        timeslot: timeslot,
                                        time: timeslot,
                                        from_date: therapy.from_date || therapy.from || '',
                                        to_date: therapy.to_date || therapy.to || '',
                                        items: itemsArray,
                                        is_group: true
                                    };
                                };

                                // Add therapy items and zero-therapist therapies to each patient
                                const patientsWithAllData = patientsWithDetails.map(item => {
                                    const reg = normalizeStrict(item.registration_no);
                                    const nrKey = `${normalizeFuzzy(item.patient_name)}_${normalizeFuzzy(item.room_no)}`;

                                    // Get unique therapies for this patient from all possible keys
                                    const getUniqueTherapies = (regKey, nameRoomKey, mainMap, fallbackMap) => {
                                        const results = [];
                                        const seenIds = new Set();

                                        const addToList = (list) => {
                                            if (list) {
                                                list.forEach(t => {
                                                    const id = t.booking_id || t.id;
                                                    if (id && !seenIds.has(id)) {
                                                        seenIds.add(id);
                                                        results.push(t);
                                                    }
                                                });
                                            }
                                        };

                                        if (regKey) addToList(mainMap[regKey]);
                                        if (nameRoomKey) addToList(fallbackMap[nameRoomKey]);

                                        return results;
                                    };

                                    const zeroTherapies = getUniqueTherapies(reg, nrKey, zeroTherapiesByReg, zeroTherapiesByNameRoom);
                                    const therapiesFromAPI = getUniqueTherapies(reg, nrKey, therapiesByReg, therapiesByNameRoom);

                                    console.log('[PDF Debug] Attaching therapies to:', item.patient_name, '| Reg:', reg, '| NR:', nrKey);
                                    console.log('[PDF Debug]   - Found therapies:', therapiesFromAPI.length);
                                    console.log('[PDF Debug]   - Found zero-therapist:', zeroTherapies.length);

                                    if (zeroTherapies.length > 0) {
                                        console.log('[PDF Debug] Patient', reg, 'has', zeroTherapies.length, 'zero-therapist therapies:', zeroTherapies.map(t => t.therapy_name));
                                    }
                                    if (therapiesFromAPI.length > 0) {
                                        console.log('[PDF Debug] Patient', reg, 'has', therapiesFromAPI.length, 'therapies from API:', therapiesFromAPI.map(t => t.therapy_name));
                                    }

                                    // Get therapy items from prescription details API
                                    const therapyItemsFromDetails = item.details?.therapy_items || [];

                                    // Convert therapies from therapy API to therapy items format
                                    const therapyItemsFromAPI = therapiesFromAPI.map(convertTherapyToTherapyItem);
                                    const zeroTherapyItemsFromAPI = zeroTherapies.map(convertTherapyToTherapyItem);

                                    // Combine ALL sources (Details, Regular API, Zero API) and enhance with timeslot information
                                    // Merging zero-therapist items here ensures they participate in deduplication and aren't printed twice
                                    const allTherapyItems = [...therapyItemsFromDetails, ...therapyItemsFromAPI, ...zeroTherapyItemsFromAPI];

                                    // Deduplicate and Merge Logic
                                    // We likely have the same therapy from multiple sources (Details API vs Therapy API)
                                    // Details API gives Allocation info (From/To). Therapy API gives specific Booking info (Time) for today.
                                    // We need to merge them into a single comprehensive entry per Allocation ID.

                                    // Deduplicate and Merge Logic - Two Pass Approach
                                    // Pass 1: Deduplicate by therapy_id (Allocation ID)
                                    const mergedById = new Map();

                                    // Helper function to merge properties
                                    function mergeTherapyItems(target, source) {
                                        // Helper defined below is available here due to hoisting

                                        // Prioritize fields that are present in Source but missing/placeholder in Target
                                        if (!isNonEmptyString(target.timeslot) && isNonEmptyString(source.timeslot)) target.timeslot = source.timeslot;
                                        if (!isNonEmptyString(target.time) && isNonEmptyString(source.time)) target.time = source.time;

                                        // Usage merging
                                        if (!isNonEmptyString(target.usage) && isNonEmptyString(source.usage)) target.usage = source.usage;
                                        if ((!target.usage_array || target.usage_array.length === 0) && source.usage_array && source.usage_array.length > 0) {
                                            target.usage_array = source.usage_array;
                                        }

                                        // Dates
                                        if (!isNonEmptyString(target.from_date) && isNonEmptyString(source.from_date)) target.from_date = source.from_date;
                                        if (!isNonEmptyString(target.to_date) && isNonEmptyString(source.to_date)) target.to_date = source.to_date;

                                        // Booking status
                                        if (source.booking_status === 'scheduled' || source.booking_status === 'allocated') {
                                            target.booking_status = source.booking_status;
                                        }

                                        // ID Corrections
                                        if ((!target.therapy_id) && source.therapy_id) target.therapy_id = source.therapy_id;

                                        // Items (Ingredients/Dosage) logic
                                        // Therapy-data API sometimes returns placeholder "minimal" items for some roles (e.g., Vasanthi),
                                        // which would overwrite the fully-populated details payload and cause missing:
                                        // - oils / medicinal mixtures (dosage column)
                                        // - usage notes / ingredients (ingredients column)
                                        // Only overwrite items if the source contains meaningful details.
                                        function isNonEmptyString(v) {
                                            if (v === null || v === undefined) return false;
                                            const s = String(v).trim();
                                            // Reject empty or common placeholders
                                            return s !== '' && s !== '—' && s !== '-' && s !== 'null' && s !== 'None';
                                        }
                                        function hasMeaningfulNestedGroupDetails(items) {
                                            if (!Array.isArray(items) || items.length === 0) return false;
                                            // Nested style: [{ items: [...], dosage, oil_class, ingredients, ... }, ...]
                                            const looksNested = items[0] && items[0].items && Array.isArray(items[0].items);
                                            if (!looksNested) return false;

                                            return items.some(group => {
                                                if (!group || typeof group !== 'object') return false;

                                                // MAJOR FIX: Count actual medicine products as a meaningful detail
                                                const medicineCount = (group.items || []).filter(it =>
                                                    it.item_name &&
                                                    it.type !== 'therapy' &&
                                                    !it.item_name.toLowerCase().includes('unknown')
                                                ).length;

                                                const dosage = group.dosage ?? group.dose ?? group.quantity ?? '';
                                                const oilClass = group.oil_class ?? group.oilClass ?? group.oil_class_name ?? '';
                                                const usage = group.usage ?? '';
                                                const ingredients = group.ingredients;

                                                const ingredientsNonEmpty = (() => {
                                                    if (!ingredients) return false;
                                                    if (Array.isArray(ingredients)) return ingredients.length > 0;
                                                    if (typeof ingredients === 'string') return isNonEmptyString(ingredients);
                                                    return false;
                                                })();

                                                // Consider it "real" if we have at least 2 meaningful fields OR a medicine product.
                                                // This avoids overwriting the fully-populated details payload with minimal placeholders,
                                                // but ensures we take the data if it contains actual products or medicine names.
                                                const detailsCount = [
                                                    isNonEmptyString(dosage),
                                                    isNonEmptyString(oilClass),
                                                    ingredientsNonEmpty,
                                                    isNonEmptyString(usage)
                                                ].filter(Boolean).length;

                                                // If we have medicines, count it strongly
                                                return (detailsCount >= 2) || (medicineCount > 0);
                                            });
                                        }

                                        const sourceHasRealItems = hasMeaningfulNestedGroupDetails(source.items);
                                        const targetHasRealItems = hasMeaningfulNestedGroupDetails(target.items);

                                        // Overwrite if source has real items, OR if target currently has NO items/empty items
                                        if (sourceHasRealItems || (!targetHasRealItems && (source.items && source.items.length > 0))) {
                                            target.items = source.items;
                                        }
                                    }

                                    allTherapyItems.forEach(item => {
                                        let uniqueId = (item.therapy_id || '').toString();
                                        if (!uniqueId) {
                                            uniqueId = `temp_no_id_${item.therapy_name || 'unknown'}_${item.booking_id || Math.random()}`;
                                        }

                                        if (!mergedById.has(uniqueId)) {
                                            mergedById.set(uniqueId, { ...item });
                                        } else {
                                            const existing = mergedById.get(uniqueId);
                                            mergeTherapyItems(existing, item);
                                        }
                                    });

                                    // Pass 2: Deduplicate by Name (Merge orphans with missing/different IDs)
                                    const mergedByName = new Map();

                                    mergedById.forEach(item => {
                                        const nameKey = (item.therapy_name || '').trim().toLowerCase();
                                        if (!nameKey) return;

                                        if (!mergedByName.has(nameKey)) {
                                            mergedByName.set(nameKey, item);
                                        } else {
                                            // Duplicate Name found - Merge!
                                            const existing = mergedByName.get(nameKey);
                                            mergeTherapyItems(existing, item);
                                        }
                                    });

                                    // Convert map back to array
                                    const uniqueTherapyItems = Array.from(mergedByName.values());

                                    return {
                                        ...item,
                                        therapy_items: uniqueTherapyItems,
                                        zero_therapist_therapies: [] // Empty this since we merged them into therapy_items above
                                    };
                                });

                                // DEBUG: Log therapy data before passing to PDF
                                console.log('[PDF MAIN] ========== BEFORE CALLING PDF GENERATOR ==========');
                                console.log('[PDF MAIN] Total patients:', patientsWithAllData.length);
                                let totalTherapyItems = 0;
                                let totalZeroTherapist = 0;
                                patientsWithAllData.forEach((patient, idx) => {
                                    const therapyCount = (patient.therapy_items || []).length;
                                    const zeroCount = (patient.zero_therapist_therapies || []).length;
                                    totalTherapyItems += therapyCount;
                                    totalZeroTherapist += zeroCount;
                                    if (therapyCount > 0 || zeroCount > 0) {
                                        console.log(`[PDF MAIN] Patient ${idx + 1} (${patient.patient_name}):`,
                                            'therapy_items:', therapyCount,
                                            'zero_therapist:', zeroCount);
                                    }
                                });
                                console.log('[PDF MAIN] TOTAL therapy_items:', totalTherapyItems);
                                console.log('[PDF MAIN] TOTAL zero_therapist_therapies:', totalZeroTherapist);
                                console.log('[PDF MAIN] ========================================');

                                printBtn.disabled = false;
                                printBtn.innerHTML = originalText;
                                generatePrescriptionPDF(patientsWithAllData, selectedDate);
                            })
                            .catch(error => {
                                printBtn.disabled = false;
                                printBtn.innerHTML = originalText;
                                // Still generate PDF without therapy items
                                generatePrescriptionPDF(patientsWithDetails, selectedDate);
                            });
                    } else {
                        printBtn.disabled = false;
                        printBtn.innerHTML = originalText;
                        alert('No scheduled prescriptions or therapies found for the selected date.');
                    }
                })
                    .catch(error => {
                        printBtn.disabled = false;
                        printBtn.innerHTML = originalText;
                        alert('Error fetching patient details: ' + error.message);
                    });
            })
                .catch(error => {
                    printBtn.disabled = false;
                    printBtn.innerHTML = originalText;
                    alert('Error fetching therapy data: ' + error.message);
                });
        })
        .catch(error => {
            printBtn.disabled = false;
            printBtn.innerHTML = originalText;
            alert('Error fetching prescription data: ' + error.message);
        });
}

function generatePrescriptionPDF(prescriptionData, date) {
    // Load the new PDF generation function
    if (typeof generatePrescriptionPDF_NEW === 'undefined') {
        // Dynamically load the new PDF script
        const script = document.createElement('script');
        script.src = '/static/js/prescription_pdf_new.js?v=' + new Date().getTime();
        script.onload = function () {
            generatePrescriptionPDF_NEW(prescriptionData, date);
        };
        script.onerror = function () {
            console.error('[PDF] Failed to load new PDF generator');
            alert('Failed to load PDF generator. Please refresh the page and try again.');
        };
        document.head.appendChild(script);
    } else {
        generatePrescriptionPDF_NEW(prescriptionData, date);
    }
}