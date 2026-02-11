const dateInput = document.getElementById('date-filter');
        const genderInput = document.getElementById('gender-filter');
        const patientGenderInput = document.getElementById('patient-gender-filter');
        const gradeInput = document.getElementById('grade-filter');
        const refreshBtn = document.getElementById('refresh-btn');
        const tableHeadRow = document.getElementById('difficulty-table-head');
        const tableBody = document.getElementById('difficulty-table-body');
        const emptyState = document.getElementById('empty-state');
        const loadingIndicator = document.getElementById('loading-indicator');
        const statTherapists = document.getElementById('stat-therapists');
        const statAssignments = document.getElementById('stat-assignments');
        const statTopDifficulty = document.getElementById('stat-top-difficulty');
        const statTopTherapist = document.getElementById('stat-top-therapist');
        const difficultySummary = document.getElementById('difficulty-summary');

        function setLoading(isLoading) {
            loadingIndicator.classList.toggle('show', isLoading);
            tableBody.parentElement.style.opacity = isLoading ? 0.4 : 1;
        }

        function fetchDifficultyData() {
            const date = dateInput.value;
            if (!date) {
                alert('Please select a date first.');
                return;
            }
            const gender = genderInput.value;
            const patientGender = patientGenderInput ? patientGenderInput.value : '';
            const grade = gradeInput ? gradeInput.value : '';
            setLoading(true);
            let url = `/sheduling/therapist-difficulty/api/data/?date=${date}`;
            if (gender) {
                url += `&gender=${encodeURIComponent(gender)}`;
            }
            if (grade) {
                url += `&grade=${encodeURIComponent(grade)}`;
            }
            if (patientGender) {
                url += `&patient_gender=${encodeURIComponent(patientGender)}`;
            }
            fetch(url)
                .then(response => response.json())
                .then(data => {
                    setLoading(false);
                    if (!data.success) {
                        throw new Error(data.error || 'Unable to load data');
                    }
                    renderDashboard(data);
                })
                .catch(error => {
                    setLoading(false);
                    console.error('Error loading difficulty data:', error);
                    alert('Failed to load data. Please try again.');
                });
        }

        function getSelectedGrade() {
            return gradeInput ? (gradeInput.value || '').trim().toLowerCase() : '';
        }

        function filterTherapistsByGrade(therapists) {
            const selectedGrade = getSelectedGrade();
            if (!selectedGrade) {
                return therapists || [];
            }
            return (therapists || []).filter(entry => {
                const grade = (entry.therapist_grade || '').toString().toLowerCase();
                // Exact, case-insensitive grade match so that "Senior Therapist"
                // does NOT include "Super Senior Therapist"
                return grade === selectedGrade;
            });
        }

        let therapistChart = null;

        function renderDashboard(payload) {
            const { therapists: rawTherapists, difficulties, summary } = payload;

            const therapists = filterTherapistsByGrade(rawTherapists);

            statTherapists.textContent = summary.therapist_count || 0;
            statAssignments.textContent = summary.total_assignments || 0;

            const topDifficulty = Object.entries(summary.difficulty_totals || {})
                .sort((a, b) => b[1] - a[1])[0];
            statTopDifficulty.textContent = topDifficulty ? `${topDifficulty[0]} (${topDifficulty[1]})` : '—';

            const topTherapist = therapists && therapists.length ? therapists[0] : null;
            statTopTherapist.textContent = topTherapist ? topTherapist.therapist_name : '—';

            renderTable(therapists, difficulties);
            // Rebuild difficulty totals from the (possibly filtered) therapists list
            const rebuiltTotals = {};
            (difficulties || []).forEach(diff => {
                rebuiltTotals[diff] = (therapists || []).reduce((acc, t) => {
                    const counts = t.counts || {};
                    return acc + (counts[diff] || 0);
                }, 0);
            });

            renderTable(therapists, difficulties);
            renderDifficultySummary(rebuiltTotals);
            renderTherapistChart(therapists, difficulties);
            
            // Render new treatment scheduling charts
            if (summary.treatment_scheduling) {
                renderTreatmentCountsChart(summary.treatment_scheduling.treatment_counts);
                renderTherapistRequirementsChart(summary.treatment_scheduling.therapist_requirements);
            }
        }

        function renderTable(therapists, difficulties) {
            tableHeadRow.innerHTML = '<th>Therapist</th><th>Total</th>';
            difficulties.forEach(diff => {
                const th = document.createElement('th');
                th.textContent = diff;
                tableHeadRow.appendChild(th);
            });

            tableBody.innerHTML = '';
            if (!therapists || therapists.length === 0) {
                emptyState.style.display = 'block';
                const colspan = 2 + (difficulties ? difficulties.length : 0);
                tableBody.innerHTML = `<tr><td colspan="${colspan}" class="empty-state">No therapist assignments for this date.</td></tr>`;
                return;
            }

            emptyState.style.display = 'none';
            therapists.forEach(entry => {
                const tr = document.createElement('tr');
                const genderDisplay = entry.therapist_gender ? ` • ${entry.therapist_gender}` : '';
                const nameCell = `
                    <div style="font-weight:600;">${entry.therapist_name}</div>
                    <div style="font-size:12px;color:var(--text-muted);">${entry.therapist_code} • ${entry.therapist_grade || 'Grade N/A'}${genderDisplay}</div>
                `;
                tr.innerHTML = `<td>${nameCell}</td><td>${entry.total}</td>`;
                difficulties.forEach(diff => {
                    tr.innerHTML += `<td>${entry.counts[diff] || 0}</td>`;
                });
                tableBody.appendChild(tr);
            });
        }

        function renderDifficultySummary(totals) {
            if (!totals || Object.keys(totals).length === 0) {
                difficultySummary.innerHTML = '<div class="empty-state">No difficulty distribution available.</div>';
                return;
            }

            const fragments = Object.entries(totals)
                .sort((a, b) => b[1] - a[1])
                .map(([difficulty, value]) => `
                    <div class="difficulty-pill">${difficulty}: ${value}</div>
                `);
            difficultySummary.innerHTML = fragments.join('');
        }

        function renderTherapistChart(therapists, difficulties) {
            const canvas = document.getElementById('chart-therapists');
            if (!canvas) return;

            if (!therapists || !therapists.length || !difficulties || !difficulties.length) {
                if (therapistChart) {
                    therapistChart.destroy();
                    therapistChart = null;
                }
                return;
            }

            const labels = therapists.map(t => {
                // X-axis: therapist name (fallback to code if name missing)
                return t.therapist_name || t.therapist_code || '';
            });

            const lowerDiffs = difficulties.map(d => d.toLowerCase());
            const wanted = ['easy', 'medium', 'hard'];
            const usedDiffs = wanted.filter(w => lowerDiffs.includes(w));

            const datasets = usedDiffs.map((key, idx) => {
                const colorMap = {
                    easy: 'rgba(16, 185, 129, 0.7)',
                    medium: 'rgba(59, 130, 246, 0.7)',
                    hard: 'rgba(239, 68, 68, 0.7)'
                };
                const label = key.charAt(0).toUpperCase() + key.slice(1);
                const realKey = difficulties[lowerDiffs.indexOf(key)];
                const data = therapists.map(t => (t.counts && t.counts[realKey]) || 0);
                return {
                    label,
                    data,
                    backgroundColor: colorMap[key] || 'rgba(107, 114, 128, 0.7)'
                };
            });

            if (therapistChart) {
                therapistChart.data.labels = labels;
                therapistChart.data.datasets = datasets;
                therapistChart.update();
                return;
            }

            therapistChart = new Chart(canvas.getContext('2d'), {
                type: 'bar',
                data: {
                    labels,
                    datasets
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { display: true, position: 'bottom' },
                        tooltip: { enabled: true }
                    },
                    scales: {
                        x: {
                            stacked: false,
                            ticks: { color: '#4b5563', font: { size: 10 }, maxRotation: 60, minRotation: 30 },
                            grid: { display: false }
                        },
                        y: {
                            beginAtZero: true,
                            ticks: { color: '#6b7280' }
                        }
                    }
                }
            });
        }

        document.addEventListener('DOMContentLoaded', () => {
            fetchDifficultyData();
        });
        refreshBtn.addEventListener('click', fetchDifficultyData);
        dateInput.addEventListener('change', () => {
            // Automatically refresh when date is changed
            fetchDifficultyData();
        });
        genderInput.addEventListener('change', () => {
            // Automatically refresh when gender filter is changed
            fetchDifficultyData();
        });
        if (gradeInput) {
            gradeInput.addEventListener('change', () => {
                // Automatically refresh when grade filter is changed
                fetchDifficultyData();
            });
        }
        if (patientGenderInput) {
            patientGenderInput.addEventListener('change', () => {
                // Automatically refresh when patient gender filter is changed
                fetchDifficultyData();
            });
        }

        // Export to Excel
        const exportExcelBtn = document.getElementById('export-distribution-excel');
        if (exportExcelBtn) {
            exportExcelBtn.addEventListener('click', function () {
                const table = document.querySelector('#table-wrapper table');
                if (!table) {
                    alert('No therapist distribution data to export. Please load data first.');
                    return;
                }

                const headerRow = table.querySelector('thead tr');
                if (!headerRow) {
                    alert('No header row found.');
                    return;
                }

                const rows = [];
                const headers = Array.from(headerRow.querySelectorAll('th')).map(th =>
                    (th.innerText || '').trim()
                );
                rows.push(headers);

                const bodyRows = table.querySelectorAll('tbody tr');
                bodyRows.forEach(tr => {
                    const cells = Array.from(tr.querySelectorAll('td')).map(td =>
                        (td.innerText || '').trim()
                    );
                    if (cells.length > 0 && !tr.querySelector('.empty-state')) {
                        rows.push(cells);
                    }
                });

                if (rows.length <= 1) {
                    alert('No therapist distribution data to export. Please select a date and load data first.');
                    return;
                }

                const wb = XLSX.utils.book_new();
                const ws = XLSX.utils.aoa_to_sheet(rows);
                XLSX.utils.book_append_sheet(wb, ws, 'Therapist Distribution');

                const dateVal = dateInput.value ? dateInput.value.replace(/-/g, '') : new Date().toISOString().split('T')[0].replace(/-/g, '');
                XLSX.writeFile(wb, `Therapist_Distribution_${dateVal}.xlsx`);
            });
        }

        // Export to PDF - full page print (includes stats, table, graphs)
        const exportPdfBtn = document.getElementById('export-distribution-pdf');
        if (exportPdfBtn) {
            exportPdfBtn.addEventListener('click', function () {
                const dateVal = dateInput.value || new Date().toISOString().split('T')[0];
                const printDateSpan = document.getElementById('print-date-span');
                if (printDateSpan) printDateSpan.textContent = dateVal;

                // Use browser print - user can choose "Save as PDF" to get full page with graphs
                window.print();
            });
        }

        // Chart instances for treatment scheduling
        let treatmentCountsChart = null;
        let therapistRequirementsChart = null;

        function renderTreatmentCountsChart(treatmentCounts) {
            const canvas = document.getElementById('chart-treatment-counts');
            if (!canvas) return;

            const categories = ['Easy', 'Medium', 'Hard'];
            const counts = categories.map(cat => treatmentCounts[cat] || 0);

            const data = {
                labels: categories,
                datasets: [{
                    label: 'Scheduled Treatments',
                    data: counts,
                    backgroundColor: [
                        'rgba(16, 185, 129, 0.7)',   // Green for Easy
                        'rgba(59, 130, 246, 0.7)',   // Blue for Medium
                        'rgba(239, 68, 68, 0.7)'     // Red for Hard
                    ],
                    borderColor: [
                        'rgba(16, 185, 129, 1)',
                        'rgba(59, 130, 246, 1)',
                        'rgba(239, 68, 68, 1)'
                    ],
                    borderWidth: 2
                }]
            };

            if (treatmentCountsChart) {
                treatmentCountsChart.data = data;
                treatmentCountsChart.update();
                return;
            }

            treatmentCountsChart = new Chart(canvas.getContext('2d'), {
                type: 'bar',
                data: data,
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { display: false },
                        tooltip: {
                            enabled: true,
                            callbacks: {
                                label: function(context) {
                                    return `${context.label}: ${context.parsed.y} treatments`;
                                }
                            }
                        }
                    },
                    scales: {
                        x: {
                            ticks: { color: '#4b5563', font: { size: 12 } },
                            grid: { display: false }
                        },
                        y: {
                            beginAtZero: true,
                            ticks: {
                                color: '#6b7280',
                                stepSize: 1,
                                callback: function(value) {
                                    return Number.isInteger(value) ? value : '';
                                }
                            }
                        }
                    }
                }
            });
        }

        function renderTherapistRequirementsChart(therapistRequirements) {
            const canvas = document.getElementById('chart-therapist-requirements');
            if (!canvas) return;

            const categories = ['Easy', 'Medium', 'Hard'];
            const grades = ['super_senior', 'senior', 'junior', 'trainee'];
            const gradeLabels = {
                'super_senior': 'Super Senior',
                'senior': 'Senior',
                'junior': 'Junior',
                'trainee': 'Trainee'
            };
            const gradeColors = {
                'super_senior': 'rgba(139, 92, 246, 0.7)',  // Purple
                'senior': 'rgba(236, 72, 153, 0.7)',        // Pink
                'junior': 'rgba(251, 191, 36, 0.7)',        // Yellow
                'trainee': 'rgba(34, 197, 94, 0.7)'        // Green
            };

            const datasets = grades.map(grade => {
                const data = categories.map(cat => {
                    const req = therapistRequirements[cat] || {};
                    return req[grade] || 0;
                });
                return {
                    label: gradeLabels[grade],
                    data: data,
                    backgroundColor: gradeColors[grade],
                    borderColor: gradeColors[grade].replace('0.7', '1'),
                    borderWidth: 2
                };
            });

            if (therapistRequirementsChart) {
                therapistRequirementsChart.data.labels = categories;
                therapistRequirementsChart.data.datasets = datasets;
                therapistRequirementsChart.update();
                return;
            }

            therapistRequirementsChart = new Chart(canvas.getContext('2d'), {
                type: 'bar',
                data: {
                    labels: categories,
                    datasets: datasets
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: {
                            display: true,
                            position: 'bottom'
                        },
                        tooltip: {
                            enabled: true,
                            callbacks: {
                                label: function(context) {
                                    return `${context.dataset.label}: ${context.parsed.y} therapists`;
                                }
                            }
                        }
                    },
                    scales: {
                        x: {
                            stacked: false,
                            ticks: { color: '#4b5563', font: { size: 12 } },
                            grid: { display: false }
                        },
                        y: {
                            beginAtZero: true,
                            ticks: {
                                color: '#6b7280',
                                stepSize: 1,
                                callback: function(value) {
                                    return Number.isInteger(value) ? value : '';
                                }
                            }
                        }
                    }
                }
            });
        }        