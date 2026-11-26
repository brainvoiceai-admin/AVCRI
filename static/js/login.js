const loginForm = document.getElementById('loginForm');
const userInput = document.getElementById('username') || document.getElementById('mobile');
const passwordInput = document.getElementById('password');
const messageContainer = document.getElementById('messageContainer');

// Show validation message
function showMessage(message, type = 'error') {
    if (!messageContainer) return;
    messageContainer.innerHTML = `<div class="message ${type}">${message}</div>`;
    setTimeout(() => { messageContainer.innerHTML = ''; }, 3000);
}

// Form submit validation
if (loginForm && userInput && passwordInput) {
    loginForm.addEventListener('submit', function(e) {
        const userVal = userInput.value.trim();
        const password = passwordInput.value.trim();

        if (!userVal || !password) {
            e.preventDefault();
            showMessage('Please enter both username and password.');
            return;
        }

        // If numeric only mobile was entered (legacy check)
        const mobileOnly = document.getElementById('mobile');
        if (mobileOnly && userInput === mobileOnly) {
            if (!/^[6-9]\d{9}$/.test(userVal)) {
                e.preventDefault();
                showMessage('Enter a valid 10-digit mobile number starting with 6-9.');
                return;
            }
        }
    });
}