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
            let roomNo = (patient.details?.patient_info?.room_no || patient.room_no || 'N/A').trim();
            const roomKey = roomNo.toUpperCase();
            if (!patientsByRoom[roomKey]) {
                patientsByRoom[roomKey] = [];
            }
            patientsByRoom[roomKey].push(patient);
        });

        // STRICT HOSPITAL CHART ORDER CONFIGURATION
        const SECTION_CONFIG = [
            {
                title: 'SUITE – GROUND FLOOR',
                rooms: ['DS-1', 'DS-2', 'DS-3', 'DS-4', 'DS-5', 'DS-6', 'NR-7', 'NR-8', 'NR-9', 'NR-10', 'NR-11', 'NR-12', 'NR-13', 'NR-14', 'NR-28', 'NR-29', 'NR-31', 'NR-32', 'NR-33']
            },
            {
                title: 'FIRST FLOOR',
                rooms: ['NR-15', 'NR-15A', 'NR-16', 'NR-17', 'NR-18', 'NR-19', 'NR-20', 'NR-21', 'NR-22', 'NR-23', 'NR-24', 'NR-25', 'NR-26', 'NR-27']
            },
            {
                title: 'COTTAGES – NEW BLOCK',
                rooms: ['CT-1', 'CT-2', 'CT-3', 'CT-4', 'CT-5', 'CT-6', 'CT-7', 'CT-8', 'CT-9', 'CT-10', 'CT-11', 'CT-12', 'CT-14', 'CT-16', 'CT-17', 'CT-19', 'CT-20', 'CT-21', 'CT-22', 'CT-23']
            },
            {
                title: 'GENERAL WARD ROOMS',
                rooms: ['MG-1', 'MG-3', 'MG-4', 'MG-5', 'FG-1', 'FG-2', 'FG-3', 'FG-5', 'FG-7', 'FG-8']
            },
            {
                title: 'CABIN',
                rooms: ['CB-1', 'CB-2']
            }
        ];

        const processedRooms = new Set();

        // 1. Process Defined Sections
        SECTION_CONFIG.forEach(section => {
            let sectionHeaderPrinted = false;
            section.rooms.forEach(roomDef => {
                const roomKey = roomDef.toUpperCase();
                if (patientsByRoom[roomKey]) {
                    if (!sectionHeaderPrinted) {
                        checkNewPage(20);
                        doc.setFontSize(11);
                        doc.setFont(undefined, 'bold');
                        doc.text(section.title, margin, yPos);
                        yPos += 8;
                        doc.line(margin, yPos - 3, pageWidth - margin, yPos - 3);
                        sectionHeaderPrinted = true;
                    }
                    processRoomPatients(roomKey);
                    processedRooms.add(roomKey);
                }
            });
        });

        // 2. Process OP Patients
        const opRooms = Object.keys(patientsByRoom).filter(r => r.startsWith('OP') && !processedRooms.has(r));
        if (opRooms.length > 0) {
            opRooms.sort((a, b) => a.localeCompare(b, undefined, { numeric: true, sensitivity: 'base' }));
            let sectionHeaderPrinted = false;
            opRooms.forEach(roomKey => {
                if (!sectionHeaderPrinted) {
                    checkNewPage(20);
                    doc.setFontSize(11);
                    doc.setFont(undefined, 'bold');
                    doc.text('OP PATIENTS', margin, yPos);
                    yPos += 8;
                    doc.line(margin, yPos - 3, pageWidth - margin, yPos - 3);
                    sectionHeaderPrinted = true;
                }
                processRoomPatients(roomKey);
                processedRooms.add(roomKey);
            });
        }

        // 3. Process Remaining Rooms
        const remainingRooms = Object.keys(patientsByRoom).filter(r => !processedRooms.has(r));
        if (remainingRooms.length > 0) {
            remainingRooms.sort((a, b) => a.localeCompare(b, undefined, { numeric: true, sensitivity: 'base' }));
            let sectionHeaderPrinted = false;
            remainingRooms.forEach(roomKey => {
                if (!sectionHeaderPrinted) {
                    checkNewPage(20);
                    doc.setFontSize(11);
                    doc.setFont(undefined, 'bold');
                    doc.text('OTHER ROOMS', margin, yPos);
                    yPos += 8;
                    doc.line(margin, yPos - 3, pageWidth - margin, yPos - 3);
                    sectionHeaderPrinted = true;
                }
                processRoomPatients(roomKey);
            });
        }

        function processRoomPatients(roomKey) {
            const patients = patientsByRoom[roomKey];
            for (let patient of patients) {
                checkNewPage(50);

                // Get display room no
                const roomNo = (patient.details?.patient_info?.room_no || patient.room_no || 'N/A').trim();

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

                // Get doctor name and team from multiple possible sources
                const doctorName = (patientInfo.doctor_name || patient.doctor_name || patient.details?.doctor_name || patient.details?.patient_info?.doctor_name || '').trim();
                const doctorTeam = (patientInfo.doctor_team || patient.doctor_team || patient.details?.doctor_team || patient.details?.patient_info?.doctor_team || '').trim();
                const rawDoa = (patientInfo.doa || patient.doa || patient.details?.patient_info?.doa || patient.details?.doa || '').trim();
                const cleanDoa = (rawDoa && rawDoa !== '—' && rawDoa !== 'null' && rawDoa !== 'None') ? rawDoa : '';

                console.log(`[PDF NEW] Patient: ${name}, Doctor: ${doctorName}, Team: ${doctorTeam}, DOA: ${cleanDoa}`);
                console.log('[PDF NEW] Data keys:', {
                    patient: Object.keys(patient),
                    patientInfo: patientInfo ? Object.keys(patientInfo) : 'null'
                });

                // ========== PATIENT HEADER - 2 LINE PROFESSIONAL LAYOUT ==========
                doc.setFontSize(9);
                doc.setFont(undefined, 'bold');

                // Column positions for professional alignment
                const col1 = margin;        // Room / Gender
                const col2 = margin + 40;   // Name / Age
                const col3 = margin + 65;   // Doctor
                const col4 = margin + 155;  // Doctor Team
                const col5 = margin + 215;  // DOA

                // Line 1: Room and Name
                doc.text(`Room: ${roomNo}`, col1, yPos);
                doc.text(`Name: ${name}`, col2, yPos);
                yPos += 5;

                // Line 2: Gender, Age, Doctor, Doctor Team, DOA
                doc.text(`Gender: ${gender || 'N/A'}`, col1, yPos);
                doc.text(`Age: ${age || 'N/A'}`, col2, yPos);
                if (doctorName) {
                    doc.text(`Doctor: ${doctorName}`, col3, yPos);
                }
                if (doctorTeam && doctorTeam !== '—') {
                    doc.text(`Doctor Team: ${doctorTeam}`, col4, yPos);
                }
                if (cleanDoa) {
                    doc.text(`DOA: ${cleanDoa}`, col5, yPos);
                }
                yPos += 5;

                yPos += 3; // Extra gap before table

                // ========== PRESCRIPTION TABLE WITH BORDERS ==========
                const prescriptionGroups = patient.details?.prescription_groups || [];

                if (prescriptionGroups.length > 0) {
                    // Group by allocation
                    const groupsByAllocation = {};
                    prescriptionGroups.forEach(group => {
                        let allocationId = 'unknown';
                        const groupMatch = group.group_id.match(/prescription_group_(\d+)_/);
                        if (groupMatch) {
                            allocationId = groupMatch[1];
                        } else {
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

                    // Prepare table data
                    const tableData = [];
                    Object.values(groupsByAllocation).forEach(allocationGroups => {
                        let commonUsage = '';
                        let commonTime = '';
                        // Try to find common usage/time from the first group that has them
                        for (const g of allocationGroups) {
                            if (g.usage) {
                                commonUsage = g.usage;
                            } else if (g.usage_array && Array.isArray(g.usage_array)) {
                                commonUsage = g.usage_array.join(', ');
                            }
                            if (g.time) commonTime = g.time;
                            if (commonUsage && commonTime) break;
                        }

                        // Collect ALL medicines in this allocation, but keep them grouped with their dosages
                        const formattedLines = [];
                        let groupOilClass = '';
                        const allIngredients = [];

                        allocationGroups.forEach((group, idx) => {
                            const items = group.items || [];
                            const itemNames = items.map(item => item.item_name || 'N/A').join(' + ');

                            // Get dosage for THIS group
                            let currentDosage = group.dose || group.dosage || '';
                            const notes = group.notes || group.uno || '';
                            if (notes) {
                                currentDosage = currentDosage ? `${currentDosage} (${notes})` : notes;
                            }
                            // Fallback to item dosage if group dosage missing
                            if (!currentDosage && items.length > 0) {
                                // Try first item's dosage
                                if (items[0].dose || items[0].dosage) {
                                    currentDosage = items[0].dose || items[0].dosage;
                                }
                            }

                            let line = itemNames;
                            if (currentDosage) {
                                line += ` [${currentDosage}]`;
                            }

                            // Add prefix for subsequent groups (visual separation)
                            if (idx > 0) {
                                line = '+ ' + line;
                            }

                            if (line.trim()) {
                                formattedLines.push(line);
                            }

                            // Capture Oil Class - check all groups and use first non-empty value
                            // If multiple groups have different oil classes, we'll use the first one
                            // Also check for alternative field names
                            if (!groupOilClass) {
                                const oilClassValue = group.oil_class || group.oilClass || group.oil_class_name || '';
                                if (oilClassValue) {
                                    const trimmedValue = String(oilClassValue).trim();
                                    if (trimmedValue) {
                                        groupOilClass = trimmedValue;
                                    }
                                }
                            }

                            // Capture Ingredients - handle multiple formats:
                            // 1. Array of objects: [{ingredient_name: "..."}, {text: "..."}]
                            // 2. Array of strings: ["ingredient1", "ingredient2"]
                            // 3. String: "ingredient1, ingredient2"
                            // 4. Empty/null: skip
                            if (group.ingredients) {
                                let ingredientText = '';

                                if (Array.isArray(group.ingredients)) {
                                    if (group.ingredients.length > 0) {
                                        // Check if it's an array of objects or strings
                                        if (typeof group.ingredients[0] === 'object' && group.ingredients[0] !== null) {
                                            // Array of objects
                                            ingredientText = group.ingredients
                                                .map(ing => {
                                                    if (typeof ing === 'string') return ing;
                                                    return ing.ingredient_name || ing.text || ing.name || '';
                                                })
                                                .filter(Boolean)
                                                .join(', ');
                                        } else {
                                            // Array of strings
                                            ingredientText = group.ingredients
                                                .filter(ing => ing && String(ing).trim())
                                                .map(ing => String(ing).trim())
                                                .join(', ');
                                        }
                                    }
                                } else if (typeof group.ingredients === 'string') {
                                    // Single string
                                    ingredientText = group.ingredients.trim();
                                }

                                if (ingredientText) {
                                    allIngredients.push(ingredientText);
                                }
                            }
                        });

                        // Join all lines with newline for the cell
                        const itemsWithDosage = formattedLines.join('\n');
                        const ingredientsText = allIngredients.join('\n'); // Join ingredients with newline to match structure if possible

                        const timeUsageText = commonTime ? `${commonTime}\n${commonUsage}` : commonUsage;

                        tableData.push([
                            timeUsageText || '—',
                            itemsWithDosage,
                            groupOilClass || '—',
                            ingredientsText || '—'
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
                // Use the pre-processed and deduplicated list from the caller if available
                // prescription_scheduling.js already combines details + API + zero items into patient.therapy_items
                const allTherapyItems = patient.therapy_items && patient.therapy_items.length > 0
                    ? patient.therapy_items
                    : (patient.details?.therapy_items || []);

                const zeroTherapistTherapies = patient.zero_therapist_therapies || [];

                console.log('[PDF NEW] Patient:', name, 'Therapies:', allTherapyItems.length, 'Zero:', zeroTherapistTherapies.length);

                if (allTherapyItems.length > 0 || zeroTherapistTherapies.length > 0) {
                    const therapyTableData = [];

                    // Regular therapies
                    allTherapyItems.forEach((therapyItem, index) => {
                        const therapyName = therapyItem.therapy_name || 'Unknown Therapy';
                        const timeslot24 = therapyItem.timeslot || therapyItem.time || '—';
                        const timeslot = convertTo12Hour(timeslot24);

                        // Extract dates
                        let fromDate = '—';
                        let toDate = '—';
                        const rawFrom = therapyItem.from_date || therapyItem.from || '';
                        const rawTo = therapyItem.to_date || therapyItem.to || '';
                        if (rawFrom) fromDate = formatDateDDMMYYYY(rawFrom);
                        if (rawTo) toDate = formatDateDDMMYYYY(rawTo);

                        // Process items_groups to match items with their usage
                        // Each group has its own usage, so we need to create separate rows for each group
                        if (therapyItem.items && Array.isArray(therapyItem.items) && therapyItem.items.length > 0) {
                            // Check if items are actually groups (nested items) or flat items
                            const isNested = therapyItem.items[0] && therapyItem.items[0].items && Array.isArray(therapyItem.items[0].items);

                            if (isNested) {
                                // It's a list of groups - each group gets its own row
                                therapyItem.items.forEach((group, idx) => {
                                    const subItems = group.items || [];
                                    const itemNames = subItems.map(it => it.item_name || '').filter(Boolean).join(' + ');

                                    // Get usage for THIS group
                                    let groupUsage = group.usage || '';
                                    if (!groupUsage && group.usage_array && Array.isArray(group.usage_array)) {
                                        groupUsage = group.usage_array.filter(u => u).join(', ');
                                    }
                                    if (!groupUsage && therapyItem.usage) {
                                        groupUsage = therapyItem.usage;
                                    }
                                    if (!groupUsage && therapyItem.usage_array && Array.isArray(therapyItem.usage_array)) {
                                        groupUsage = therapyItem.usage_array.filter(u => u).join(', ');
                                    }
                                    if (!groupUsage) groupUsage = '—';

                                    // Get dosage for THIS group
                                    let dosage = group.dosage || group.dose || group.quantity || '';
                                    if (group.uno) dosage = dosage ? `${dosage} (${group.uno})` : group.uno;

                                    let itemsWithDosage = itemNames;
                                    if (dosage) itemsWithDosage += ` [${dosage}]`;
                                    if (!itemsWithDosage) itemsWithDosage = '—';

                                    // Get oil class for THIS group
                                    let oilClass = group.oil_class || group.oilClass || group.oil_class_name || '';
                                    if (!oilClass && therapyItem.oil_class) {
                                        oilClass = therapyItem.oil_class;
                                    }
                                    if (!oilClass) oilClass = '—';

                                    // Get ingredients for THIS group
                                    let ingredients = '—';
                                    if (group.ingredients) {
                                        if (Array.isArray(group.ingredients) && group.ingredients.length > 0) {
                                            // Check if it's an array of objects or strings
                                            if (typeof group.ingredients[0] === 'object' && group.ingredients[0] !== null) {
                                                // Array of objects
                                                ingredients = group.ingredients
                                                    .map(ing => {
                                                        if (typeof ing === 'string') return ing;
                                                        return ing.ingredient_name || ing.text || ing.name || '';
                                                    })
                                                    .filter(Boolean)
                                                    .join(', ');
                                            } else {
                                                // Array of strings
                                                ingredients = group.ingredients
                                                    .filter(ing => ing && String(ing).trim())
                                                    .map(ing => String(ing).trim())
                                                    .join(', ');
                                            }
                                        } else if (typeof group.ingredients === 'string') {
                                            // Single string
                                            ingredients = group.ingredients.trim();
                                        }
                                    }
                                    if (!ingredients || ingredients === '') ingredients = '—';

                                    // Create a separate row for this group
                                    // Only show therapy name, time, and dates on first row
                                    therapyTableData.push([
                                        idx === 0 ? therapyName : '',  // Therapy name only on first row
                                        groupUsage,                    // Usage for this group
                                        itemsWithDosage,               // Items with dosage for this group
                                        oilClass,                      // Oil class for this group
                                        idx === 0 ? timeslot : '',     // Time only on first row
                                        idx === 0 ? fromDate : '',     // From date only on first row
                                        idx === 0 ? toDate : ''        // To date only on first row
                                    ]);
                                });
                            } else {
                                // Flat list - treat as one group with single usage
                                const itemNames = therapyItem.items.map(it => it.item_name || '').filter(Boolean).join(' + ');

                                // Get usage
                                let usage = therapyItem.usage || '';
                                if (!usage && therapyItem.usage_array && Array.isArray(therapyItem.usage_array)) {
                                    usage = therapyItem.usage_array.filter(u => u).join(', ');
                                }
                                if (!usage) usage = '—';

                                // Get dosage
                                let dosage = therapyItem.dosage || therapyItem.dose || '';
                                if (therapyItem.uno) dosage = dosage ? `${dosage} (${therapyItem.uno})` : therapyItem.uno;

                                let itemsWithDosage = itemNames;
                                if (dosage) itemsWithDosage += ` [${dosage}]`;
                                if (!itemsWithDosage) itemsWithDosage = '—';

                                // Get oil class
                                let oilClass = therapyItem.oil_class || therapyItem.oilClass || '—';
                                if (!oilClass) oilClass = '—';

                                // Get ingredients
                                let ingredients = '—';
                                if (therapyItem.ingredients) {
                                    if (Array.isArray(therapyItem.ingredients) && therapyItem.ingredients.length > 0) {
                                        if (typeof therapyItem.ingredients[0] === 'object' && therapyItem.ingredients[0] !== null) {
                                            ingredients = therapyItem.ingredients
                                                .map(ing => {
                                                    if (typeof ing === 'string') return ing;
                                                    return ing.ingredient_name || ing.text || ing.name || '';
                                                })
                                                .filter(Boolean)
                                                .join(', ');
                                        } else {
                                            ingredients = therapyItem.ingredients
                                                .filter(ing => ing && String(ing).trim())
                                                .map(ing => String(ing).trim())
                                                .join(', ');
                                        }
                                    } else if (typeof therapyItem.ingredients === 'string') {
                                        ingredients = therapyItem.ingredients.trim();
                                    }
                                }
                                if (!ingredients || ingredients === '') ingredients = '—';

                                therapyTableData.push([therapyName, usage, itemsWithDosage, oilClass, timeslot, fromDate, toDate]);
                            }
                        } else {
                            // No items - fallback to therapy-level data
                            let usage = therapyItem.usage || '';
                            if (!usage && therapyItem.usage_array && Array.isArray(therapyItem.usage_array)) {
                                usage = therapyItem.usage_array.filter(u => u).join(', ');
                            }
                            if (!usage) usage = '—';

                            let itemsWithDosage = therapyItem.dosage || therapyItem.dose || '—';
                            let oilClass = therapyItem.oil_class || therapyItem.oilClass || '—';

                            therapyTableData.push([therapyName, usage, itemsWithDosage, oilClass, timeslot, fromDate, toDate]);
                        }
                    });

                    // Zero-therapist therapies
                    zeroTherapistTherapies.forEach(therapy => {
                        const therapyName = therapy.therapy_name || 'Unknown Therapy';
                        const timeslot24 = therapy.timeslot || '—';
                        const timeslot = convertTo12Hour(timeslot24);

                        // Extract dates
                        let fromDate = '—';
                        let toDate = '—';
                        const rawFrom = therapy.from_date || therapy.from || '';
                        const rawTo = therapy.to_date || therapy.to || '';
                        if (rawFrom) fromDate = formatDateDDMMYYYY(rawFrom);
                        if (rawTo) toDate = formatDateDDMMYYYY(rawTo);

                        // Process items_groups to match items with their usage
                        // Each group gets its own row
                        if (therapy.items_groups && Array.isArray(therapy.items_groups) && therapy.items_groups.length > 0) {
                            therapy.items_groups.forEach((group, idx) => {
                                const subItems = group.items || [];
                                const itemNames = subItems.map(it => it.item_name || '').filter(Boolean).join(' + ');

                                // Get usage for THIS group
                                let groupUsage = group.usage || '';
                                if (!groupUsage && group.usage_array && Array.isArray(group.usage_array)) {
                                    groupUsage = group.usage_array.filter(u => u).join(', ');
                                }
                                if (!groupUsage && therapy.usage) {
                                    groupUsage = therapy.usage;
                                }
                                if (!groupUsage && therapy.usage_array && Array.isArray(therapy.usage_array)) {
                                    groupUsage = therapy.usage_array.filter(u => u).join(', ');
                                }
                                if (!groupUsage) groupUsage = '—';

                                // Get dosage for THIS group
                                let dosage = group.dosage || group.dose || group.quantity || '';
                                if (group.uno) dosage = dosage ? `${dosage} (${group.uno})` : group.uno;

                                let itemsWithDosage = itemNames;
                                if (dosage) itemsWithDosage += ` [${dosage}]`;
                                if (!itemsWithDosage) itemsWithDosage = '—';

                                // Get oil class for THIS group
                                let oilClass = group.oil_class || group.oilClass || group.oil_class_name || '';
                                if (!oilClass && therapy.oil_class) {
                                    oilClass = therapy.oil_class;
                                }
                                if (!oilClass) oilClass = '—';

                                // Get ingredients for THIS group
                                let ingredients = '—';
                                if (group.ingredients) {
                                    if (Array.isArray(group.ingredients) && group.ingredients.length > 0) {
                                        // Check if it's an array of objects or strings
                                        if (typeof group.ingredients[0] === 'object' && group.ingredients[0] !== null) {
                                            // Array of objects
                                            ingredients = group.ingredients
                                                .map(ing => {
                                                    if (typeof ing === 'string') return ing;
                                                    return ing.ingredient_name || ing.text || ing.name || '';
                                                })
                                                .filter(Boolean)
                                                .join(', ');
                                        } else {
                                            // Array of strings
                                            ingredients = group.ingredients
                                                .filter(ing => ing && String(ing).trim())
                                                .map(ing => String(ing).trim())
                                                .join(', ');
                                        }
                                    } else if (typeof group.ingredients === 'string') {
                                        // Single string
                                        ingredients = group.ingredients.trim();
                                    }
                                }
                                if (!ingredients || ingredients === '') ingredients = '—';

                                // Create a separate row for this group
                                // Only show therapy name, time, and dates on first row
                                therapyTableData.push([
                                    idx === 0 ? therapyName : '',  // Therapy name only on first row
                                    groupUsage,                    // Usage for this group
                                    itemsWithDosage,               // Items with dosage for this group
                                    oilClass,                      // Oil class for this group
                                    idx === 0 ? timeslot : '',     // Time only on first row
                                    idx === 0 ? fromDate : '',     // From date only on first row
                                    idx === 0 ? toDate : ''        // To date only on first row
                                ]);
                            });
                        } else {
                            // No items_groups - fallback to therapy-level data
                            let usage = therapy.usage || '';
                            if (!usage && therapy.usage_array && Array.isArray(therapy.usage_array)) {
                                usage = therapy.usage_array.filter(u => u).join(', ');
                            }
                            if (!usage) usage = '—';

                            let itemsWithDosage = therapy.dosage || therapy.dose || '—';
                            let oilClass = therapy.oil_class || therapy.oilClass || '—';

                            therapyTableData.push([therapyName, usage, itemsWithDosage, oilClass, timeslot, fromDate, toDate]);
                        }
                    });

                    if (therapyTableData.length > 0) {
                        checkNewPage(30);

                        doc.autoTable({
                            startY: yPos,
                            head: [['Therapy', 'Usage', 'Items (Dosage)', 'Oil Class', 'Time', 'From', 'To']],
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
                                0: { cellWidth: 38 },   // Therapy
                                1: { cellWidth: 45 },   // Usage (widened to prevent awkward wrapping)
                                2: { cellWidth: 87 },   // Items (Dosage)
                                3: { cellWidth: 25 },   // Oil Class
                                4: { cellWidth: 18 },   // Time
                                5: { cellWidth: 21 },   // From
                                6: { cellWidth: 21 }    // To
                                // Total: 255mm (matches Prescription table width)
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
