const dateInput = document.getElementById('date-filter');
        const genderInput = document.getElementById('gender-filter');
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
            const grade = gradeInput ? gradeInput.value : '';
            setLoading(true);
            let url = `/sheduling/therapist-difficulty/api/data/?date=${date}`;
            if (gender) {
                url += `&gender=${encodeURIComponent(gender)}`;
            }
            if (grade) {
                url += `&grade=${encodeURIComponent(grade)}`;
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