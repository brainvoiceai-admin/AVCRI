const loginForm = document.getElementById('loginForm');
    const mobileInput = document.getElementById('mobile');
    const passwordInput = document.getElementById('password');
    const messageContainer = document.getElementById('messageContainer');

    // Show validation message
    function showMessage(message, type = 'error') {
        messageContainer.innerHTML = `<div class="message ${type}">${message}</div>`;
        setTimeout(() => { messageContainer.innerHTML = ''; }, 3000);
    }

    // Validate mobile number (Indian format)
    function isValidMobile(mobile) {
        return /^[6-9]\d{9}$/.test(mobile);
    }

    // Allow only numbers in mobile input
    mobileInput.addEventListener('input', function() {
        this.value = this.value.replace(/[^0-9]/g, '').slice(0, 10);
    });

    // Form submit validation
    loginForm.addEventListener('submit', function(e) {
        const mobile = mobileInput.value.trim();
        const password = passwordInput.value.trim();

        if (!mobile || !password) {
            e.preventDefault();
            showMessage('Please enter both mobile number and password.');
            return;
        }

        if (!isValidMobile(mobile)) {
            e.preventDefault();
            showMessage('Enter a valid 10-digit mobile number starting with 6-9.');
            return;
        }

        if (password.length < 3) {
            e.preventDefault();
            showMessage('Password must be at least 6 characters long.');
            return;
        }

        // ✅ If validation passes, form submits normally to Django
    });