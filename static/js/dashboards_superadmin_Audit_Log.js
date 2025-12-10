function exportLogs() {
      // Get current filter parameters
      const params = new URLSearchParams(window.location.search);
      const exportUrl = '{% url "authentication:Audit_Log" %}?' + params.toString() + '&export=1';
      window.open(exportUrl, '_blank');
    }

    function refreshLogs() {
      window.location.reload();
    }
    
    // Print Audit Log to PDF
    function printAuditLogToPDF() {
      // Check if jsPDF is loaded
      if (typeof window.jspdf === 'undefined') {
        alert('PDF library not loaded. Please refresh the page and try again.');
        console.error('jsPDF library not found');
        return;
      }
      
      // Show loading indicator
      const printBtn = document.querySelector('button[onclick="printAuditLogToPDF()"]');
      const originalText = printBtn ? printBtn.innerHTML : '';
      if (printBtn) {
        printBtn.disabled = true;
        printBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Generating PDF...';
      }
      
      // Get current filter parameters from URL
      const urlParams = new URLSearchParams(window.location.search);
      // Remove page parameter as we want all data
      urlParams.delete('page');
      
      // Build API URL
      const apiUrl = '{% url "authentication:audit_log_api" %}?' + urlParams.toString();
      
      // Fetch all audit logs from API
      fetch(apiUrl)
        .then(response => response.json())
        .then(data => {
          if (printBtn) {
            printBtn.disabled = false;
            printBtn.innerHTML = originalText;
          }
          
          if (!data.success || !data.data || data.data.length === 0) {
            alert('No audit logs found to generate PDF.');
            return;
          }
          
          // Generate PDF with all data
          generateAuditLogPDF(data.data, urlParams);
        })
        .catch(error => {
          if (printBtn) {
            printBtn.disabled = false;
            printBtn.innerHTML = originalText;
          }
          console.error('Error fetching audit logs:', error);
          alert('Error fetching audit logs: ' + error.message);
        });
    }
    
    function generateAuditLogPDF(logsData, urlParams) {
      try {
        const { jsPDF } = window.jspdf;
        const doc = new jsPDF('p', 'mm', 'a4');
        
        const pageWidth = doc.internal.pageSize.getWidth();
        const pageHeight = doc.internal.pageSize.getHeight();
        const margin = 15;
        let yPos = margin;
        
        // Get current date for title
        const today = new Date();
        const dateStr = today.toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' });
        
        // Get filter info
        const hasFilters = urlParams.toString() && urlParams.toString().length > 0;
        const filterInfo = hasFilters ? ' (Filtered)' : ' (Today\'s Logs)';
        
        // Header
        doc.setFillColor(59, 130, 246); // Blue
        doc.rect(0, 0, pageWidth, 25, 'F');
        doc.setTextColor(255, 255, 255);
        doc.setFontSize(18);
        doc.setFont(undefined, 'bold');
        doc.text('Audit Log Report', margin, 15);
        doc.setFontSize(10);
        doc.setFont(undefined, 'normal');
        doc.text(dateStr + filterInfo, margin, 22);
        doc.text(`Total Records: ${logsData.length}`, pageWidth - margin, 22, { align: 'right' });
        
        yPos = 35;
        
        // Prepare table data from API response
        const tableData = logsData.map(log => {
          // Combine description and additional_info if available
          let description = log.description || '';
          if (log.additional_info) {
            description += (description ? ' | ' : '') + log.additional_info;
          }
          // Limit description length
          if (description.length > 80) {
            description = description.substring(0, 77) + '...';
          }
          
          // Combine timestamp and time
          const timestamp = log.timestamp + ' ' + log.time;
          
          return [
            log.id.toString(),
            log.user + (log.user_role ? '\n(' + log.user_role + ')' : ''),
            log.action,
            description || '-',
            log.object || '-',
            timestamp,
            log.ip_address || '-',
            log.status
          ];
        });
        
        // Generate table
        doc.autoTable({
          head: [['ID', 'User', 'Action', 'Description', 'Object', 'Timestamp', 'IP Address', 'Status']],
          body: tableData,
          startY: yPos,
          margin: { left: margin, right: margin },
          styles: {
            fontSize: 7,
            cellPadding: 2,
            overflow: 'linebreak',
            cellWidth: 'wrap',
          },
          headStyles: {
            fillColor: [59, 130, 246], // Blue header
            textColor: 255,
            fontStyle: 'bold',
            fontSize: 8,
          },
          alternateRowStyles: {
            fillColor: [245, 247, 250], // Light gray alternate rows
          },
          columnStyles: {
            0: { cellWidth: 15 }, // ID
            1: { cellWidth: 30 }, // User
            2: { cellWidth: 25 }, // Action
            3: { cellWidth: 50 }, // Description
            4: { cellWidth: 30 }, // Object
            5: { cellWidth: 35 }, // Timestamp
            6: { cellWidth: 25 }, // IP Address
            7: { cellWidth: 20 }, // Status
          },
          didDrawPage: function(data) {
            // Footer
            const pageNum = data.pageNumber;
            const totalPages = doc.internal.getNumberOfPages();
            doc.setFontSize(8);
            doc.setTextColor(128, 128, 128);
            doc.text(
              `Page ${pageNum} of ${totalPages} | Generated on ${new Date().toLocaleString()}`,
              pageWidth / 2,
              pageHeight - 10,
              { align: 'center' }
            );
          },
        });
        
        // Save PDF
        const fileName = `Audit_Log_Report_${today.toISOString().split('T')[0]}.pdf`;
        doc.save(fileName);
      } catch (error) {
        console.error('Error generating PDF:', error);
        alert('Error generating PDF: ' + error.message + '\nPlease check the browser console for details.');
      }
    }

    // Auto-refresh every 30 seconds (only for today's view)
    setInterval(function() {
      // Only refresh if no filters are applied and user is on first page
      const urlParams = new URLSearchParams(window.location.search);
      if (urlParams.toString() === '' || urlParams.toString() === 'page=1') {
        window.location.reload();
      }
    }, 30000);