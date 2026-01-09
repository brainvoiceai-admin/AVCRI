// Therapy Status Chart
        const therapyStatusData = {{ therapy_status_data|safe }};
        new Chart(document.getElementById('therapyStatusChart'), {
            type: 'doughnut',
            data: {
                labels: Object.keys(therapyStatusData),
                datasets: [{
                    data: Object.values(therapyStatusData),
                    backgroundColor: ['#2ed573', '#e74c3c', '#f39c12', '#3498db']
                }]
            }
        });

        // Prescription Status Chart
        const prescriptionStatusData = {{ prescription_status_data|safe }};
        new Chart(document.getElementById('prescriptionStatusChart'), {
            type: 'doughnut',
            data: {
                labels: Object.keys(prescriptionStatusData),
                datasets: [{
                    data: Object.values(prescriptionStatusData),
                    backgroundColor: ['#2ed573', '#e74c3c', '#f39c12', '#3498db']
                }]
            }
        });

        // Top Therapies Chart
        const topTherapiesData = {{ top_therapies|safe }};
        new Chart(document.getElementById('topTherapiesChart'), {
            type: 'bar',
            data: {
                labels: topTherapiesData.map(t => t.therapy_name),
                datasets: [{
                    label: 'Count',
                    data: topTherapiesData.map(t => t.count),
                    backgroundColor: '#2ed573'
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    y: { beginAtZero: true }
                }
            }
        });

        // Daily Bookings Chart
        const dailyBookingsData = {{ daily_bookings_data|safe }};
        new Chart(document.getElementById('dailyBookingsChart'), {
            type: 'line',
            data: {
                labels: dailyBookingsData.dates,
                datasets: [{
                    label: 'Bookings',
                    data: dailyBookingsData.counts,
                    borderColor: '#2ed573',
                    backgroundColor: 'rgba(46, 213, 115, 0.1)',
                    fill: true
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    y: { beginAtZero: true }
                }
            }
        });

        // Therapist Utilization Chart
        const therapistUtilData = {{ therapist_utilization|safe }};
        new Chart(document.getElementById('therapistUtilChart'), {
            type: 'bar',
            data: {
                labels: therapistUtilData.map(t => t.therapist__therapist_name),
                datasets: [{
                    label: 'Bookings',
                    data: therapistUtilData.map(t => t.count),
                    backgroundColor: '#3498db'
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    y: { beginAtZero: true }
                }
            }
        });

        // Room Utilization Chart
        const roomUtilData = {{ room_utilization|safe }};
        new Chart(document.getElementById('roomUtilChart'), {
            type: 'bar',
            data: {
                labels: roomUtilData.map(r => r.room__room_no),
                datasets: [{
                    label: 'Bookings',
                    data: roomUtilData.map(r => r.count),
                    backgroundColor: '#f39c12'
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    y: { beginAtZero: true }
                }
            }
        });