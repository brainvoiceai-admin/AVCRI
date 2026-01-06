// Sample data - in a real app, this would come from an API
        const PATIENTS = [
            { 
                id: 'DS-1', 
                name: 'Jacqueline Chua So', 
                sex: 'F', 
                age: 46, 
                room: 'IP-12', 
                facility: 'IP Room', 
                therapy: 'Charaka Team',
                therapies: [
                    { 
                        therapyName: 'Kashayam Regimen', 
                        therapyItems: [], 
                        medicines: [
                            { name: 'Vecrathadi Kashayam', dose: '10 ml', qty: 1, time: 'M', notes: 'Chandraprabha', prescribedOn: '2025-10-22' },
                            { name: 'Gandharvahasthadi Kashayam', dose: '15 ml', qty: 1, time: 'M', notes: '', prescribedOn: '2025-10-22' },
                            { name: 'Dhanwantharam Kashayam', dose: '15 ml', qty: 1, time: 'AL', notes: '', prescribedOn: '2025-08-15' }
                        ]
                    }
                ], 
                history: [] 
            },
            { 
                id: 'REG-1001', 
                name: 'Asha Patel', 
                sex: 'F', 
                age: 34, 
                room: 'PH-03', 
                facility: 'IP Pharmacy', 
                therapy: 'Physiotherapy',
                therapies: [
                    { 
                        therapyName: 'Physiotherapy', 
                        therapyItems: [], 
                        medicines: [
                            { name: 'Paracetamol', dose: '500 mg', qty: 15, time: 'M', notes: 'After food', prescribedOn: getTodayDate() },
                            { name: 'Amoxicillin', dose: '250 mg', qty: 14, time: 'M', notes: '', prescribedOn: getTodayDate() }
                        ]
                    }
                ], 
                history: [] 
            },
            { 
                id: 'REG-1002', 
                name: 'Ravi Kumar', 
                sex: 'M', 
                age: 56, 
                room: 'KR-01', 
                facility: 'KashayaRoom', 
                therapy: 'Ayurvedic',
                therapies: [
                    { 
                        therapyName: 'Ayurvedic Kashaya', 
                        therapyItems: [], 
                        medicines: [
                            { name: 'Trikatu', dose: '2 g', qty: 30, time: 'BL', notes: 'Brew and sip', prescribedOn: getTodayDate() }
                        ]
                    }
                ], 
                history: [] 
            },
            { 
                id: 'REG-1003', 
                name: 'Meena Joshi', 
                sex: 'F', 
                age: 22, 
                room: 'PH-09', 
                facility: 'IP Pharmacy', 
                therapy: 'Respiratory',
                therapies: [
                    { 
                        therapyName: 'Respiratory Therapy', 
                        therapyItems: [], 
                        medicines: [
                            { name: 'Salbutamol inhaler', dose: '2 puffs', qty: 1, time: 'BT', notes: 'PRN', prescribedOn: getTodayDate() }
                        ]
                    }
                ], 
                history: [] 
            }
        ];

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
            document.getElementById('dateFilter').value = getTodayDate();
            
            // Render the patient list
            renderPatients();
            
            // Update statistics
            updateStatistics();
            
            // Set up event listeners
            setupEventListeners();
        });

        function renderPatients() {
            const patientsList = document.getElementById('patientsList');
            const searchTerm = document.getElementById('search').value.toLowerCase();
            const activeFilter = document.querySelector('.filter-tab.active').dataset.filter;
            const selectedDate = document.getElementById('dateFilter').value;
            
            // Filter patients based on search and filter
            const filteredPatients = PATIENTS.filter(patient => {
                // Search filter
                const matchesSearch = patient.name.toLowerCase().includes(searchTerm) || 
                                      patient.id.toLowerCase().includes(searchTerm);
                
                // Status filter
                let matchesFilter = true;
                if (activeFilter === 'pending') {
                    matchesFilter = !isPatientFullyPrepared(patient, selectedDate);
                } else if (activeFilter === 'prepared') {
                    matchesFilter = isPatientFullyPrepared(patient, selectedDate);
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
                patientCard.dataset.id = patient.id;
                
                // Check if patient has any medicines for selected date
                const hasMedsForDate = hasMedicinesForDate(patient, selectedDate);
                if (!hasMedsForDate) {
                    patientCard.style.opacity = '0.6';
                }
                
                // Count medicines for selected date
                const medsCount = countMedicinesForDate(patient, selectedDate);
                const preparedCount = countPreparedMedicines(patient, selectedDate);
                const isFullyPrepared = preparedCount === medsCount && medsCount > 0;
                
                patientCard.innerHTML = `
                    <div class="patient-name">
                        ${escapeHtml(patient.name)}
                        <span class="status-badge ${isFullyPrepared ? 'status-prepared' : 'status-pending'}">
                            ${isFullyPrepared ? 'Prepared' : 'Pending'}
                        </span>
                    </div>
                    <div class="patient-id">${escapeHtml(patient.id)}</div>
                    <div class="patient-details">
                        <span>${patient.age} yrs</span>
                        <span>${patient.sex}</span>
                        <span>Room ${patient.room}</span>
                    </div>
                    <div class="patient-meds">
                        <span class="meds-count">${medsCount} medicines</span>
                        <span>${preparedCount}/${medsCount} prepared</span>
                    </div>
                `;
                
                patientCard.addEventListener('click', function() {
                    selectPatient(patient.id);
                    highlightActivePatient(patient.id);
                });
                
                patientsList.appendChild(patientCard);
            });
        }

        function hasMedicinesForDate(patient, date) {
            for (const therapy of patient.therapies) {
                for (const medicine of therapy.medicines) {
                    if (medicine.prescribedOn === date) {
                        return true;
                    }
                }
            }
            return false;
        }

        function countMedicinesForDate(patient, date) {
            let count = 0;
            for (const therapy of patient.therapies) {
                for (const medicine of therapy.medicines) {
                    if (medicine.prescribedOn === date) {
                        count++;
                    }
                }
            }
            return count;
        }

        function countPreparedMedicines(patient, date) {
            // In a real app, this would check against a database
            // For now, we'll use a simple approach - mark all as not prepared initially
            return 0;
        }

        function isPatientFullyPrepared(patient, date) {
            const totalMeds = countMedicinesForDate(patient, date);
            const preparedMeds = countPreparedMedicines(patient, date);
            return totalMeds > 0 && preparedMeds === totalMeds;
        }

        function selectPatient(patientId) {
            const patient = PATIENTS.find(p => p.id === patientId);
            if (!patient) return;
            
            // Show patient view
            document.getElementById('noSelection').style.display = 'none';
            document.getElementById('patientView').style.display = 'block';
            
            // Update patient info
            document.getElementById('pv_name').textContent = patient.name;
            document.getElementById('pv_meta').textContent = `${patient.id} • Age ${patient.age} • ${patient.sex}`;
            document.getElementById('pv_room').textContent = patient.room;
            document.getElementById('pv_therapy').textContent = patient.therapy;
            
            // Render medicines
            renderPatientMedicines(patient);
        }

        function renderPatientMedicines(patient) {
            const selectedDate = document.getElementById('dateFilter').value;
            const pvContent = document.getElementById('pv_content');
            
            // Clear content
            pvContent.innerHTML = '';
            
            // Group medicines by time slot
            const medicinesByTime = {};
            
            for (const therapy of patient.therapies) {
                for (const medicine of therapy.medicines) {
                    if (medicine.prescribedOn === selectedDate) {
                        const timeSlot = medicine.time || 'M';
                        if (!medicinesByTime[timeSlot]) {
                            medicinesByTime[timeSlot] = [];
                        }
                        medicinesByTime[timeSlot].push({
                            ...medicine,
                            therapyName: therapy.therapyName
                        });
                    }
                }
            }
            
            // If no medicines for selected date
            if (Object.keys(medicinesByTime).length === 0) {
                pvContent.innerHTML = '<p>No medicines prescribed for selected date.</p>';
                return;
            }
            
            // Define time slot order
            const timeSlotOrder = ['M', 'ABF', 'BL', 'AL', 'E', 'AD', 'BT', 'PRN'];
            const timeSlotLabels = {
                'M': 'Morning',
                'ABF': 'After Breakfast',
                'BL': 'Before Lunch',
                'AL': 'After Lunch',
                'E': 'Evening',
                'AD': 'After Dinner',
                'BT': 'Bed Time',
                'PRN': 'As Needed'
            };
            
            // Render medicines by time slot
            timeSlotOrder.forEach(timeSlot => {
                if (medicinesByTime[timeSlot]) {
                    const timeSlotDiv = document.createElement('div');
                    timeSlotDiv.className = 'time-slots';
                    
                    const timeSlotTitle = document.createElement('div');
                    timeSlotTitle.className = 'time-slot-title';
                    timeSlotTitle.textContent = timeSlotLabels[timeSlot] || timeSlot;
                    timeSlotDiv.appendChild(timeSlotTitle);
                    
                    medicinesByTime[timeSlot].forEach(medicine => {
                        const medicineCard = document.createElement('div');
                        medicineCard.className = 'medicine-card';
                        
                        medicineCard.innerHTML = `
                            <div class="medicine-checkbox">
                                <input type="checkbox" id="med-${medicine.name.replace(/\s+/g, '-')}">
                            </div>
                            <div class="medicine-details">
                                <div class="medicine-name">${escapeHtml(medicine.name)}</div>
                                <div class="medicine-meta">
                                    <span>Dose: ${escapeHtml(medicine.dose)}</span>
                                    <span>Therapy: ${escapeHtml(medicine.therapyName)}</span>
                                    <span>Notes: ${escapeHtml(medicine.notes || 'None')}</span>
                                </div>
                            </div>
                            <div class="medicine-qty">Qty: ${medicine.qty}</div>
                        `;
                        
                        timeSlotDiv.appendChild(medicineCard);
                    });
                    
                    pvContent.appendChild(timeSlotDiv);
                }
            });
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
            const selectedDate = document.getElementById('dateFilter').value;
            let totalMeds = 0;
            let preparedMeds = 0;
            
            PATIENTS.forEach(patient => {
                for (const therapy of patient.therapies) {
                    for (const medicine of therapy.medicines) {
                        if (medicine.prescribedOn === selectedDate) {
                            totalMeds++;
                            // In a real app, we would check if this medicine is prepared
                            // For now, we'll assume none are prepared
                        }
                    }
                }
            });
            
            document.getElementById('totalMeds').textContent = totalMeds;
            document.getElementById('pendingMeds').textContent = totalMeds - preparedMeds;
            document.getElementById('preparedMeds').textContent = preparedMeds;
        }

        function setupEventListeners() {
            // Search input
            document.getElementById('search').addEventListener('input', renderPatients);
            
            // Date filter
            document.getElementById('dateFilter').addEventListener('change', function() {
                renderPatients();
                updateStatistics();
                
                // If a patient is selected, update their medicine list
                const activePatientCard = document.querySelector('.patient-card.active');
                if (activePatientCard) {
                    const patientId = activePatientCard.dataset.id;
                    selectPatient(patientId);
                }
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
                // In a real app, this would mark all medicines as prepared in the database
                alert('All medicines marked as prepared!');
                // Refresh the view
                const activePatientCard = document.querySelector('.patient-card.active');
                if (activePatientCard) {
                    const patientId = activePatientCard.dataset.id;
                    selectPatient(patientId);
                }
                renderPatients();
                updateStatistics();
            });
            
            // Export CSV button
            document.getElementById('exportPatientCSV').addEventListener('click', function() {
                alert('Patient data exported as CSV!');
                // In a real app, this would generate and download a CSV file
            });
            
            // Save changes button
            document.getElementById('saveChangesBtn').addEventListener('click', function() {
                alert('Changes saved!');
                // In a real app, this would save the preparation status to the database
                renderPatients();
                updateStatistics();
            });
        }