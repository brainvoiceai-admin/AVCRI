// Global functions for select all/deselect all (backup if inline doesn't work)
function selectAllModules() {
    var checkboxes = document.querySelectorAll('input[name="modules"][type="checkbox"]');
    for (var i = 0; i < checkboxes.length; i++) {
        var item = checkboxes[i].closest('.module-item');
        if (!item || item.offsetParent !== null) {
            checkboxes[i].checked = true;
        }
    }
}

function deselectAllModules() {
    var checkboxes = document.querySelectorAll('input[name="modules"][type="checkbox"]');
    for (var i = 0; i < checkboxes.length; i++) {
        checkboxes[i].checked = false;
    }
}

// Make functions globally accessible
window.selectAllModules = selectAllModules;
window.deselectAllModules = deselectAllModules;

// Wait for DOM to be ready
document.addEventListener('DOMContentLoaded', function() {
    // Module Search Functionality
    const moduleSearchInput = document.getElementById('moduleSearch');
    if (moduleSearchInput) {
        moduleSearchInput.addEventListener('input', function(e) {
            const searchTerm = e.target.value.toLowerCase();
            const moduleItems = document.querySelectorAll('.module-item');
            
            moduleItems.forEach(item => {
                const moduleName = item.getAttribute('data-module-name') || '';
                const moduleDesc = item.getAttribute('data-module-desc') || '';
                const matches = moduleName.includes(searchTerm) || moduleDesc.includes(searchTerm);
                
                if (matches) {
                    item.style.display = '';
                } else {
                    item.style.display = 'none';
                }
            });
            
            // Hide/show entire categories if all items are hidden
            document.querySelectorAll('.module-category').forEach(category => {
                const visibleItems = category.querySelectorAll('.module-item:not([style*="display: none"])').length;
                const totalItems = category.querySelectorAll('.module-item').length;
                const categoryCard = category.querySelector('.card');
                
                if (visibleItems === 0 && searchTerm !== '') {
                    if (categoryCard) categoryCard.style.display = 'none';
                } else {
                    if (categoryCard) categoryCard.style.display = '';
                }
            });
        });
    }
    
    // Attach event listeners to buttons
    const selectAllBtn = document.getElementById('selectAllBtn');
    console.log('Select All button found:', selectAllBtn);
    if (selectAllBtn) {
        selectAllBtn.onclick = function(e) {
            e.preventDefault();
            e.stopPropagation();
            selectAllModules();
            return false;
        };
    } else {
        console.error('Select All button not found!');
    }
    
    const deselectAllBtn = document.getElementById('deselectAllBtn');
    console.log('Deselect All button found:', deselectAllBtn);
    if (deselectAllBtn) {
        deselectAllBtn.onclick = function(e) {
            e.preventDefault();
            e.stopPropagation();
            deselectAllModules();
            return false;
        };
    } else {
        console.error('Deselect All button not found!');
    }
    
    // Select All / Deselect All for category
    const categorySelectBtns = document.querySelectorAll('.select-category-all');
    console.log('Category Select All buttons found:', categorySelectBtns.length);
    categorySelectBtns.forEach(btn => {
        btn.onclick = function(e) {
            e.preventDefault();
            e.stopPropagation();
            var category = this.getAttribute('data-category');
            console.log('Category Select All clicked for:', category);
            var categoryDiv = document.querySelector('.module-category[data-category="' + category + '"]');
            if (categoryDiv) {
                var checkboxes = categoryDiv.querySelectorAll('input[name="modules"][type="checkbox"]');
                console.log('Found checkboxes in category:', checkboxes.length);
                for (var i = 0; i < checkboxes.length; i++) {
                    var item = checkboxes[i].closest('.module-item');
                    if (!item || item.offsetParent !== null) {
                        checkboxes[i].checked = true;
                    }
                }
            }
            return false;
        };
    });
    
    const categoryDeselectBtns = document.querySelectorAll('.deselect-category-all');
    console.log('Category Deselect All buttons found:', categoryDeselectBtns.length);
    categoryDeselectBtns.forEach(btn => {
        btn.onclick = function(e) {
            e.preventDefault();
            e.stopPropagation();
            var category = this.getAttribute('data-category');
            console.log('Category Deselect All clicked for:', category);
            var categoryDiv = document.querySelector('.module-category[data-category="' + category + '"]');
            if (categoryDiv) {
                var checkboxes = categoryDiv.querySelectorAll('input[name="modules"][type="checkbox"]');
                console.log('Found checkboxes in category:', checkboxes.length);
                for (var i = 0; i < checkboxes.length; i++) {
                    checkboxes[i].checked = false;
                }
            }
            return false;
        };
    });
    
    // Show toast on form submission success
    const form = document.querySelector('form');
    if (form) {
        form.addEventListener('submit', function(e) {
            // Let the form submit normally
            // The toast will be shown on the role_management page after redirect
        });
    }
    
    // Check for success message in URL or messages
    const urlParams = new URLSearchParams(window.location.search);
    if (urlParams.get('created') === '1') {
        const toastElement = document.getElementById('successToast');
        if (toastElement) {
            const toast = new bootstrap.Toast(toastElement);
            toast.show();
        }
    }
    
    {% if messages %}
        {% for message in messages %}
            {% if message.tags == 'success' %}
                const toastElement = document.getElementById('successToast');
                if (toastElement) {
                    const toast = new bootstrap.Toast(toastElement);
                    toast.show();
                }
            {% endif %}
        {% endfor %}
    {% endif %}
});