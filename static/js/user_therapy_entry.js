// User Therapy Entry Dashboard JavaScript
document.addEventListener('DOMContentLoaded', function () {
    setupTabs();
    setupFilters();
    setupPatientSearch();
});

function setupTabs() {
    document.querySelectorAll('.tab').forEach(tab => {
        tab.addEventListener('click', function () {
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
            this.classList.add('active');
            const target = this.dataset.tab;
            const content = document.getElementById(target);
            if (content) {
                content.classList.add('active');
            }
        });
    });
}

function setupFilters() {
    const scheduledDate = document.getElementById('scheduled-date');

    function applyDateFilter() {
        if (!scheduledDate) return;
        const dateVal = scheduledDate.value;
        const params = new URLSearchParams();
        if (dateVal) {
            params.append('date', dateVal);
        }
        const url = window.location.pathname + (params.toString() ? '?' + params.toString() : '');
        window.location.href = url;
    }

    if (scheduledDate) {
        scheduledDate.addEventListener('change', applyDateFilter);
        scheduledDate.addEventListener('keyup', function (e) {
            if (e.key === 'Enter') {
                applyDateFilter();
            }
        });
    }
}

function setupPatientSearch() {
    const searchInput = document.getElementById('patient-search');
    const searchBtn = document.getElementById('patient-search-btn');
    const clearBtn = document.getElementById('clear-patient-search');
    const therapistTable = document.getElementById('therapist-scheduled-table');
    const nurseTable = document.getElementById('nurse-scheduled-table');

    if (!searchInput) return;

    function applyPatientFilter() {
        const term = searchInput.value.trim().toLowerCase();

        function filterTable(table) {
            if (!table) return;
            const rows = table.querySelectorAll('tbody tr');
            rows.forEach(row => {
                const cell = row.querySelector('.patient-cell');
                if (!cell) {
                    row.style.display = '';
                    return;
                }
                const text = cell.textContent || '';
                if (!term || text.toLowerCase().includes(term)) {
                    row.style.display = '';
                } else {
                    row.style.display = 'none';
                }
            });
        }

        filterTable(therapistTable);
        filterTable(nurseTable);
    }

    searchInput.addEventListener('input', applyPatientFilter);
    if (searchBtn) {
        searchBtn.addEventListener('click', applyPatientFilter);
    }
    if (clearBtn) {
        clearBtn.addEventListener('click', function () {
            searchInput.value = '';
            applyPatientFilter();
        });
    }
}

// Export scheduled sessions (therapist + nurse) to Excel/PDF (client-side)
document.addEventListener('DOMContentLoaded', function () {
    const excelBtn = document.getElementById('export-scheduled-excel');
    const pdfBtn = document.getElementById('export-scheduled-pdf');

    function tableToAoA(table) {
        if (!table) return null;
        const headRow = table.querySelector('thead tr');
        if (!headRow) return null;
        const headers = Array.from(headRow.querySelectorAll('th')).map(th => (th.innerText || '').trim());
        const aoa = [headers];
        const rows = table.querySelectorAll('tbody tr');
        rows.forEach(tr => {
            const cells = Array.from(tr.querySelectorAll('td')).map(td => (td.innerText || '').trim());
            aoa.push(cells);
        });
        return aoa;
    }

    if (excelBtn) {
        excelBtn.addEventListener('click', function () {
            const therapistTable = document.getElementById('therapist-scheduled-table');
            const nurseTable = document.getElementById('nurse-scheduled-table');

            const therapistAoA = tableToAoA(therapistTable);
            const nurseAoA = tableToAoA(nurseTable);

            if ((!therapistAoA || therapistAoA.length <= 1) && (!nurseAoA || nurseAoA.length <= 1)) {
                alert('No scheduled sessions to export.');
                return;
            }

            if (typeof XLSX === 'undefined') {
                alert('Excel export library not loaded.');
                return;
            }

            const wb = XLSX.utils.book_new();
            if (therapistAoA && therapistAoA.length > 1) {
                const wsTherapist = XLSX.utils.aoa_to_sheet(therapistAoA);
                XLSX.utils.book_append_sheet(wb, wsTherapist, 'Therapist Schedule');
            }
            if (nurseAoA && nurseAoA.length > 1) {
                const wsNurse = XLSX.utils.aoa_to_sheet(nurseAoA);
                XLSX.utils.book_append_sheet(wb, wsNurse, 'Nurse Schedule');
            }

            const today = new Date().toISOString().split('T')[0];
            XLSX.writeFile(wb, `User_Scheduled_Therapies_${today}.xlsx`);
        });
    }

    if (pdfBtn) {
        pdfBtn.addEventListener('click', function () {
            const therapistTable = document.getElementById('therapist-scheduled-table');
            const nurseTable = document.getElementById('nurse-scheduled-table');

            const therapistAoA = tableToAoA(therapistTable);
            const nurseAoA = tableToAoA(nurseTable);

            if ((!therapistAoA || therapistAoA.length <= 1) && (!nurseAoA || nurseAoA.length <= 1)) {
                alert('No scheduled sessions to export.');
                return;
            }

            const { jsPDF } = window.jspdf || {};
            if (!jsPDF || !window.jspdf || !window.jspdf.jsPDF) {
                alert('PDF library not loaded.');
                return;
            }

            const doc = new window.jspdf.jsPDF('l', 'pt', 'a4');
            let currentY = 40;

            if (therapistAoA && therapistAoA.length > 1) {
                doc.text('Therapist Schedule', 40, currentY - 10);
                doc.autoTable({
                    head: [therapistAoA[0]],
                    body: therapistAoA.slice(1),
                    startY: currentY,
                    styles: { fontSize: 7, cellPadding: 3 },
                    headStyles: { fillColor: [37, 99, 235] },
                });
                currentY = doc.lastAutoTable.finalY + 30;
            }

            if (nurseAoA && nurseAoA.length > 1) {
                doc.text('Nurse Schedule', 40, currentY - 10);
                doc.autoTable({
                    head: [nurseAoA[0]],
                    body: nurseAoA.slice(1),
                    startY: currentY,
                    styles: { fontSize: 7, cellPadding: 3 },
                    headStyles: { fillColor: [37, 99, 235] },
                });
            }

            const today = new Date().toISOString().split('T')[0];
            doc.save(`User_Scheduled_Therapies_${today}.pdf`);
        });
    }
});
