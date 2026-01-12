// Initialize the dashboard
        document.addEventListener('DOMContentLoaded', function() {
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
                tab.addEventListener('click', function() {
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
            document.getElementById('draft-date').addEventListener('change', function() {
                loadPrescriptionData('draft', this.value);
            });
            document.getElementById('scheduled-date').addEventListener('change', function() {
                loadPrescriptionData('scheduled', this.value);
            });
            document.getElementById('dispatched-date').addEventListener('change', function() {
                loadPrescriptionData('dispatched', this.value);
            });
            
            // Print to PDF button
            document.getElementById('print-prescription-pdf').addEventListener('click', function() {
                printPrescriptionScheduleToPDF();
            });
            
            // Close modals when clicking outside
            window.onclick = function(event) {
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
        
        function loadPrescriptionData(status, date) {
            const url = `/sheduling/prescription/api/prescription-data/?status=${status}&date=${date}`;
            
            fetch(url)
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        updateTable(status, data.data, date);
                        updateStats(data.data, status);
                    } else {
                        console.error('API Error:', data.error);
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
                
                tbody.innerHTML = `
                    <tr>
                        <td colspan="7" class="empty-state">
                            <div class="empty-state-icon">📋</div>
                            <div>${message}</div>
                        </td>
                    </tr>
                `;
                return;
            }
            
            data.forEach(item => {
                const row = document.createElement('tr');
                row.innerHTML = `
                    <td>
                        <div class="patient-details">
                            <div class="patient-name">${escapeHtml(item.patient_name)}</div>
                            <div class="patient-meta">ID: ${escapeHtml(item.patient_id)}</div>
                        </div>
                    </td>
                    <td>${escapeHtml(item.registration_no)}</td>
                    <td>${escapeHtml(item.room_no || '-')}</td>
                    <td>${escapeHtml(item.doctor_name)}</td>
                    <td>
                        <span class="prescription-count">${item.prescription_count}</span>
                    </td>
                    <td>
                        <span class="status-badge status-${status}">${getStatusLabel(status)}</span>
                    </td>
                    ${status === 'scheduled' ? `<td>${escapeHtml(item.sent_to || '-')}</td>` : ''}
                    ${status === 'dispatched' ? `<td>${escapeHtml(item.dispatched_from || '-')}</td>` : ''}
                    ${status === 'dispatched' ? `<td>${formatDate(item.dispatched_at) || '-'}</td>` : ''}
                    <td>
                        <div style="display: flex; gap: 8px;">
                            <button class="btn btn-outline btn-small" onclick="viewPrescriptionDetails(${item.patient_id}, '${date}')">
                                View Details
                            </button>
                            ${status === 'draft' ? `
                                <button class="btn btn-outline btn-small" onclick="viewChangeLog(${item.patient_id}, '${date}')">
                                    Change Log
                                </button>
                            ` : ''}
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
        
        function sendFinalPrescription() {
            const date = document.getElementById('draft-date').value;
            if (!date) {
                alert('Please select a date first');
                return;
            }
            
            if (!confirm(`Are you sure you want to send all draft prescriptions for ${formatDate(date)} to procurement departments?`)) {
                return;
            }
            
            showLoading('draft');
            
            fetch('/sheduling/prescription/api/send-final-prescription/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    date: date
                })
            })
            .then(response => response.json())
            .then(data => {
                hideLoading('draft');
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
                hideLoading('draft');
                showAlert('error', 'Error sending final prescription: ' + error.message);
            });
        }
        
        function viewPrescriptionDetails(patientId, date) {
            fetch(`/sheduling/prescription/api/prescription-details/?patient_id=${patientId}&date=${date}`)
                .then(response => response.json())
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
                <p><strong>Doctor:</strong> ${escapeHtml(patientInfo.doctor_name || 'N/A')}</p>
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
                        
                        const line1 = document.createElement('div');
                        line1.style.fontWeight = '600';
                        line1.style.marginBottom = '2px';
                        const prefix = groupIndex === 0 ? '• ' : '+ ';
                        line1.innerHTML = `${prefix}<span style="display:inline-block;padding:2px 8px;border-radius:999px;background:#e3f2fd;color:#0d47a1;">${itemNames || 'No medicines'}</span>`;
                        
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
                .then(response => response.json())
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
        
        function showChangeLogModal(changeLog) {
            const modal = document.getElementById('changeLogModal');
            const content = document.getElementById('change-log-content');
            
            if (changeLog.length === 0) {
                content.innerHTML = '<p>No changes recorded for this prescription.</p>';
            } else {
                content.innerHTML = changeLog.map(entry => `
                    <div style="border: 1px solid var(--border); border-radius: 8px; padding: 15px; margin-bottom: 10px;">
                        <h4>${escapeHtml(entry.action)}</h4>
                        <p><strong>Patient:</strong> ${escapeHtml(entry.patient_name)}</p>
                        <p><strong>Date:</strong> ${formatDate(entry.date)}</p>
                        <p><strong>Changed By:</strong> ${escapeHtml(entry.changed_by)}</p>
                        <p><strong>Time:</strong> ${escapeHtml(entry.timestamp)}</p>
                        ${entry.before_values ? `<p><strong>Before:</strong> ${escapeHtml(entry.before_values)}</p>` : ''}
                        ${entry.after_values ? `<p><strong>After:</strong> ${escapeHtml(entry.after_values)}</p>` : ''}
                    </div>
                `).join('');
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
        
        // Format date as DD/MM/YYYY
        function formatDate(dateStr) {
            if (!dateStr) return '';
            try {
                // Handle both YYYY-MM-DD format and Date objects
                let date;
                if (typeof dateStr === 'string') {
                    date = new Date(dateStr + 'T00:00:00');
                } else if (dateStr instanceof Date) {
                    date = dateStr;
                } else {
                    return dateStr;
                }
                if (isNaN(date.getTime())) return dateStr; // Return original if invalid
                const day = String(date.getDate()).padStart(2, '0');
                const month = String(date.getMonth() + 1).padStart(2, '0');
                const year = date.getFullYear();
                return `${day}/${month}/${year}`;
            } catch (e) {
                return dateStr; // Return original if error
            }
        }
        
        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }
        
        // Print Prescription Schedule to PDF
        function printPrescriptionScheduleToPDF() {
            const selectedDate = document.getElementById('scheduled-date').value;
            
            if (!selectedDate) {
                alert('Please select a date first using the date filter');
                return;
            }
            
            // Show loading
            const printBtn = document.getElementById('print-prescription-pdf');
            const originalText = printBtn.innerHTML;
            printBtn.disabled = true;
            printBtn.innerHTML = '<span>⏳</span> Generating PDF...';
            
            // Fetch prescription data
            fetch(`/sheduling/prescription/api/prescription-data/?status=scheduled&date=${selectedDate}`)
                .then(response => response.json())
                .then(data => {
                    // Also fetch therapy data to get patients with zero-therapist therapies
                    // Use include_zero_therapist=true to get zero-therapist therapies for prescription PDF
                    fetch(`/sheduling/scheduling/api/therapy-data/?status=allocated&date=${selectedDate}&include_zero_therapist=true`)
                        .then(res => res.json())
                        .then(therapyData => {
                            // Get all patients from prescriptions
                            const prescriptionPatients = new Set();
                            if (data.success && data.data.length > 0) {
                                data.data.forEach(item => {
                                    prescriptionPatients.add(item.registration_no);
                                });
                            }
                            
                            // Get patients with zero-therapist therapies who don't have prescriptions
                            // With include_zero_therapist=true, zero-therapist therapies are included in therapyData
                            const zeroTherapistPatients = new Set();
                            if (therapyData.success && therapyData.data) {
                                therapyData.data.forEach(therapy => {
                                    const therapistsCount = therapy.therapists ? therapy.therapists.length : 0;
                                    const isNurse = therapy.is_nurse_treatment === true;
                                    const isZeroTherapist = !isNurse && therapistsCount === 0;
                                    
                                    if (isZeroTherapist && !prescriptionPatients.has(therapy.patient_reg_no)) {
                                        zeroTherapistPatients.add(therapy.patient_reg_no);
                                    }
                                });
                            }
                            
                            // Add placeholder entries for patients with only zero-therapist therapies
                            // We'll fetch their details to get age, sex, and doctor info
                            const additionalPatientsPromises = Array.from(zeroTherapistPatients).map(regNo => {
                                // Find the therapy data for this patient to get patient info
                                // Look in therapyData which now includes zero-therapist therapies
                                const therapyForPatient = therapyData.data.find(t => t.patient_reg_no === regNo);
                                const patientId = therapyForPatient ? therapyForPatient.id : null;
                                
                                // Try to fetch patient details to get age, sex, and doctor
                                if (patientId) {
                                    return fetch(`/sheduling/prescription/api/prescription-details/?patient_id=${patientId}&date=${selectedDate}`)
                                        .then(res => res.json())
                                        .then(detailData => {
                                            if (detailData.success && detailData.patient_info) {
                                                return {
                                                    patient_id: patientId,
                                                    scheduling_id: null,
                                                    patient_name: detailData.patient_info.name || therapyForPatient.patient_name || 'Unknown',
                                                    registration_no: regNo,
                                                    room_no: detailData.patient_info.room_no || therapyForPatient.patient_room_no || null,
                                                    doctor_name: detailData.patient_info.doctor_name || 'N/A',
                                                    prescription_count: 0,
                                                    status: 'scheduled',
                                                    details: {
                                                        success: true,
                                                        patient_info: detailData.patient_info,
                                                        prescription_groups: [],
                                                        therapy_items: []
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
                                                    doctor_name: 'N/A',
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
                                                            doctor_name: 'N/A'
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
                                                doctor_name: 'N/A',
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
                                                        doctor_name: 'N/A'
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
                                        doctor_name: 'N/A',
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
                                                doctor_name: 'N/A'
                                            },
                                            prescription_groups: [],
                                            therapy_items: []
                                        }
                                    });
                                }
                            });
                            
                            // Wait for all patient details to be fetched, then continue
                            Promise.all(additionalPatientsPromises).then(additionalPatients => {
                                // Combine prescription patients with zero-therapist-only patients
                                const allPatients = (data.success && data.data.length > 0 ? data.data : []).concat(additionalPatients);
                                
                                if (allPatients.length > 0) {
                                // Fetch details for each patient (only for prescription patients)
                                const patientPromises = allPatients.map(item => {
                                    if (item.details) {
                                        // Already has details (zero-therapist-only patient)
                                        return Promise.resolve(item);
                                    } else {
                                        // Fetch prescription details
                                        return fetch(`/sheduling/prescription/api/prescription-details/?patient_id=${item.patient_id}&date=${selectedDate}`)
                                            .then(res => res.json())
                                            .then(detailData => ({
                                                ...item,
                                                details: detailData.success ? detailData : null
                                            }));
                                    }
                                });
                                
                                Promise.all(patientPromises)
                                    .then(patientsWithDetails => {
                                        // Map therapies by patient registration number
                                        // Separate regular therapies and zero-therapist therapies
                                        const therapiesByPatient = {};
                                        const zeroTherapistTherapiesByPatient = {};
                                        if (therapyData.success && therapyData.data) {
                                            console.log('[PDF Debug] Total therapies from API:', therapyData.data.length);
                                            therapyData.data.forEach(therapy => {
                                                const regNo = therapy.patient_reg_no;
                                                // Check if this is a zero-therapist therapy (not nurse treatment)
                                                // Zero-therapist therapies have empty therapists array
                                                // is_nurse_treatment will be false (boolean) for non-nurse treatments, true for nurse treatments
                                                const therapistsCount = therapy.therapists ? therapy.therapists.length : 0;
                                                const isNurse = therapy.is_nurse_treatment === true;
                                                const isZeroTherapist = !isNurse && therapistsCount === 0;
                                                
                                                if (isZeroTherapist) {
                                                    console.log('[PDF Debug] Found zero-therapist therapy:', therapy.therapy_name, 'for patient:', regNo);
                                                    // Store zero-therapist therapies separately
                                                    if (!zeroTherapistTherapiesByPatient[regNo]) {
                                                        zeroTherapistTherapiesByPatient[regNo] = [];
                                                    }
                                                    zeroTherapistTherapiesByPatient[regNo].push(therapy);
                                                } else {
                                                    // Regular therapies with therapists
                                                    if (!therapiesByPatient[regNo]) {
                                                        therapiesByPatient[regNo] = [];
                                                    }
                                                    therapiesByPatient[regNo].push(therapy);
                                                }
                                            });
                                            console.log('[PDF Debug] Zero-therapist therapies by patient:', Object.keys(zeroTherapistTherapiesByPatient));
                                        }
                                        
                                        // Add therapy items and zero-therapist therapies to each patient
                                        const patientsWithAllData = patientsWithDetails.map(item => {
                                            const regNo = item.registration_no;
                                            const zeroTherapies = zeroTherapistTherapiesByPatient[regNo] || [];
                                            if (zeroTherapies.length > 0) {
                                                console.log('[PDF Debug] Patient', regNo, 'has', zeroTherapies.length, 'zero-therapist therapies:', zeroTherapies.map(t => t.therapy_name));
                                            }
                                            return {
                                                ...item,
                                                therapy_items: therapiesByPatient[regNo] || [],
                                                zero_therapist_therapies: zeroTherapies
                                            };
                                        });
                                        
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
            const { jsPDF } = window.jspdf;
            const doc = new jsPDF('p', 'mm', 'a4');
            
            const pageWidth = doc.internal.pageSize.getWidth();
            const pageHeight = doc.internal.pageSize.getHeight();
            const margin = 15;
            let yPos = margin;
            let currentPage = 1;
            let totalPages = 1;
            
            // Remove duplicates and merge patients by registration number
            // This ensures patients with both prescriptions and zero-therapist therapies appear only once
            const uniqueDataMap = new Map();
            prescriptionData.forEach(item => {
                const regNo = item.registration_no || item.details?.patient_info?.registration_no || '';
                if (regNo) {
                    if (uniqueDataMap.has(regNo)) {
                        // Merge with existing patient entry
                        const existing = uniqueDataMap.get(regNo);
                        // Merge prescription groups
                        const existingGroups = existing.details?.prescription_groups || [];
                        const newGroups = item.details?.prescription_groups || [];
                        // Merge therapy items
                        const existingTherapyItems = existing.details?.therapy_items || [];
                        const newTherapyItems = item.details?.therapy_items || [];
                        // Merge zero-therapist therapies
                        const existingZero = existing.zero_therapist_therapies || [];
                        const newZero = item.zero_therapist_therapies || [];
                        
                        uniqueDataMap.set(regNo, {
                            ...existing,
                            details: {
                                ...existing.details,
                                prescription_groups: [...existingGroups, ...newGroups],
                                therapy_items: [...existingTherapyItems, ...newTherapyItems]
                            },
                            zero_therapist_therapies: [...existingZero, ...newZero]
                        });
                    } else {
                        uniqueDataMap.set(regNo, item);
                    }
                } else {
                    // Fallback to patient_id if registration_no not available
                    const patientId = item.patient_id;
                    if (patientId && !uniqueDataMap.has(`id_${patientId}`)) {
                        uniqueDataMap.set(`id_${patientId}`, item);
                    }
                }
            });
            
            // Convert map to array
            const uniqueData = Array.from(uniqueDataMap.values());
            
            // Sort by patient name
            uniqueData.sort((a, b) => {
                const nameA = a.patient_name || a.details?.patient_info?.name || '';
                const nameB = b.patient_name || b.details?.patient_info?.name || '';
                return nameA.localeCompare(nameB);
            });
            
            // Header function - add heading only on first page
            function addHeader(isFirstPage) {
                if (isFirstPage) {
                    // Add heading "Prescription Scheduling of [date]" at top of first page
                    const formattedDate = formatDate(date);
                    doc.setFontSize(14);
                    doc.setFont(undefined, 'bold');
                    doc.setTextColor(0, 0, 0);
                    const headingText = `Prescription Scheduling of ${formattedDate}`;
                    doc.text(headingText, pageWidth / 2, margin + 8, { align: 'center' });
                    
                    // Add a line below the heading
                    doc.setDrawColor(0, 0, 0);
                    doc.setLineWidth(0.5);
                    doc.line(margin, margin + 12, pageWidth - margin, margin + 12);
                    
                    yPos = margin + 18; // Start content below heading
                } else {
                    // Just reset a small top margin for subsequent pages
                    yPos = margin;
                }
            }
            
            // Footer function
            function addFooter(pageNum) {
                const footerY = pageHeight - 10;
                
                // Subtle footer line
                doc.setDrawColor(230, 230, 230);
                doc.setLineWidth(0.3);
                doc.line(margin, footerY - 5, pageWidth - margin, footerY - 5);
                
                doc.setFontSize(8);
                doc.setFont(undefined, 'normal');
                doc.setTextColor(108, 117, 125);
                doc.text(`Page ${pageNum}`, pageWidth / 2, footerY, { align: 'center' });
            }
            
            // Check if we need a new page
            function checkNewPage(requiredHeight) {
                if (yPos + requiredHeight > pageHeight - 20) {
                    addFooter(currentPage);
                    doc.addPage();
                    currentPage++;
                    addHeader(false); // Not first page
                }
            }
            
            // Add initial header with heading on first page only
            addHeader(true);
            
            // Process each patient
            uniqueData.forEach((item, index) => {
                // Get patient info from details, with fallbacks to item data
                const patientInfo = {
                    name: item.details?.patient_info?.name || item.patient_name || 'Unknown',
                    registration_no: item.details?.patient_info?.registration_no || item.registration_no || 'N/A',
                    room_no: item.details?.patient_info?.room_no || item.room_no || 'N/A',
                    age: item.details?.patient_info?.age || '',
                    sex: item.details?.patient_info?.sex || '',
                    doctor_name: item.details?.patient_info?.doctor_name || item.doctor_name || 'N/A'
                };
                
                const prescriptionGroups = item.details?.prescription_groups || [];
                const therapyItems = item.details?.therapy_items || [];
                const zeroTherapistTherapies = item.zero_therapist_therapies || [];
                
                // Determine if this patient has any content to display
                const hasPrescriptions = prescriptionGroups.length > 0 || therapyItems.length > 0;
                const hasZeroTherapist = zeroTherapistTherapies.length > 0;
                const hasAnyContent = hasPrescriptions || hasZeroTherapist;
                
                // Calculate estimated height based on groups (compact so multiple patients fit per page)
                let estimatedHeight = 18;
                prescriptionGroups.forEach(group => {
                    estimatedHeight += 6 + (group.items?.length || 0) * 3;
                });
                therapyItems.forEach(item => {
                    estimatedHeight += 6 + (item.items?.length || 0) * 3;
                });
                zeroTherapistTherapies.forEach(() => {
                    estimatedHeight += 5; // Height per zero-therapist therapy row
                });
                checkNewPage(estimatedHeight);
                
                // Patient Information Section - show once at the top if patient has any content
                // This ensures patient details appear only once, regardless of whether they have prescriptions, zero-therapist therapies, or both
                if (hasAnyContent) {
                    doc.setFontSize(9);
                    doc.setFont(undefined, 'bold');
                    doc.setTextColor(0, 0, 0);
                    const roomText = `Room: ${patientInfo.room_no || 'N/A'}`;
                    const nameText = `Name: ${patientInfo.name || 'Unknown'}`;
                    const genderAgeText = `Gender: ${patientInfo.sex || 'N/A'}   Age: ${patientInfo.age || 'N/A'}`;
                    const doctorText = `Doctor: ${patientInfo.doctor_name || 'N/A'}`;
                    // First line: Room and Name
                    doc.text(roomText, margin, yPos);
                    doc.text(nameText, margin + 60, yPos);
                    yPos += 5;
                    // Second line: Gender/Age and Doctor
                    doc.text(genderAgeText, margin, yPos);
                    doc.text(doctorText, margin + 60, yPos);
                    yPos += 6;
                }
                
                // Prescription Items and Zero-Therapist Therapies - combined in same table structure
                if (prescriptionGroups.length > 0 || zeroTherapistTherapies.length > 0) {
                    checkNewPage(6);
                    
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
                    
                    // Calculate approximate box height needed (include zero-therapist therapies)
                    let estimatedHeight = 10; // Base height for header and column headers
                    Object.values(groupsByAllocation).forEach(allocationGroups => {
                        allocationGroups.forEach(group => {
                            if (group.items && group.items.length > 0) {
                                estimatedHeight += 5; // Height per row
                            }
                        });
                    });
                    zeroTherapistTherapies.forEach(() => {
                        estimatedHeight += 5; // Height per zero-therapist therapy row
                    });
                    checkNewPage(estimatedHeight);
                    
                    // Prescription entry - simple list format (no table borders)
                    const boxX = margin;
                    const boxStartY = yPos;
                    
                    // Column headers (no background box, just text) - only show once if there are any items
                    if (prescriptionGroups.length > 0 || zeroTherapistTherapies.length > 0) {
                        doc.setFontSize(7);
                        doc.setFont(undefined, 'bold');
                        doc.setTextColor(0, 0, 0);
                        // Column order: Usage, Items, Dosage, Oil Class, Ingredients
                        doc.text('Usage', boxX + 2, yPos + 2.5);
                        doc.text('Items', boxX + 30, yPos + 2.5);
                        doc.text('Dosage', boxX + 68, yPos + 2.5);
                        doc.text('Oil Class', boxX + 100, yPos + 2.5);
                        doc.text('Ingredients', boxX + 135, yPos + 2.5);
                        
                        yPos += 5;
                    }
                    
                    // Render prescription groups
                    const allocationIds = Object.keys(groupsByAllocation);
                    allocationIds.forEach((allocationId, entryIndex) => {
                        const allocationGroups = groupsByAllocation[allocationId];
                        
                        // Determine common usage for this allocation
                        let commonUsage = '';
                        if (allocationGroups.length > 0) {
                            const g0 = allocationGroups[0];
                            if (g0.usage) {
                                commonUsage = g0.usage;
                            } else if (g0.usage_array && Array.isArray(g0.usage_array) && g0.usage_array.length > 0) {
                                commonUsage = g0.usage_array.join(', ');
                            }
                        }
                        
                        // Render each group as a row
                        allocationGroups.forEach((group, groupIndex) => {
                            const items = group.items || [];
                            if (!items.length) return;

                            const itemNames = items.map(it => it.item_name || 'N/A').join(', ');

                            // Dosage + UNO
                            const dose = group.dose || '';
                            const unoNote = group.notes || '';
                            let doseDisplay = '';
                            if (dose && unoNote) {
                                doseDisplay = `${dose} (${unoNote})`;
                            } else if (dose) {
                                doseDisplay = dose;
                            } else if (unoNote) {
                                doseDisplay = unoNote;
                            }

                            const oilClass = group.oil_class || '';

                            // Ingredients
                            const ingredientsDisplay = (group.ingredients && group.ingredients.length > 0)
                                ? group.ingredients.map(ing => ing.ingredient_name || ing.text || 'N/A').join(', ')
                                : '';

                            const rowStartY = yPos;
                            
                            // Get usage for this entry (only show in first row)
                            const rowUsage = (groupIndex === 0) ? (group.usage || commonUsage || '') : '';
                            
                            // Render row data
                            doc.setFontSize(7);
                            
                            // Usage (first column, only show in first row of entry, common for full entry)
                            doc.setFont(undefined, 'normal');
                            doc.setTextColor(0, 0, 0);
                            const usageLines = (groupIndex === 0 && rowUsage) ? doc.splitTextToSize(rowUsage, 25) : [];
                            if (usageLines.length > 0) {
                                doc.text(usageLines, boxX + 2, yPos + 2);
                            }
                            // For subsequent rows, usage column is left empty
                            
                            // Items (second column, in blue, bold) - add "+" prefix for groups after the first
                            doc.setFont(undefined, 'bold');
                            doc.setTextColor(0, 86, 179);
                            const prefix = groupIndex > 0 ? '+ ' : '';
                            const itemsText = prefix + (itemNames || '—');
                            const itemsLines = doc.splitTextToSize(itemsText, 35);
                            doc.text(itemsLines, boxX + 30, yPos + 2);
                            
                            // Dosage (third column)
                            doc.setFont(undefined, 'normal');
                            doc.setTextColor(0, 0, 0);
                            const doseLines = doc.splitTextToSize(doseDisplay || '—', 30);
                            doc.text(doseLines, boxX + 68, yPos + 2);
                            
                            // Oil Class (fourth column)
                            doc.text(oilClass || '—', boxX + 100, yPos + 2);
                            
                            // Ingredients (fifth column)
                            const ingredientsLines = doc.splitTextToSize(ingredientsDisplay || '—', 30);
                            doc.text(ingredientsLines, boxX + 135, yPos + 2);
                            
                            // Calculate row height based on tallest cell (include usage only for first row)
                            const rowHeight = Math.max(
                                itemsLines.length * 2.5,
                                (groupIndex === 0 ? usageLines.length * 2.5 : 0),
                                doseLines.length * 2.5,
                                ingredientsLines.length * 2.5,
                                3.5
                            );
                            yPos += rowHeight;
                            
                            // No row separator lines - clean list format
                        });
                    });
                    
                    // Render zero-therapist therapies as rows in the same table structure
                    zeroTherapistTherapies.forEach((therapy, index) => {
                        checkNewPage(5);
                        
                        const therapyName = therapy.therapy_name || 'Unknown Therapy';
                        const therapyTime = therapy.timeslot || 'N/A';
                        
                        // Render row data
                        doc.setFontSize(7);
                        
                        // Usage column: Time
                        doc.setFont(undefined, 'normal');
                        doc.setTextColor(0, 0, 0);
                        doc.text(therapyTime, boxX + 2, yPos + 2);
                        
                        // Items column: Therapy name (in blue, bold)
                        doc.setFont(undefined, 'bold');
                        doc.setTextColor(0, 86, 179);
                        const itemsLines = doc.splitTextToSize(therapyName, 35);
                        doc.text(itemsLines, boxX + 30, yPos + 2);
                        
                        // Dosage column: empty
                        doc.setFont(undefined, 'normal');
                        doc.setTextColor(0, 0, 0);
                        doc.text('—', boxX + 68, yPos + 2);
                        
                        // Oil Class column: empty
                        doc.text('—', boxX + 100, yPos + 2);
                        
                        // Ingredients column: empty
                        doc.text('—', boxX + 135, yPos + 2);
                        
                        // Calculate row height
                        const rowHeight = Math.max(itemsLines.length * 2.5, 3.5);
                        yPos += rowHeight;
                    });
                    
                    yPos += 3; // Space after prescription/zero-therapist section
                }
                // Removed "No prescription items found" message - just skip if no items
                
                // Therapy Items - Grouped Format with colored header bar
                if (therapyItems.length > 0) {
                    checkNewPage(15);
                    doc.setFillColor(16, 185, 129); // Green like therapy scheduling
                    doc.rect(margin, yPos - 3, pageWidth - margin * 2, 8, 'F');
                    
                    doc.setFontSize(12);
                    doc.setFont(undefined, 'bold');
                    doc.setTextColor(255, 255, 255);
                    doc.text('Therapy Items', margin + 5, yPos + 2);
                    yPos += 10;
                    doc.setTextColor(0, 0, 0);
                    
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
                        
                        checkNewPage(15);
                        
                        // Therapy name - Colored bar like therapy scheduling
                        doc.setFillColor(52, 211, 153); // Lighter green
                        doc.rect(margin, yPos - 2, pageWidth - margin * 2, 6, 'F');
                        
                        doc.setFontSize(10);
                        doc.setFont(undefined, 'bold');
                        doc.setTextColor(255, 255, 255);
                        doc.text(therapyName, margin + 5, yPos + 2);
                        
                        yPos += 8;
                        doc.setTextColor(0, 0, 0);
                        
                        // Render each dosage group within this therapy
                        therapyGroupsList.forEach(group => {
                            const items = group.items || [];
                            if (items.length === 0) return;
                            
                            checkNewPage(20);
                            
                            // Dosage if available - combine with UNO if both exist
                            if (group.dosage || group.uno) {
                                doc.setFontSize(9);
                                doc.setFont(undefined, 'bold');
                                doc.setTextColor(0, 0, 0);
                                const dosageText = group.dosage || '';
                                const unoText = group.uno || '';
                                const dosageDisplay = (dosageText && unoText) 
                                    ? `${dosageText} (${unoText})`
                                    : (dosageText || (unoText ? `(${unoText})` : ''));
                                if (dosageDisplay) {
                                    doc.text(`Dosage: ${dosageDisplay}`, margin + 5, yPos);
                                    yPos += 5;
                                }
                            }
                            
                            // Display multiple items as comma-separated list
                            doc.setFontSize(9);
                            doc.setFont(undefined, 'bold');
                            doc.setTextColor(0, 0, 0);
                            const itemNames = items.map(it => {
                                const name = it.item_name || 'N/A';
                                const isRemoved = it.is_removed || it.status === 'removed';
                                return isRemoved ? `${name} [REMOVED]` : name;
                            }).join(', ');
                            const itemNamesLines = doc.splitTextToSize(itemNames, pageWidth - margin * 2 - 10);
                            doc.text(itemNamesLines, margin + 5, yPos);
                            yPos += itemNamesLines.length * 4 + 4;
                            
                            // Display shared details: usage, UNO, Ext/Int
                            doc.setFontSize(8);
                            doc.setFont(undefined, 'normal');
                            doc.setTextColor(73, 80, 87);
                            
                            const details = [];
                            // Handle usage
                            let usage = 'N/A';
                            if (group.usage) {
                                usage = group.usage;
                            } else if (group.usage_array && Array.isArray(group.usage_array) && group.usage_array.length > 0) {
                                usage = group.usage_array.join(', ');
                            }
                            if (usage !== 'N/A') {
                                details.push(`Usage: ${usage}`);
                            }
                            // UNO is now combined with dosage above, so we don't need a separate UNO entry
                            if (group.internal_external && group.internal_external !== 'N/A') {
                                details.push(`Ext/Int: ${group.internal_external}`);
                            }
                            
                            if (details.length > 0) {
                                const detailsText = details.join('  •  ');
                                const detailsLines = doc.splitTextToSize(detailsText, pageWidth - margin * 2 - 10);
                                doc.text(detailsLines, margin + 5, yPos);
                                yPos += detailsLines.length * 4 + 3;
                            }
                            
                            yPos += 4; // Space between groups
                            doc.setTextColor(0, 0, 0);
                        });
                        
                        yPos += 3; // Space between therapies
                    });
                    
                    yPos += 5; // Space after therapy section
                }
                
                // Zero-therapist therapies are now integrated into the prescription table above
                // No separate section needed
                
                // Add spacing between patients with separator line
                yPos += 8;
                doc.setDrawColor(200, 200, 200);
                doc.setLineWidth(0.5);
                doc.line(margin, yPos, pageWidth - margin, yPos);
                yPos += 12;
            });
            
            // Add final footer
            addFooter(currentPage);
            
            // Save PDF
            const fileName = `Prescription_Schedule_${date.replace(/-/g, '_')}.pdf`;
            doc.save(fileName);
        }