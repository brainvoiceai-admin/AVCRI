// NEW PRESCRIPTION PDF GENERATION - EXACT HOSPITAL CHART FORMAT WITH PROPER TABLES
// This function generates the prescription print exactly as per hospital requirements

function generatePrescriptionPDF_NEW(prescriptionData, date) {
    console.log('[PDF NEW] ========== STARTING PDF GENERATION ==========');
    console.log('[PDF NEW] generatePrescriptionPDF_NEW called with', prescriptionData?.length || 0, 'patients');

    if (!prescriptionData || prescriptionData.length === 0) {
        alert('No prescription data available to generate PDF.');
        console.error('[PDF NEW] No prescription data provided');
        return;
    }

    try {
        const { jsPDF } = window.jspdf;
        const doc = new jsPDF('l', 'mm', 'a4'); // Landscape
        console.log('[PDF NEW] jsPDF instance created');

        const pageWidth = doc.internal.pageSize.getWidth();
        const pageHeight = doc.internal.pageSize.getHeight();
        const margin = 10;
        let yPos = margin;

        // Helper function
        function formatDateDDMMYYYY(dateStr) {
            if (!dateStr) return '';
            try {
                const date = new Date(dateStr + 'T00:00:00');
                const day = String(date.getDate()).padStart(2, '0');
                const month = String(date.getMonth() + 1).padStart(2, '0');
                const year = date.getFullYear();
                return `${day}/${month}/${year}`;
            } catch (e) {
                return dateStr;
            }
        }

        function convertTo12Hour(time24) {
            if (!time24 || time24 === '—') return '—';
            try {
                // Handle formats like "08:30", "14:30", "8:30 AM", etc.
                const timeStr = String(time24).trim();

                // If already in 12-hour format, return as is
                if (timeStr.includes('AM') || timeStr.includes('PM') || timeStr.includes('am') || timeStr.includes('pm')) {
                    return timeStr;
                }

                // Parse 24-hour format
                const parts = timeStr.split(':');
                if (parts.length < 2) return time24;

                const hours = parseInt(parts[0]);
                const minutes = parseInt(parts[1]);

                if (isNaN(hours) || isNaN(minutes)) return time24;

                const period = hours >= 12 ? 'PM' : 'AM';
                const hours12 = hours % 12 || 12;
                const minutesStr = String(minutes).padStart(2, '0');

                return `${hours12}:${minutesStr} ${period}`;
            } catch (e) {
                return time24;
            }
        }

        function checkNewPage(requiredHeight) {
            if (yPos + requiredHeight > pageHeight - 15) {
                doc.addPage();
                yPos = margin;
                return true;
            }
            return false;
        }

        // ========== HEADER ==========
        doc.setFontSize(12);
        doc.setFont(undefined, 'bold');
        doc.text('THE ARYA VAIDA CHIKITSALAYAM AND RESEARCH INSTITUTE', pageWidth / 2, yPos, { align: 'center' });
        yPos += 6;

        doc.setFontSize(10);
        const formattedDate = formatDateDDMMYYYY(date);
        doc.text(`PRESCRIPTIONS AS ON ${formattedDate}        PHYSICIAN / PHARMACY / RESEARCH`, pageWidth / 2, yPos, { align: 'center' });
        yPos += 8;

        doc.setDrawColor(0, 0, 0);
        doc.setLineWidth(0.5);
        doc.line(margin, yPos, pageWidth - margin, yPos);
        yPos += 6;

        // ========== TIME LEGEND ==========
        doc.setFontSize(8);
        doc.setFont(undefined, 'bold');
        doc.text('TIME LEGEND:', margin, yPos);
        yPos += 5;

        doc.setFont(undefined, 'normal');
        // 3-column layout for better readability
        const legendRows = [
            ['M  (5.30–5.45)  – Morning', 'BL (11.00–12.30) – Before Lunch', 'AD (8.00–8.30)  – After Dinner'],
            ['E  (5.30–6.00)  – Evening', 'AL (12.30–1.30) – After Lunch', 'BT (8.30–9.00)  – Bed Time'],
            ['ABF (8.00–8.30) – After Breakfast', 'BD (6.30–7.00)  – Before Dinner', 'NT – A Pinch Now And Then']
        ];

        const col1X = margin + 5;
        const col2X = margin + 85;
        const col3X = margin + 170;

        legendRows.forEach((row, rowIdx) => {
            const rowY = yPos + (rowIdx * 4);
            doc.text(row[0], col1X, rowY);
            doc.text(row[1], col2X, rowY);
            doc.text(row[2], col3X, rowY);
        });

        yPos += 14;

        doc.line(margin, yPos, pageWidth - margin, yPos);
        yPos += 8;

        // ========== PROCESS PATIENTS ==========
        // Group patients by room
        const patientsByRoom = {};
        prescriptionData.forEach(patient => {
            const roomNo = (patient.details?.patient_info?.room_no || patient.room_no || 'N/A').trim();
            if (!patientsByRoom[roomNo]) {
                patientsByRoom[roomNo] = [];
            }
            patientsByRoom[roomNo].push(patient);
        });

        // Process each room
        const rooms = Object.keys(patientsByRoom).sort();

        for (let roomNo of rooms) {
            const patients = patientsByRoom[roomNo];

            for (let patient of patients) {
                checkNewPage(50);

                // Extract patient info from multiple possible sources
                const patientInfo = patient.details?.patient_info || {};
                const name = patientInfo.name || patient.patient_name || 'Unknown';

                // Try to get age and gender from multiple sources
                let age = patientInfo.age || patient.age || patient.details?.age || '';
                let gender = patientInfo.sex || patientInfo.gender || patient.gender || patient.sex || patient.details?.sex || patient.details?.gender || '';

                // Try from patient object at root level
                if (!age && patient.patient_age) age = patient.patient_age;
                if (!gender && patient.patient_gender) gender = patient.patient_gender;
                if (!gender && patient.patient_sex) gender = patient.patient_sex;

                const doctor = patientInfo.doctor_name || patient.doctor_name || patient.details?.doctor_name || 'N/A';

                console.log('[PDF NEW] Patient:', name, '| Age:', age, '| Gender:', gender, '| Doctor:', doctor);
                console.log('[PDF NEW] Patient data structure:', {
                    has_details: !!patient.details,
                    has_patient_info: !!patientInfo,
                    patient_keys: Object.keys(patient)
                });
                console.log('[PDF NEW] FULL PATIENT OBJECT:', JSON.stringify(patient, null, 2).substring(0, 500));
                console.log('[PDF NEW] PATIENT INFO:', JSON.stringify(patientInfo, null, 2));

                // Patient header
                doc.setFontSize(9);
                doc.setFont(undefined, 'bold');
                doc.text(`Room: ${roomNo}`, margin, yPos);
                doc.text(`Name: ${name}`, margin + 50, yPos);
                yPos += 5;
                doc.text(`Gender: ${gender || 'N/A'}`, margin, yPos);
                doc.text(`Age: ${age || 'N/A'}`, margin + 30, yPos);
                doc.text(`Doctor: ${doctor}`, margin + 60, yPos);
                yPos += 8;

                // ========== PRESCRIPTION TABLE WITH BORDERS ==========
                const prescriptionGroups = patient.details?.prescription_groups || [];

                if (prescriptionGroups.length > 0) {
                    // Group by allocation
                    const groupsByAllocation = {};
                    prescriptionGroups.forEach(group => {
                        let allocationId = 'unknown';
                        const groupMatch = group.group_id.match(/prescription_group_(\\d+)_/);
                        if (groupMatch) {
                            allocationId = groupMatch[1];
                        } else {
                            const itemMatch = group.group_id.match(/prescription_item_(\\d+)/);
                            if (itemMatch) {
                                allocationId = `item_${itemMatch[1]}`;
                            }
                        }
                        if (!groupsByAllocation[allocationId]) {
                            groupsByAllocation[allocationId] = [];
                        }
                        groupsByAllocation[allocationId].push(group);
                    });

                    // Prepare table data
                    const tableData = [];
                    Object.values(groupsByAllocation).forEach(allocationGroups => {
                        let commonUsage = '';
                        let commonTime = '';
                        if (allocationGroups.length > 0) {
                            const g0 = allocationGroups[0];
                            if (g0.usage) {
                                commonUsage = g0.usage;
                            } else if (g0.usage_array && Array.isArray(g0.usage_array)) {
                                commonUsage = g0.usage_array.join(', ');
                            }
                            commonTime = g0.time || '';
                        }

                        // Collect ALL medicines in this allocation
                        const allMedicines = [];
                        let groupDosage = '';
                        let groupOilClass = '';
                        let groupIngredients = '';

                        allocationGroups.forEach(group => {
                            const items = group.items || [];
                            items.forEach(item => {
                                allMedicines.push(item.item_name || 'N/A');
                            });

                            if (!groupDosage) {
                                const dose = group.dose || '';
                                const unoNote = group.notes || '';
                                groupDosage = (dose && unoNote) ? `${dose} (${unoNote})` : (dose || unoNote);
                            }

                            if (!groupOilClass && group.oil_class) {
                                groupOilClass = group.oil_class;
                            }

                            if (!groupIngredients && group.ingredients && group.ingredients.length > 0) {
                                groupIngredients = group.ingredients.map(ing => ing.ingredient_name || ing.text || '').join(', ');
                            }
                        });

                        // Combine all medicines with + and add dosage at END
                        const medicinesText = allMedicines.join(' + ');
                        const itemsWithDosage = groupDosage
                            ? `${medicinesText} — [${groupDosage}]`
                            : medicinesText;

                        const timeUsageText = commonTime ? `${commonTime} / ${commonUsage}` : commonUsage;

                        tableData.push([
                            timeUsageText || '—',
                            itemsWithDosage,
                            groupOilClass || '—',
                            groupIngredients || '—'
                        ]);
                    });

                    // Draw prescription table using autoTable
                    doc.autoTable({
                        startY: yPos,
                        head: [['Time / Usage', 'Items', 'Oil Class', 'Ingredients']],
                        body: tableData,
                        theme: 'grid',
                        styles: {
                            fontSize: 8,
                            cellPadding: 2,
                            lineColor: [0, 0, 0],
                            lineWidth: 0.1
                        },
                        headStyles: {
                            fillColor: [240, 240, 240],
                            textColor: [0, 0, 0],
                            fontStyle: 'bold',
                            halign: 'left'
                        },
                        columnStyles: {
                            0: { cellWidth: 30 },   // Time/Usage
                            1: { cellWidth: 140 },  // Items (wider for long medicine names)
                            2: { cellWidth: 25 },   // Oil Class
                            3: { cellWidth: 60 }    // Ingredients
                        },
                        margin: { left: margin, right: margin },
                        tableWidth: 'auto'
                    });

                    yPos = doc.lastAutoTable.finalY + 5;
                }

                // ========== THERAPY TABLE WITH BORDERS ==========
                const therapyItemsFromDetails = patient.details?.therapy_items || [];
                const therapyItemsFromAPI = patient.therapy_items || [];
                const allTherapyItems = [...therapyItemsFromDetails, ...therapyItemsFromAPI];
                const zeroTherapistTherapies = patient.zero_therapist_therapies || [];

                console.log('[PDF NEW] Patient:', name, 'Therapies:', allTherapyItems.length, 'Zero:', zeroTherapistTherapies.length);

                if (allTherapyItems.length > 0 || zeroTherapistTherapies.length > 0) {
                    const therapyTableData = [];

                    // Regular therapies
                    allTherapyItems.forEach((therapyItem, index) => {
                        // Debug: log first therapy item to see structure
                        if (index === 0) {
                            console.log('[PDF NEW] THERAPY ITEM STRUCTURE:', JSON.stringify(therapyItem, null, 2));
                        }

                        const therapyName = therapyItem.therapy_name || 'Unknown Therapy';
                        const timeslot24 = therapyItem.timeslot || therapyItem.time || '—';
                        const timeslot = convertTo12Hour(timeslot24);

                        // Extract usage from multiple possible fields
                        let usage = therapyItem.usage || '';
                        if (!usage && therapyItem.usage_array && Array.isArray(therapyItem.usage_array)) {
                            usage = therapyItem.usage_array.filter(u => u).join(', ');
                        }
                        // Fallback: Check if usage is in the items array (nested)
                        if (!usage && therapyItem.items && Array.isArray(therapyItem.items) && therapyItem.items[0]) {
                            usage = therapyItem.items[0].usage || '';
                        }
                        if (!usage) usage = '—';

                        // Extract dates - check multiple possible fields
                        let fromDate = '—';
                        let toDate = '—';

                        const rawFrom = therapyItem.from_date || therapyItem.from || '';
                        const rawTo = therapyItem.to_date || therapyItem.to || '';

                        if (rawFrom) fromDate = formatDateDDMMYYYY(rawFrom);
                        if (rawTo) toDate = formatDateDDMMYYYY(rawTo);

                        let itemsWithDosage = '';

                        // Check if items structure is nested (groups of items)
                        if (therapyItem.items && Array.isArray(therapyItem.items) && therapyItem.items.length > 0) {
                            const allItems = [];
                            let dosage = therapyItem.dosage || therapyItem.dose || '';

                            therapyItem.items.forEach(group => {
                                // If it's a group object with an internal items array
                                if (group && group.items && Array.isArray(group.items)) {
                                    group.items.forEach(it => {
                                        if (it && it.item_name) allItems.push(it.item_name);
                                    });
                                    if (!dosage) dosage = group.dosage || group.dose || group.quantity || '';
                                } else if (group && group.item_name) {
                                    // If it's just a flat item object
                                    allItems.push(group.item_name);
                                    if (!dosage) dosage = group.dosage || group.dose || group.quantity || '';
                                }
                            });

                            itemsWithDosage = allItems.join(' + ');
                            if (dosage) {
                                itemsWithDosage += ` [${dosage}]`;
                            }
                        }

                        // Fallback: If still empty, use the therapy's top-level dosage
                        if (!itemsWithDosage) {
                            itemsWithDosage = therapyItem.dosage || therapyItem.dose || '—';
                        }

                        therapyTableData.push([therapyName, usage, itemsWithDosage, timeslot, fromDate, toDate]);
                    });

                    // Zero-therapist therapies
                    zeroTherapistTherapies.forEach(therapy => {
                        const therapyName = therapy.therapy_name || 'Unknown Therapy';
                        const timeslot24 = therapy.timeslot || '—';
                        const timeslot = convertTo12Hour(timeslot24);

                        // Extract usage
                        let usage = therapy.usage || '';
                        if (!usage && therapy.usage_array && Array.isArray(therapy.usage_array)) {
                            usage = therapy.usage_array.filter(u => u).join(', ');
                        }
                        if (!usage) usage = '—';

                        // Extract dates
                        let fromDate = '—';
                        let toDate = '—';

                        const rawFrom = therapy.from_date || therapy.from || '';
                        const rawTo = therapy.to_date || therapy.to || '';

                        if (rawFrom) fromDate = formatDateDDMMYYYY(rawFrom);
                        if (rawTo) toDate = formatDateDDMMYYYY(rawTo);

                        let itemsWithDosage = '';
                        if (therapy.items_groups && Array.isArray(therapy.items_groups)) {
                            const allItems = [];
                            let dosage = therapy.dosage || therapy.dose || '';

                            therapy.items_groups.forEach(group => {
                                if (group.items && Array.isArray(group.items)) {
                                    group.items.forEach(item => {
                                        if (item && item.item_name) allItems.push(item.item_name);
                                    });
                                }
                                // Check multiple dosage fields
                                if (!dosage) {
                                    dosage = group.dosage || group.dose || group.quantity || '';
                                }
                            });

                            itemsWithDosage = allItems.join(' + ');
                            if (dosage) {
                                itemsWithDosage += ` [${dosage}]`;
                            }
                        }

                        // Fallback
                        if (!itemsWithDosage) {
                            itemsWithDosage = therapy.dosage || therapy.dose || '—';
                        }

                        therapyTableData.push([therapyName, usage, itemsWithDosage, timeslot, fromDate, toDate]);
                    });

                    if (therapyTableData.length > 0) {
                        checkNewPage(30);

                        doc.autoTable({
                            startY: yPos,
                            head: [['Therapy', 'Usage', 'Items (Dosage)', 'Time', 'From', 'To']],
                            body: therapyTableData,
                            theme: 'grid',
                            styles: {
                                fontSize: 8,
                                cellPadding: 2,
                                lineColor: [0, 0, 0],
                                lineWidth: 0.1
                            },
                            headStyles: {
                                fillColor: [76, 175, 80],  // Green header like screenshot
                                textColor: [255, 255, 255],
                                fontStyle: 'bold',
                                halign: 'left'
                            },
                            columnStyles: {
                                0: { cellWidth: 32 },   // Therapy
                                1: { cellWidth: 15 },   // Usage
                                2: { cellWidth: 70 },   // Items (Dosage)
                                3: { cellWidth: 18 },   // Time
                                4: { cellWidth: 22 },   // From
                                5: { cellWidth: 22 }    // To
                                // Total: 179mm (fits in 237mm landscape with margins)
                            },
                            margin: { left: margin, right: margin },
                            tableWidth: 'auto'
                        });

                        yPos = doc.lastAutoTable.finalY + 5;
                    }
                }

                // Separator between patients
                yPos += 5;
                doc.setDrawColor(200, 200, 200);
                doc.setLineWidth(0.3);
                doc.line(margin, yPos, pageWidth - margin, yPos);
                yPos += 10;
            }
        }

        // Save PDF
        const fileName = `Prescription_Chart_${date.replace(/-/g, '_')}.pdf`;
        console.log('[PDF NEW] Saving PDF with filename:', fileName);
        doc.save(fileName);
        console.log('[PDF NEW] PDF saved successfully');
    } catch (error) {
        console.error('[PDF NEW] Error generating PDF:', error);
        alert('Error generating PDF: ' + error.message);
    }
}
