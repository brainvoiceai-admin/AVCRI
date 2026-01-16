// Module Search Functionality
        document.getElementById('moduleSearch').addEventListener('input', function(e) {
            const searchTerm = e.target.value.toLowerCase();
            const moduleItems = document.querySelectorAll('.module-item');
            
            moduleItems.forEach(item => {
                const moduleName = item.getAttribute('data-module-name');
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
                const visibleItems = category.querySelectorAll('.module-item[style=""]').length;
                const totalItems = category.querySelectorAll('.module-item').length;
                const categoryCard = category.querySelector('.card');
                
                if (visibleItems === 0 && searchTerm !== '') {
                    categoryCard.style.display = 'none';
                } else {
                    categoryCard.style.display = '';
                }
            });
        });
        
        // Select All / Deselect All for all modules
        document.getElementById('selectAllBtn').addEventListener('click', function() {
            document.querySelectorAll('.module-checkbox').forEach(checkbox => {
                if (!checkbox.closest('.module-item').style.display || checkbox.closest('.module-item').style.display !== 'none') {
                    checkbox.checked = true;
                }
            });
        });
        
        document.getElementById('deselectAllBtn').addEventListener('click', function() {
            document.querySelectorAll('.module-checkbox').forEach(checkbox => {
                checkbox.checked = false;
            });
        });
        
        // Select All / Deselect All for category
        document.querySelectorAll('.select-category-all').forEach(btn => {
            btn.addEventListener('click', function() {
                const category = this.getAttribute('data-category');
                const categoryDiv = document.querySelector(`.module-category[data-category="${category}"]`);
                categoryDiv.querySelectorAll('.module-checkbox').forEach(checkbox => {
                    if (!checkbox.closest('.module-item').style.display || checkbox.closest('.module-item').style.display !== 'none') {
                        checkbox.checked = true;
                    }
                });
            });
        });
        
        document.querySelectorAll('.deselect-category-all').forEach(btn => {
            btn.addEventListener('click', function() {
                const category = this.getAttribute('data-category');
                const categoryDiv = document.querySelector(`.module-category[data-category="${category}"]`);
                categoryDiv.querySelectorAll('.module-checkbox').forEach(checkbox => {
                    checkbox.checked = false;
                });
            });
        });
        
        // Show toast on form submission success
        document.querySelector('form').addEventListener('submit', function(e) {
            // Let the form submit normally
            // The toast will be shown on the role_management page after redirect
        });
        
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