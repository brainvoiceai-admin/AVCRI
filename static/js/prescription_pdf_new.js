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
        const doc = new jsPDF('p', 'mm', 'a4'); // Portrait
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
            if (yPos + requiredHeight > pageHeight - margin) {
                doc.addPage();
                yPos = margin;
                return true;
            }
            return false;
        }

        // Chronological Time Order Mapping (Minutes from midnight)
        const TIME_VALUE_MAP = {
            'M': 330,    // 5:30 AM
            'ABF': 480,  // 8:00 AM
            'BL': 660,   // 11:00 AM
            'AL': 750,   // 12:30 PM
            'E': 960,    // 4:00 PM
            'BD': 1110,  // 6:30 PM
            'AD': 1200,  // 8:00 PM
            'BT': 1320,  // 10:00 PM
            'NT': 1400   // Late night
        };

        function getTimeScore(text) {
            if (!text || text === '—') return 8000;
            const upperText = String(text).toUpperCase();

            // 1. ABSOLUTE OVERRIDE: External treatments (Body/Head) must be last
            // We check this first to ensure they beat any master order or times.
            if (upperText.includes('BODY')) return 9000;
            if (upperText.includes('HEAD')) return 9100;

            // 2. Master Order Ranking (Usage Order)
            const masterMap = window.PRESCRIPTION_TIME_ORDER_MAP || {};
            const words = upperText.split(/[\s,()/.-]+/);
            let bestMasterScore = 4999;
            let foundMasterMatch = false;
            
            for (const word of words) {
                if (word && masterMap[word] !== undefined) {
                    if (masterMap[word] < bestMasterScore) {
                        bestMasterScore = masterMap[word];
                        foundMasterMatch = true;
                    }
                }
            }
            if (foundMasterMatch) return bestMasterScore;

            // 3. Chronological Fallback (Minutes since midnight)
            const baseChronologicalScore = 1000;
            const timeMatches = upperText.match(/(\d{1,2})[:.](\d{2})\s*(AM|PM)?/gi);
            if (timeMatches && timeMatches.length > 0) {
                let minMinutes = 1440;
                timeMatches.forEach(tm => {
                    const cleanItem = tm.replace('.', ':');
                    const parts = cleanItem.split(':');
                    let h = parseInt(parts[0]);
                    const m = parseInt(parts[1]);
                    const isPM = tm.toUpperCase().includes('PM');
                    const isAM = tm.toUpperCase().includes('AM');
                    if (isPM && h < 12) h += 12;
                    if (isAM && h === 12) h = 0;
                    const minutes = (h * 60) + m;
                    if (minutes < minMinutes) minMinutes = minutes;
                });
                return baseChronologicalScore + minMinutes;
            }

            // 24h format Check
            const h24Match = upperText.match(/(\d{2}):(\d{2}):(\d{2})/);
            if (h24Match) return baseChronologicalScore + (parseInt(h24Match[1]) * 60) + parseInt(h24Match[2]);

            // Internal code fallback (M, E, etc.)
            for (const [key, value] of Object.entries(TIME_VALUE_MAP)) {
                if (upperText.split(/[\s,]+/).includes(key) || upperText.includes(key)) {
                    return baseChronologicalScore + value;
                }
            }

            return 8000;
        }

        // ========== HEADER ==========
        doc.setFontSize(12);
        doc.setFont(undefined, 'bold');
        doc.text('THE ARYA VAIDA CHIKITSALAYAM AND RESEARCH INSTITUTE', pageWidth / 2, yPos, { align: 'center' });
        yPos += 5;

        doc.setFontSize(10);
        const formattedDate = formatDateDDMMYYYY(date);
        doc.text(`PRESCRIPTIONS AS ON ${formattedDate}        PHYSICIAN / PHARMACY / RESEARCH`, pageWidth / 2, yPos, { align: 'center' });
        yPos += 6;

        doc.setDrawColor(0, 0, 0);
        doc.setLineWidth(0.5);
        doc.line(margin, yPos, pageWidth - margin, yPos);
        yPos += 5;

        // ========== TIME LEGEND ==========
        doc.setFontSize(8);
        doc.setFont(undefined, 'bold');
        doc.text('TIME LEGEND:', margin, yPos);
        yPos += 4;

        doc.setFontSize(8.5);
        doc.setFont(undefined, 'normal');
        // 3-column layout for better readability
        const legendRows = [
            ['M  (5.30–5.45)  – Morning', 'BL (11.00–12.30) – Before Lunch', 'AD (8.00–8.30)  – After Dinner'],
            ['E  (5.30–6.00)  – Evening', 'AL (12.30–1.30) – After Lunch', 'BT (8.30–9.00)  – Bed Time'],
            ['ABF (8.00–8.30) – After Breakfast', 'BD (6.30–7.00)  – Before Dinner', 'NT – A Pinch Now And Then']
        ];

        const col1X = margin + 2;
        const col2X = margin + 65;
        const col3X = margin + 130;

        legendRows.forEach((row, rowIdx) => {
            const rowY = yPos + (rowIdx * 3.5);
            doc.text(row[0], col1X, rowY);
            doc.text(row[1], col2X, rowY);
            doc.text(row[2], col3X, rowY);
        });

        yPos += 11;

        doc.line(margin, yPos, pageWidth - margin, yPos);
        yPos += 6;

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

        // STRICT HOSPITAL CHART ORDER CONFIGURATION 2026
        const CATEGORIES = [
            { title: 'DELUXE SUITE ROOMS', prefixes: ['DS'] },
            { title: 'NORMAL ROOMS', prefixes: ['NR'] },
            { title: 'COTTAGES', prefixes: ['CT'] },
            { title: 'GENERAL WARD MALE', prefixes: ['MG', 'MD', 'MW'] },
            { title: 'GENERAL WARD FEMALE', prefixes: ['FG', 'FD', 'FW'] },
            { title: 'CABINS', prefixes: ['CB', 'CN'] }
        ];

        const processedRooms = new Set();
        const availableRoomKeys = Object.keys(patientsByRoom);

        // Natural sort helper (for CB-1, CB-2, CB-10 order)
        const naturalSort = (a, b) => a.localeCompare(b, undefined, { numeric: true, sensitivity: 'base' });

        // 1. Process Main Categories by Prefix
        CATEGORIES.forEach(cat => {
            const catRooms = availableRoomKeys.filter(rk => {
                if (processedRooms.has(rk)) return false;
                const rkStr = String(rk).trim().toUpperCase();
                return cat.prefixes.some(p => rkStr.startsWith(p.trim().toUpperCase()));
            }).sort(naturalSort);

            if (catRooms.length > 0) {
                checkNewPage(20);
                doc.setFontSize(11);
                doc.setFont(undefined, 'bold');
                doc.text(cat.title, margin, yPos);
                yPos += 6;
                doc.setDrawColor(0, 0, 0);
                doc.setLineWidth(0.4);
                doc.line(margin, yPos - 3, pageWidth - margin, yPos - 3);

                catRooms.forEach(roomKey => {
                    processRoomPatients(roomKey);
                    processedRooms.add(roomKey);
                });
            }
        });

        // 2. Process OP / Outpatients
        const opRooms = availableRoomKeys.filter(rk => {
            if (processedRooms.has(rk)) return false;
            return String(rk).trim().toUpperCase().startsWith('OP');
        }).sort(naturalSort);

        if (opRooms.length > 0) {
            checkNewPage(20);
            doc.setFontSize(11);
            doc.setFont(undefined, 'bold');
            doc.text('OP PATIENTS', margin, yPos);
            yPos += 8;
            doc.line(margin, yPos - 3, pageWidth - margin, yPos - 3);

            opRooms.forEach(roomKey => {
                processRoomPatients(roomKey);
                processedRooms.add(roomKey);
            });
        }

        // 3. Process Any Remaining Rooms (N/A, orphans)
        const remainingRooms = availableRoomKeys.filter(rk => !processedRooms.has(rk)).sort(naturalSort);
        if (remainingRooms.length > 0) {
            checkNewPage(20);
            doc.setFontSize(11);
            doc.setFont(undefined, 'bold');
            doc.text('OTHER ROOMS', margin, yPos);
            yPos += 6;
            doc.line(margin, yPos - 3, pageWidth - margin, yPos - 3);

            remainingRooms.forEach(roomKey => {
                processRoomPatients(roomKey);
                processedRooms.add(roomKey);
            });
        }


        function processRoomPatients(roomKey) {
            const patients = patientsByRoom[roomKey];
            for (let patient of patients) {
                // Check if there are any printable (non-cancelled) items first
                const prescriptionGroups = patient.details?.prescription_groups || [];
                const therapyItems = patient.therapy_items || [];
                
                const activePrescriptions = prescriptionGroups.filter(g => !g.is_cancelled && !g.is_canceled);
                // Also check for therapy-specific cancellation flags
                const activeTherapies = therapyItems.filter(g => !g.booking_is_cancelled && !g.booking_is_canceled);
                
                if (activePrescriptions.length === 0 && activeTherapies.length === 0) {
                    console.log(`[PDF] Skipping patient ${patient.patient_name || patient.registration_no} - no active items.`);
                    continue; 
                }

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
                doc.setFontSize(10);
                doc.setFont(undefined, 'bold');

                // Column positions for professional alignment
                const col1 = margin;        
                const col2 = margin + 50;   
                const col3 = margin + 120;  

                // Line 1: Room and Name
                doc.text(`Room: ${roomNo}`, col1, yPos);
                doc.text(`Name: ${name}`, col2, yPos);
                yPos += 4.5;
                
                // Line 2: Gender, Age, DOA
                doc.text(`Gender: ${gender || 'N/A'}`, col1, yPos);
                doc.text(`Age: ${age || 'N/A'}`, col2, yPos);
                if (cleanDoa) {
                    doc.text(`DOA: ${cleanDoa}`, col3, yPos);
                }
                yPos += 4.5;

                // Line 3: Doctor and Team
                if (doctorName) {
                    doc.text(`Doctor: ${doctorName}`, col1, yPos);
                }
                if (doctorTeam && doctorTeam !== '—') {
                    doc.text(`Team: ${doctorTeam}`, col3, yPos);
                }
                yPos += 4.5;

                yPos += 1; // Minimal gap before table

                // ========== PRESCRIPTION TABLE WITH BORDERS ==========
                // Note: prescriptionGroups was already defined above for filtering

                if (prescriptionGroups.length > 0) {
                    // Group by allocation
                    const groupsByAllocation = {};
                    prescriptionGroups.forEach(group => {
                        if (group.is_cancelled || group.is_canceled) return;
                        let allocationId = 'unknown';
                        const groupMatch = group.group_id.match(/prescription_group_([^/_]+)_/);
                        if (groupMatch) {
                            allocationId = groupMatch[1];
                        } else {
                            const itemMatch = group.group_id.match(/prescription_item_([^/_]+)/);
                            if (itemMatch) {
                                allocationId = `item_${itemMatch[1]}`;
                            }
                        }
                        
                        // NEW: Include usage and time in the grouping key to ensure separate rows 
                        // for separate scheduled times/usages even from same allocation.
                        const usageKey = (group.usage || '').trim().toLowerCase();
                        const timeKey = (group.time || '').trim().toLowerCase();
                        const uniqueKey = `${allocationId}_${usageKey}_${timeKey}`;
                        
                        if (!groupsByAllocation[uniqueKey]) {
                            groupsByAllocation[uniqueKey] = [];
                        }
                        groupsByAllocation[uniqueKey].push(group);
                    });

                    // Prepare table data
                    const tableData = [];
                    Object.values(groupsByAllocation).forEach(allocationGroups => {
                        let commonUsage = '';
                        let commonTime = '';
                        let commonMedUsage = '';
                        // Try to find common usage/time/medication_usage from the first group that has them
                        for (const g of allocationGroups) {
                            if (g.usage) {
                                commonUsage = g.usage;
                            } else if (g.usage_array && Array.isArray(g.usage_array)) {
                                commonUsage = g.usage_array.join(', ');
                            }
                            if (g.time) commonTime = g.time;
                            if (g.medication_usage) commonMedUsage = g.medication_usage.trim();
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
                        const timeUsageWithInstruction = (commonMedUsage && commonMedUsage !== '—')
                            ? `${timeUsageText || '—'}\n(${commonMedUsage})`
                            : (timeUsageText || '—');

                        tableData.push([
                            timeUsageWithInstruction,
                            itemsWithDosage,
                            groupOilClass || '—',
                            ingredientsText || '—'
                        ]);
                    });

                    // CHRONOLOGICAL SORTING FOR MEDICINE ROWS
                    tableData.sort((a, b) => {
                        const scoreA = getTimeScore(a[0]);
                        const scoreB = getTimeScore(b[0]);
                        return scoreA - scoreB;
                    });

                    // Draw prescription table using autoTable
                    doc.autoTable({
                        startY: yPos,
                        head: [['Time / Usage', 'Items', 'Oil Class', 'Ingredients']],
                        body: tableData,
                        theme: 'grid',
                        styles: {
                            fontSize: 9,
                            cellPadding: 2,
                            lineColor: [0, 0, 0],
                            lineWidth: 0.1,
                            valign: 'middle'
                        },
                        headStyles: {
                            fillColor: [240, 240, 240],
                            textColor: [0, 0, 0],
                            fontStyle: 'bold',
                            halign: 'left'
                        },
                        columnStyles: {
                            0: { cellWidth: 28.5 }, // Time/Usage
                            1: { cellWidth: 104.5 }, // Items
                            2: { cellWidth: 28.5 }, // Oil Class
                            3: { cellWidth: 28.5 }  // Ingredients
                        },
                        margin: { left: margin, right: margin },
                        tableWidth: 'auto'
                    });

                    yPos = doc.lastAutoTable.finalY + 2.5;
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
                        if (therapyItem.booking_is_cancelled || therapyItem.is_cancelled || therapyItem.is_canceled) return;
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

                                    // Get medication_usage for THIS group
                                    const groupMedUsage = (group.medication_usage || '').trim() || '—';

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
                                    const groupUsageWithInstruction = (groupMedUsage && groupMedUsage !== '—')
                                        ? `${groupUsage}\n(${groupMedUsage})`
                                        : groupUsage;
                                    therapyTableData.push([
                                        idx === 0 ? therapyName : '',  // Therapy name only on first row
                                        groupUsageWithInstruction,     // Usage (+ instruction) for this group
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

                                // Get medication_usage
                                const flatMedUsage = (therapyItem.medication_usage || '').trim() || '—';

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

                                const flatUsageWithInstruction = (flatMedUsage && flatMedUsage !== '—')
                                    ? `${usage}\n(${flatMedUsage})`
                                    : usage;
                                therapyTableData.push([therapyName, flatUsageWithInstruction, itemsWithDosage, oilClass, timeslot, fromDate, toDate]);
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
                        if (therapy.is_cancelled || therapy.is_canceled) return;
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

                                // Get medication_usage for THIS group
                                const zeroGroupMedUsage = (group.medication_usage || '').trim() || '—';

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
                                const zeroGroupUsageWithInstruction = (zeroGroupMedUsage && zeroGroupMedUsage !== '—')
                                    ? `${groupUsage}\n(${zeroGroupMedUsage})`
                                    : groupUsage;
                                therapyTableData.push([
                                    idx === 0 ? therapyName : '',  // Therapy name only on first row
                                    zeroGroupUsageWithInstruction, // Usage (+ instruction) for this group
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

                    // CHRONOLOGICAL SORTING FOR THERAPY ROWS
                    therapyTableData.sort((a, b) => {
                        // For therapy, usage is in index 1, therapy name in 0
                        // Prefer sorting by usage if it contains M, BL, etc.
                        let scoreA = getTimeScore(a[1]);
                        let scoreB = getTimeScore(b[1]);
                        
                        // Fallback to timeslot (index 4) if usage doesn't have codes
                        if (scoreA === 999 && a[4] && a[4] !== '—') {
                            // Extract hour for simple numeric sort
                            const hA = parseInt(a[4].split(':')[0]);
                            const isPM_A = a[4].includes('PM');
                            scoreA = (hA % 12 + (isPM_A ? 12 : 0)) * 100;
                        }
                        if (scoreB === 999 && b[4] && b[4] !== '—') {
                            const hB = parseInt(b[4].split(':')[0]);
                            const isPM_B = b[4].includes('PM');
                            scoreB = (hB % 12 + (isPM_B ? 12 : 0)) * 100;
                        }

                        return scoreA - scoreB;
                    });

                    if (therapyTableData.length > 0) {
                        checkNewPage(30);

                        doc.autoTable({
                            startY: yPos,
                            head: [['Therapy', 'Usage', 'Items (Dosage)', 'Oil Class', 'Time', 'From', 'To']],
                            body: therapyTableData,
                            theme: 'grid',
                            styles: {
                                fontSize: 8.5,
                                cellPadding: 1.5,
                                lineColor: [0, 0, 0],
                                lineWidth: 0.1,
                                valign: 'middle'
                            },
                            headStyles: {
                                fillColor: [76, 175, 80],
                                textColor: [255, 255, 255],
                                fontStyle: 'bold',
                                halign: 'left'
                            },
                            columnStyles: {
                                0: { cellWidth: 32 },   // Therapy
                                1: { cellWidth: 32 },   // Usage
                                2: { cellWidth: 46 },   // Items
                                3: { cellWidth: 20 },   // Oil Class
                                4: { cellWidth: 20, halign: 'center' }, // Time
                                5: { cellWidth: 20, halign: 'center' }, // From
                                6: { cellWidth: 20, halign: 'center' }  // To
                            },
                            didParseCell: function(data) {
                                if (data.section === 'head' && (data.column.index >= 4)) {
                                    data.cell.styles.halign = 'center';
                                }
                            },
                            didDrawPage: function (data) {
                                // Reset font size after table drawing if needed
                                doc.setFontSize(10);
                            },
                            margin: { left: margin, right: margin },
                            tableWidth: 190
                        });
                        yPos = doc.lastAutoTable.finalY + 2.5;
                    }
                }

                // Separator between patients
                yPos += 1;
                doc.setDrawColor(200, 200, 200);
                doc.setLineWidth(0.3);
                doc.line(margin, yPos, pageWidth - margin, yPos);
                yPos += 3;
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
