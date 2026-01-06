// Prevent modal from auto-closing and keep instructions visible
    (function() {
        // Override the auto-dismiss functionality BEFORE it runs
        const originalQuerySelectorAll = document.querySelectorAll;
        document.querySelectorAll = function(selector) {
            const elements = originalQuerySelectorAll.call(document, selector);
            if (selector === '.alert') {
                // Filter out alerts inside modals or with data-no-auto-dismiss
                return Array.from(elements).filter(function(el) {
                    const modal = el.closest('.modal');
                    const noAutoDismiss = el.hasAttribute('data-no-auto-dismiss');
                    return !modal && !noAutoDismiss;
                });
            }
            return elements;
        };
        
        // Also override Bootstrap Alert close for our instructions
        const originalBootstrapAlert = window.bootstrap ? bootstrap.Alert : null;
        if (originalBootstrapAlert) {
            const OriginalAlert = originalBootstrapAlert;
            bootstrap.Alert = function(element) {
                const instance = new OriginalAlert(element);
                const originalClose = instance.close;
                instance.close = function() {
                    // Don't close if it's the instructions alert
                    if (element && element.id === 'instructionsAlert') {
                        return;
                    }
                    return originalClose.call(this);
                };
                return instance;
            };
        }
    })();
    
    document.addEventListener('DOMContentLoaded', function() {
        const modal = document.getElementById('bulkUploadModal');
        if (modal) {
            // Prevent modal from closing when there are errors
            modal.addEventListener('hide.bs.modal', function(event) {
                const resultDiv = document.getElementById('uploadResult');
                if (resultDiv && resultDiv.innerHTML.includes('alert-danger')) {
                    // If there's an error, prevent closing
                    event.preventDefault();
                    event.stopPropagation();
                    return false;
                }
            });
            
            // Keep instructions visible - ensure it never gets hidden
            const instructionsAlert = document.getElementById('instructionsAlert');
            if (instructionsAlert) {
                // Make sure it's always visible
                instructionsAlert.style.display = 'block';
                instructionsAlert.style.visibility = 'visible';
                
                // Prevent Bootstrap Alert from closing it
                instructionsAlert.addEventListener('close.bs.alert', function(e) {
                    e.preventDefault();
                    e.stopPropagation();
                    return false;
                });
                
                // Monitor for any changes that might hide it
                const observer = new MutationObserver(function(mutations) {
                    mutations.forEach(function(mutation) {
                        if (mutation.type === 'attributes') {
                            if (mutation.attributeName === 'style') {
                                const display = instructionsAlert.style.display;
                                if (display === 'none' || display === '') {
                                    instructionsAlert.style.display = 'block';
                                }
                            }
                            if (mutation.attributeName === 'class') {
                                // If alert-dismissible or fade classes are added, remove them
                                if (instructionsAlert.classList.contains('alert-dismissible') || 
                                    instructionsAlert.classList.contains('fade')) {
                                    instructionsAlert.classList.remove('alert-dismissible', 'fade');
                                }
                            }
                        }
                    });
                });
                
                observer.observe(instructionsAlert, {
                    attributes: true,
                    attributeFilter: ['style', 'class'],
                    childList: false,
                    subtree: false
                });
                
                // Also protect against setTimeout-based dismissals
                const checkInterval = setInterval(function() {
                    if (instructionsAlert.style.display === 'none' || 
                        instructionsAlert.style.visibility === 'hidden' ||
                        instructionsAlert.style.opacity === '0') {
                        instructionsAlert.style.display = 'block';
                        instructionsAlert.style.visibility = 'visible';
                        instructionsAlert.style.opacity = '1';
                    }
                }, 100);
                
                // Clean up interval when modal is closed
                modal.addEventListener('hidden.bs.modal', function() {
                    clearInterval(checkInterval);
                });
            }
        }
    });
    
    // Make function globally accessible
    window.submitBulkUpload = function submitBulkUpload() {
        const form = document.getElementById('bulkUploadForm');
        if (!form) {
            console.error('Bulk upload form not found');
            return;
        }
        
        const formData = new FormData(form);
        const progressDiv = document.getElementById('uploadProgress');
        const resultDiv = document.getElementById('uploadResult');
        const submitBtn = document.getElementById('uploadBtn');
        const closeBtn = document.getElementById('closeModalBtn');
        
        // Get upload URL from form data attribute
        const uploadUrl = form.getAttribute('data-upload-url');
        if (!uploadUrl) {
            console.error('Upload URL not found. Using fallback URL.');
            resultDiv.innerHTML = '<div class="alert alert-danger">Configuration error: Upload URL not set. Please refresh the page.</div>';
            return;
        }
        
        // Reset
        resultDiv.innerHTML = '';
        progressDiv.style.display = 'block';
        submitBtn.disabled = true;
        closeBtn.disabled = true;
        
        // Scroll to result area
        resultDiv.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        
        fetch(uploadUrl, {
            method: 'POST',
            body: formData,
            headers: {
                'X-CSRFToken': formData.get('csrfmiddlewaretoken')
            }
        })
        .then(response => response.json())
        .then(data => {
            progressDiv.style.display = 'none';
            submitBtn.disabled = false;
            closeBtn.disabled = false;
            
            if (data.success) {
                resultDiv.innerHTML = `
                    <div class="alert alert-success alert-dismissible fade show" role="alert">
                        <strong>Success!</strong> ${data.message}
                        <ul class="mb-0 mt-2">
                            <li>Created: ${data.created}</li>
                            <li>Updated: ${data.updated}</li>
                            ${data.errors > 0 ? `<li class="text-warning">Errors: ${data.errors}</li>` : ''}
                        </ul>
                        ${data.error_details && data.error_details.length > 0 ? `
                            <details class="mt-2">
                                <summary class="text-warning">Error Details (first 10)</summary>
                                <ul class="mb-0 mt-2">
                                    ${data.error_details.map(e => `<li class="text-danger">${e}</li>`).join('')}
                                </ul>
                            </details>
                        ` : ''}
                        <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
                    </div>
                `;
                // Reload page after 3 seconds if successful and no errors
                if (data.errors === 0) {
                    setTimeout(() => {
                        window.location.reload();
                    }, 3000);
                }
            } else {
                resultDiv.innerHTML = `
                    <div class="alert alert-danger alert-dismissible fade show" role="alert">
                        <strong>Error!</strong> ${data.error || 'Unknown error occurred'}
                        ${data.traceback ? `
                            <details class="mt-2">
                                <summary>Technical Details</summary>
                                <pre class="mt-2 small">${data.traceback}</pre>
                            </details>
                        ` : ''}
                        <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
                    </div>
                `;
                // Scroll to error message
                resultDiv.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
            }
        })
        .catch(error => {
            progressDiv.style.display = 'none';
            submitBtn.disabled = false;
            closeBtn.disabled = false;
            resultDiv.innerHTML = `
                <div class="alert alert-danger alert-dismissible fade show" role="alert">
                    <strong>Error!</strong> ${error.message || 'Failed to upload file'}
                    <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
                </div>
            `;
            // Scroll to error message
            resultDiv.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        });
    };
    
    // Ensure function is available when modal is shown (backup for dynamically loaded modals)
    document.addEventListener('DOMContentLoaded', function() {
        // Re-attach onclick handler when modal is shown (in case it was cleared)
        const modal = document.getElementById('bulkUploadModal');
        if (modal) {
            modal.addEventListener('shown.bs.modal', function() {
                const uploadBtn = document.getElementById('uploadBtn');
                if (uploadBtn && !uploadBtn.onclick) {
                    uploadBtn.onclick = window.submitBulkUpload;
                }
            });
        }
    });