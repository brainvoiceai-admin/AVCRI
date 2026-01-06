document.addEventListener('DOMContentLoaded', function() {
            const urlParams = new URLSearchParams(window.location.search);
            const toastElement = document.getElementById('successToast');
            const toastMessage = document.getElementById('toastMessage');
            
            if (toastElement && toastMessage) {
                let shouldShowToast = false;
                
                // Check for success messages first (most reliable)
                {% if messages %}
                    {% for message in messages %}
                        {% if message.tags == 'success' %}
                            toastMessage.textContent = '{{ message|escapejs }}';
                            shouldShowToast = true;
                        {% endif %}
                    {% endfor %}
                {% endif %}
                
                // If no message but URL parameter exists, use default message
                if (!shouldShowToast) {
                    if (urlParams.get('updated') === '1') {
                        toastMessage.textContent = 'Role updated successfully';
                        shouldShowToast = true;
                    } else if (urlParams.get('created') === '1') {
                        toastMessage.textContent = 'Role created successfully';
                        shouldShowToast = true;
                    }
                }
                
                // Show toast if we have a message
                if (shouldShowToast) {
                    const toast = new bootstrap.Toast(toastElement);
                    toast.show();
                }
            }
        });