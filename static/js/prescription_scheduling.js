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
                .then(response => response.json())
                .then(data => {
                    console.log('[PDF] Prescription data received:', data.success, 'patients:', data.data?.length || 0);
                    // Also fetch therapy data to get ALL scheduled therapies (with therapists, nurse treatments, and zero-therapist)
                    // Fetch both 'allocated' and 'scheduled' status to get all scheduled therapies
                    // Use include_zero_therapist=true to get zero-therapist therapies for prescription PDF
                    console.log('[PDF] Fetching therapy data...');
                    Promise.all([
                        fetch(`/sheduling/scheduling/api/therapy-data/?status=allocated&date=${selectedDate}&include_zero_therapist=true`).then(r => r.json()),
                        fetch(`/sheduling/scheduling/api/therapy-data/?status=scheduled&date=${selectedDate}&include_zero_therapist=true`).then(r => r.json())
                    ]).then(([allocatedData, scheduledData]) => {
                        // Combine both responses
                        const therapyData = {
                            success: allocatedData.success || scheduledData.success,
                            data: [...(allocatedData.data || []), ...(scheduledData.data || [])]
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
                                    
                                    // Create a map of therapy times by therapy name and patient for lookup
                                    const therapyTimeMap = {};
                                    if (therapyData.success && therapyData.data) {
                                        therapyData.data.forEach(therapy => {
                                            const regNo = therapy.patient_reg_no;
                                            const therapyName = therapy.therapy_name;
                                            const timeslot = therapy.timeslot || '';
                                            if (regNo && therapyName && timeslot) {
                                                const key = `${regNo}_${therapyName}`;
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
                                                booking_id: therapy.booking_id,
                                                booking_status: therapy.status || therapy.booking_status || 'scheduled',
                                                booking_is_cancelled: false,
                                                timeslot: timeslot,
                                                time: timeslot,
                                                items: itemsArray,
                                                is_group: true
                                            };
                                        };
                                        
                                    // Add therapy items and zero-therapist therapies to each patient
                                    const patientsWithAllData = patientsWithDetails.map(item => {
                                        const regNo = item.registration_no;
                                        const zeroTherapies = zeroTherapistTherapiesByPatient[regNo] || [];
                                        const therapiesFromAPI = therapiesByPatient[regNo] || [];
                                        
                                        if (zeroTherapies.length > 0) {
                                            console.log('[PDF Debug] Patient', regNo, 'has', zeroTherapies.length, 'zero-therapist therapies:', zeroTherapies.map(t => t.therapy_name));
                                        }
                                        if (therapiesFromAPI.length > 0) {
                                            console.log('[PDF Debug] Patient', regNo, 'has', therapiesFromAPI.length, 'therapies from API:', therapiesFromAPI.map(t => t.therapy_name));
                                        }
                                        
                                        // Get therapy items from prescription details API
                                        const therapyItemsFromDetails = item.details?.therapy_items || [];
                                        
                                        // Convert therapies from therapy API to therapy items format
                                        const therapyItemsFromAPI = therapiesFromAPI.map(convertTherapyToTherapyItem);
                                        
                                        // Combine both sources and enhance with timeslot information
                                        const allTherapyItems = [...therapyItemsFromDetails, ...therapyItemsFromAPI];
                                        
                                        // Remove duplicates based on therapy_name and booking_id
                                        const uniqueTherapyItems = [];
                                        const seenTherapies = new Set();
                                        allTherapyItems.forEach(therapyItem => {
                                            const therapyName = therapyItem.therapy_name || '';
                                            const bookingId = therapyItem.booking_id || '';
                                            const key = `${therapyName}_${bookingId}`;
                                            
                                            if (!seenTherapies.has(key)) {
                                                seenTherapies.add(key);
                                                // Enhance with timeslot information
                                                const lookupKey = `${regNo}_${therapyName}`;
                                                const timeslot = therapyTimeMap[lookupKey] || therapyItem.timeslot || therapyItem.time || '';
                                                uniqueTherapyItems.push({
                                                    ...therapyItem,
                                                    timeslot: timeslot
                                                });
                                            }
                                        });
                                        
                                        return {
                                            ...item,
                                            therapy_items: uniqueTherapyItems,
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
            console.log('[PDF] generatePrescriptionPDF called with', prescriptionData?.length || 0, 'patients');
            
            if (!prescriptionData || prescriptionData.length === 0) {
                alert('No prescription data available to generate PDF.');
                console.error('[PDF] No prescription data provided');
                return;
            }
            
            try {
                const { jsPDF } = window.jspdf;
                const doc = new jsPDF('p', 'mm', 'a4');
                console.log('[PDF] jsPDF instance created');
                
                const pageWidth = doc.internal.pageSize.getWidth();
                const pageHeight = doc.internal.pageSize.getHeight();
                const margin = 15;
                let yPos = margin;
                let currentPage = 1;
                let totalPages = 1;
                
                // Remove duplicates and merge patients by registration number
                // This ensures patients with both prescriptions and zero-therapist therapies appear only once
                const uniqueDataMap = new Map();
                console.log('[PDF] Total patients before deduplication:', prescriptionData.length);
                prescriptionData.forEach((item, index) => {
                    // Normalize registration number (trim whitespace, convert to string)
                    const regNoRaw = item.registration_no || item.details?.patient_info?.registration_no || '';
                    const regNo = String(regNoRaw).trim();
                    const patientName = item.patient_name || item.details?.patient_info?.name || 'Unknown';
                    console.log(`[PDF] Processing patient ${index + 1}: regNo="${regNo}", name="${patientName}"`);
                    
                    if (regNo) {
                    if (uniqueDataMap.has(regNo)) {
                        // Merge with existing patient entry
                        console.log(`[PDF] Merging duplicate patient: ${regNo}`);
                        const existing = uniqueDataMap.get(regNo);
                        // Merge prescription groups
                        const existingGroups = existing.details?.prescription_groups || [];
                        const newGroups = item.details?.prescription_groups || [];
                        // Merge therapy items from details
                        const existingTherapyItems = existing.details?.therapy_items || [];
                        const newTherapyItems = item.details?.therapy_items || [];
                        // Merge therapy items from API (item.therapy_items)
                        const existingTherapyItemsAPI = existing.therapy_items || [];
                        const newTherapyItemsAPI = item.therapy_items || [];
                        // Merge zero-therapist therapies
                        const existingZero = existing.zero_therapist_therapies || [];
                        const newZero = item.zero_therapist_therapies || [];
                        
                        // Merge patient info - prefer non-empty values from new item
                        const existingPatientInfo = existing.details?.patient_info || {};
                        const newPatientInfo = item.details?.patient_info || {};
                        const mergedPatientInfo = {
                            name: newPatientInfo.name || existingPatientInfo.name || existing.patient_name || item.patient_name || 'Unknown',
                            registration_no: newPatientInfo.registration_no || existingPatientInfo.registration_no || regNo,
                            room_no: newPatientInfo.room_no || existingPatientInfo.room_no || existing.room_no || item.room_no || 'N/A',
                            age: newPatientInfo.age || existingPatientInfo.age || '',
                            sex: newPatientInfo.sex || existingPatientInfo.sex || '',
                            doctor_name: newPatientInfo.doctor_name || existingPatientInfo.doctor_name || existing.doctor_name || item.doctor_name || 'N/A'
                        };
                        
                        uniqueDataMap.set(regNo, {
                            ...existing,
                            patient_name: mergedPatientInfo.name,
                            registration_no: mergedPatientInfo.registration_no,
                            room_no: mergedPatientInfo.room_no,
                            doctor_name: mergedPatientInfo.doctor_name,
                            details: {
                                ...existing.details,
                                patient_info: mergedPatientInfo,
                                prescription_groups: [...existingGroups, ...newGroups],
                                therapy_items: [...existingTherapyItems, ...newTherapyItems]
                            },
                            therapy_items: [...existingTherapyItemsAPI, ...newTherapyItemsAPI],
                            zero_therapist_therapies: [...existingZero, ...newZero]
                        });
                    } else {
                        console.log(`[PDF] Adding new patient: ${regNo}`);
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
                console.log('[PDF] Total patients after deduplication:', uniqueData.length);
                uniqueData.forEach((patient, idx) => {
                    const regNo = patient.registration_no || patient.details?.patient_info?.registration_no || '';
                    const name = patient.patient_name || patient.details?.patient_info?.name || 'Unknown';
                    console.log(`[PDF] Final patient ${idx + 1}: regNo="${regNo}", name="${name}", prescriptions=${patient.details?.prescription_groups?.length || 0}, therapies=${patient.therapy_items?.length || 0}, zeroTherapist=${patient.zero_therapist_therapies?.length || 0}`);
                });
                
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
                
                // Track which patients we've already shown to prevent duplicates
                const shownPatients = new Set();
                
                // Process each patient
                uniqueData.forEach((item, index) => {
                    // Get patient info from details, with fallbacks to item data
                    const regNo = item.registration_no || item.details?.patient_info?.registration_no || '';
                    const patientInfo = {
                        name: item.details?.patient_info?.name || item.patient_name || 'Unknown',
                        registration_no: regNo || 'N/A',
                        room_no: item.details?.patient_info?.room_no || item.room_no || 'N/A',
                        age: item.details?.patient_info?.age || '',
                        sex: item.details?.patient_info?.sex || '',
                        doctor_name: item.details?.patient_info?.doctor_name || item.doctor_name || 'N/A'
                    };
                    
                    // Skip if we've already shown this patient (by registration number)
                    if (regNo && shownPatients.has(regNo)) {
                        console.log(`[PDF] Skipping duplicate patient: ${regNo}`);
                        return; // Skip this iteration
                    }
                    if (regNo) {
                        shownPatients.add(regNo);
                    }
                    
                    const prescriptionGroups = item.details?.prescription_groups || [];
                    // Get therapy items from both details API and converted from therapy API
                    const therapyItemsFromDetails = item.details?.therapy_items || [];
                    const therapyItemsFromAPI = item.therapy_items || [];
                    // Combine both sources (therapies from API are already converted to therapy items format)
                    const therapyItems = [...therapyItemsFromDetails, ...therapyItemsFromAPI];
                    const zeroTherapistTherapies = item.zero_therapist_therapies || [];
                    
                    console.log('[PDF Debug] Patient:', item.patient_name, 'therapyItemsFromDetails:', therapyItemsFromDetails.length, 'therapyItemsFromAPI:', therapyItemsFromAPI.length, 'total therapyItems:', therapyItems.length, 'zeroTherapist:', zeroTherapistTherapies.length);
                    
                    // Determine if this patient has any content to display
                    const hasPrescriptions = prescriptionGroups.length > 0;
                    const hasTherapyItems = therapyItems.length > 0;
                    const hasZeroTherapist = zeroTherapistTherapies.length > 0;
                    const hasAnyContent = hasPrescriptions || hasTherapyItems || hasZeroTherapist;
                    
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
                
                // Prescription Items, Therapy Treatments, and Zero-Therapist Therapies - combined in same table structure
                if (prescriptionGroups.length > 0 || therapyItems.length > 0 || zeroTherapistTherapies.length > 0) {
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
                    
                    // Process therapy items - group by therapy name and extract time/date
                    const therapyRows = [];
                    if (therapyItems && therapyItems.length > 0) {
                        therapyItems.forEach(item => {
                            // Therapy items can be in different formats
                            // Format 1: is_group with items array
                            // Format 2: Direct therapy item with items array
                            const therapyName = item.therapy_name || 'Unknown Therapy';
                            const therapyTime = item.timeslot || item.time || '';
                            
                            // Check if item has items array (grouped format)
                            if (item.items && Array.isArray(item.items) && item.items.length > 0) {
                                // Process each group within the therapy
                                item.items.forEach(group => {
                                    const items = group.items || [];
                                    // Handle both cases: items with content and empty items (use therapy name)
                                    if (items.length > 0) {
                                        const itemNames = items.map(it => it.item_name || 'N/A').join(', ');
                                        
                                        // Get dosage, usage, etc. from group or item
                                        const dosage = group.dosage || item.dosage || group.dose || '';
                                        const uno = group.uno || item.uno || group.notes || '';
                                        const dosageDisplay = (dosage && uno) ? `${dosage} (${uno})` : (dosage || uno || '');
                                        
                                        // Usage can be from group, item, or usage_array
                                        let usage = group.usage || item.usage || '';
                                        if (!usage && group.usage_array && Array.isArray(group.usage_array) && group.usage_array.length > 0) {
                                            usage = group.usage_array.join(', ');
                                        } else if (!usage && item.usage_array && Array.isArray(item.usage_array) && item.usage_array.length > 0) {
                                            usage = item.usage_array.join(', ');
                                        }
                                        
                                        const oilClass = group.oil_class || item.oil_class || '';
                                        const ingredients = (group.ingredients && group.ingredients.length > 0)
                                            ? group.ingredients.map(ing => ing.ingredient_name || ing.text || 'N/A').join(', ')
                                            : ((item.ingredients && item.ingredients.length > 0)
                                                ? item.ingredients.map(ing => ing.ingredient_name || ing.text || 'N/A').join(', ')
                                                : '');
                                        
                                        // Use time from item or group, fallback to therapy time
                                        const rowTime = group.time || group.timeslot || therapyTime || '';
                                        
                                        // For therapies: Usage column = therapy name, Items column = usage, Dosage column = items + dosage, Ingredients column = time
                                        therapyRows.push({
                                            therapyName: therapyName,
                                            therapyTime: rowTime,
                                            itemNames: itemNames,
                                            usage: therapyName, // Usage column shows therapy name
                                            usageForItems: usage, // Items column shows usage
                                            dosage: itemNames + (dosageDisplay ? ` - ${dosageDisplay}` : ''), // Dosage column shows items + dosage
                                            oilClass: oilClass,
                                            ingredients: rowTime || '' // Ingredients column shows time slot
                                        });
                                    } else {
                                        // If group has no items, still create a row with just therapy name and time
                                        const rowTime = group.time || group.timeslot || therapyTime || '';
                                        const usage = group.usage || item.usage || '';
                                        const dosageDisplay = group.dosage || item.dosage || '';
                                        
                                        therapyRows.push({
                                            therapyName: therapyName,
                                            therapyTime: rowTime,
                                            itemNames: therapyName,
                                            usage: therapyName, // Usage column shows therapy name
                                            usageForItems: usage, // Items column shows usage
                                            dosage: therapyName + (dosageDisplay ? ` - ${dosageDisplay}` : ''), // Dosage column shows therapy name + dosage
                                            oilClass: group.oil_class || item.oil_class || '',
                                            ingredients: rowTime || '' // Ingredients column shows time slot
                                        });
                                    }
                                });
                            } else {
                                // If no items array, treat the whole item as a single therapy entry
                                // This handles therapies that don't have items structure (like from therapy API)
                                // For therapies from API without items, show just therapy name and time
                                const itemName = item.item_name || therapyName;
                                const dosage = item.dosage || item.dose || '';
                                const uno = item.uno || item.notes || '';
                                const dosageDisplay = (dosage && uno) ? `${dosage} (${uno})` : (dosage || uno || '');
                                
                                let usage = item.usage || '';
                                if (!usage && item.usage_array && Array.isArray(item.usage_array) && item.usage_array.length > 0) {
                                    usage = item.usage_array.join(', ');
                                }
                                
                                const oilClass = item.oil_class || '';
                                
                                // For therapies: Usage column = therapy name, Items column = usage, Dosage column = items + dosage, Ingredients column = time
                                therapyRows.push({
                                    therapyName: therapyName,
                                    therapyTime: therapyTime,
                                    itemNames: itemName,
                                    usage: therapyName, // Usage column shows therapy name
                                    usageForItems: usage, // Items column shows usage
                                    dosage: itemName + (dosageDisplay ? ` - ${dosageDisplay}` : ''), // Dosage column shows items + dosage
                                    oilClass: oilClass,
                                    ingredients: therapyTime || '' // Ingredients column shows time slot
                                });
                            }
                        });
                    }
                    
                    // Calculate approximate box height needed (include all items)
                    let estimatedHeight = 10; // Base height for header and column headers
                    Object.values(groupsByAllocation).forEach(allocationGroups => {
                        allocationGroups.forEach(group => {
                            if (group.items && group.items.length > 0) {
                                estimatedHeight += 5; // Height per row
                            }
                        });
                    });
                    therapyRows.forEach(() => {
                        estimatedHeight += 5; // Height per therapy row
                    });
                    zeroTherapistTherapies.forEach(() => {
                        estimatedHeight += 5; // Height per zero-therapist therapy row
                    });
                    checkNewPage(estimatedHeight);
                    
                    // Prescription entry - simple list format (no table borders)
                    const boxX = margin;
                    const boxStartY = yPos;
                    
                    // Column headers (no background box, just text) - only show once if there are any items
                    if (prescriptionGroups.length > 0 || therapyRows.length > 0 || zeroTherapistTherapies.length > 0) {
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
                    
                    // Render therapy treatments as rows in the same table structure
                    therapyRows.forEach((therapyRow, index) => {
                        checkNewPage(5);
                        
                        // Render row data
                        doc.setFontSize(7);
                        
                        // Usage column: Therapy name
                        doc.setFont(undefined, 'normal');
                        doc.setTextColor(0, 0, 0);
                        const usageText = therapyRow.usage || therapyRow.therapyName || '—';
                        const usageLines = doc.splitTextToSize(usageText, 25);
                        doc.text(usageLines, boxX + 2, yPos + 2);
                        
                        // Items column: Usage of therapy (in blue, bold)
                        doc.setFont(undefined, 'bold');
                        doc.setTextColor(0, 86, 179);
                        const itemsText = therapyRow.usageForItems || '—';
                        const itemsLines = doc.splitTextToSize(itemsText, 35);
                        doc.text(itemsLines, boxX + 30, yPos + 2);
                        
                        // Dosage column: Therapy items + dosage
                        doc.setFont(undefined, 'normal');
                        doc.setTextColor(0, 0, 0);
                        const doseLines = doc.splitTextToSize(therapyRow.dosage || '—', 30);
                        doc.text(doseLines, boxX + 68, yPos + 2);
                        
                        // Oil Class column
                        doc.text(therapyRow.oilClass || '—', boxX + 100, yPos + 2);
                        
                        // Ingredients column: Time slot
                        const ingredientsLines = doc.splitTextToSize(therapyRow.ingredients || '—', 30);
                        doc.text(ingredientsLines, boxX + 135, yPos + 2);
                        
                        // Calculate row height
                        const rowHeight = Math.max(
                            itemsLines.length * 2.5,
                            usageLines.length * 2.5,
                            doseLines.length * 2.5,
                            ingredientsLines.length * 2.5,
                            3.5
                        );
                        yPos += rowHeight;
                    });
                    
                    // Render zero-therapist therapies as rows in the same table structure
                    zeroTherapistTherapies.forEach((therapy, index) => {
                        checkNewPage(5);
                        
                        const therapyName = therapy.therapy_name || 'Unknown Therapy';
                        const therapyTime = therapy.timeslot || 'N/A';
                        
                        // Extract items and usage from zero-therapist therapy
                        let itemNames = '';
                        let dosageDisplay = '';
                        let usage = '';
                        
                        // Check if therapy has items_groups or items structure
                        if (therapy.items_groups && Array.isArray(therapy.items_groups) && therapy.items_groups.length > 0) {
                            // Extract items from items_groups
                            const allItems = [];
                            therapy.items_groups.forEach(group => {
                                if (group.items && Array.isArray(group.items)) {
                                    group.items.forEach(item => {
                                        allItems.push(item.item_name || 'N/A');
                                    });
                                }
                            });
                            itemNames = allItems.join(', ');
                            
                            // Get dosage and usage from first group
                            const firstGroup = therapy.items_groups[0];
                            const dosage = firstGroup.dosage || therapy.dosage || '';
                            const uno = firstGroup.uno || therapy.uno || '';
                            dosageDisplay = (dosage && uno) ? `${dosage} (${uno})` : (dosage || uno || '');
                            
                            // Extract usage
                            usage = firstGroup.usage || therapy.usage || '';
                            if (!usage && firstGroup.usage_array && Array.isArray(firstGroup.usage_array) && firstGroup.usage_array.length > 0) {
                                usage = firstGroup.usage_array.join(', ');
                            } else if (!usage && therapy.usage_array && Array.isArray(therapy.usage_array) && therapy.usage_array.length > 0) {
                                usage = therapy.usage_array.join(', ');
                            }
                        } else if (therapy.items && Array.isArray(therapy.items) && therapy.items.length > 0) {
                            // Extract items from items array
                            itemNames = therapy.items.map(item => item.item_name || 'N/A').join(', ');
                            const dosage = therapy.dosage || '';
                            const uno = therapy.uno || '';
                            dosageDisplay = (dosage && uno) ? `${dosage} (${uno})` : (dosage || uno || '');
                            
                            // Extract usage
                            usage = therapy.usage || '';
                            if (!usage && therapy.usage_array && Array.isArray(therapy.usage_array) && therapy.usage_array.length > 0) {
                                usage = therapy.usage_array.join(', ');
                            }
                        } else {
                            // If no items structure, try to get usage directly from therapy
                            usage = therapy.usage || '';
                            if (!usage && therapy.usage_array && Array.isArray(therapy.usage_array) && therapy.usage_array.length > 0) {
                                usage = therapy.usage_array.join(', ');
                            }
                        }
                        
                        // If no items found, use '—'
                        const dosageText = itemNames ? (itemNames + (dosageDisplay ? ` - ${dosageDisplay}` : '')) : '—';
                        
                        // Usage for Items column (show '—' if no usage found)
                        const usageForItems = usage || '—';
                        
                        // Render row data
                        doc.setFontSize(7);
                        
                        // Usage column: Therapy name
                        doc.setFont(undefined, 'normal');
                        doc.setTextColor(0, 0, 0);
                        const usageLines = doc.splitTextToSize(therapyName, 25);
                        doc.text(usageLines, boxX + 2, yPos + 2);
                        
                        // Items column: Usage of therapy (in blue, bold)
                        doc.setFont(undefined, 'bold');
                        doc.setTextColor(0, 86, 179);
                        const itemsLines = doc.splitTextToSize(usageForItems, 35);
                        doc.text(itemsLines, boxX + 30, yPos + 2);
                        
                        // Dosage column: Therapy items + dosage
                        doc.setFont(undefined, 'normal');
                        doc.setTextColor(0, 0, 0);
                        const doseLines = doc.splitTextToSize(dosageText, 30);
                        doc.text(doseLines, boxX + 68, yPos + 2);
                        
                        // Oil Class column: empty
                        doc.text('—', boxX + 100, yPos + 2);
                        
                        // Ingredients column: Time slot
                        doc.text(therapyTime, boxX + 135, yPos + 2);
                        
                        // Calculate row height
                        const rowHeight = Math.max(
                            itemsLines.length * 2.5,
                            usageLines.length * 2.5,
                            doseLines.length * 2.5,
                            3.5
                        );
                        yPos += rowHeight;
                    });
                    
                    yPos += 3; // Space after prescription/therapy/zero-therapist section
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
                console.log('[PDF] Saving PDF with filename:', fileName);
                doc.save(fileName);
                console.log('[PDF] PDF saved successfully');
            } catch (error) {
                console.error('[PDF] Error generating PDF:', error);
                alert('Error generating PDF: ' + error.message);
            }
        }