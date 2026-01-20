const dateInput = document.getElementById('date-filter');
        const genderInput = document.getElementById('gender-filter');
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
            setLoading(true);
            let url = `/sheduling/therapist-difficulty/api/data/?date=${date}`;
            if (gender) {
                url += `&gender=${encodeURIComponent(gender)}`;
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

        function renderDashboard(payload) {
            const { therapists, difficulties, summary } = payload;

            statTherapists.textContent = summary.therapist_count || 0;
            statAssignments.textContent = summary.total_assignments || 0;

            const topDifficulty = Object.entries(summary.difficulty_totals || {})
                .sort((a, b) => b[1] - a[1])[0];
            statTopDifficulty.textContent = topDifficulty ? `${topDifficulty[0]} (${topDifficulty[1]})` : '—';

            const topTherapist = therapists && therapists.length ? therapists[0] : null;
            statTopTherapist.textContent = topTherapist ? topTherapist.therapist_name : '—';

            renderTable(therapists, difficulties);
            renderDifficultySummary(summary.difficulty_totals || {});
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