/**
 * Error Templates JavaScript
 * Provides interactive features and animations for error pages
 */

(function() {
    'use strict';

    // Initialize when DOM is ready
    document.addEventListener('DOMContentLoaded', function() {
        initErrorPage();
        initAnimations();
        initAutoRedirect();
    });

    /**
     * Initialize error page features
     */
    function initErrorPage() {
        // Add smooth scroll behavior
        document.documentElement.style.scrollBehavior = 'smooth';

        // Add ripple effect to buttons
        const buttons = document.querySelectorAll('.btn');
        buttons.forEach(button => {
            button.addEventListener('click', function(e) {
                createRipple(e, this);
            });
        });

        // Add typing effect to error message if needed
        const errorMessage = document.querySelector('.error-message');
        if (errorMessage && errorMessage.dataset.animate === 'true') {
            typeWriter(errorMessage, errorMessage.textContent);
        }
    }

    /**
     * Initialize animations
     */
    function initAnimations() {
        // Animate error code on load
        const errorCode = document.querySelector('.error-code');
        if (errorCode) {
            animateNumber(errorCode);
        }

        // Add stagger animation to error details items
        const errorDetailsItems = document.querySelectorAll('.error-details li');
        errorDetailsItems.forEach((item, index) => {
            item.style.opacity = '0';
            item.style.transform = 'translateX(-20px)';
            setTimeout(() => {
                item.style.transition = 'all 0.5s ease';
                item.style.opacity = '1';
                item.style.transform = 'translateX(0)';
            }, index * 100);
        });
    }

    /**
     * Animate number counting effect
     */
    function animateNumber(element) {
        const target = parseInt(element.textContent);
        const duration = 1000;
        const increment = target / (duration / 16);
        let current = 0;

        const timer = setInterval(() => {
            current += increment;
            if (current >= target) {
                element.textContent = target;
                clearInterval(timer);
            } else {
                element.textContent = Math.floor(current);
            }
        }, 16);
    }

    /**
     * Create ripple effect on button click
     */
    function createRipple(event, element) {
        const ripple = document.createElement('span');
        const rect = element.getBoundingClientRect();
        const size = Math.max(rect.width, rect.height);
        const x = event.clientX - rect.left - size / 2;
        const y = event.clientY - rect.top - size / 2;

        ripple.style.width = ripple.style.height = size + 'px';
        ripple.style.left = x + 'px';
        ripple.style.top = y + 'px';
        ripple.classList.add('ripple');

        const existingRipple = element.querySelector('.ripple');
        if (existingRipple) {
            existingRipple.remove();
        }

        element.appendChild(ripple);

        setTimeout(() => {
            ripple.remove();
        }, 600);
    }

    /**
     * Typewriter effect for error messages
     */
    function typeWriter(element, text) {
        element.textContent = '';
        let i = 0;
        const speed = 50;

        function type() {
            if (i < text.length) {
                element.textContent += text.charAt(i);
                i++;
                setTimeout(type, speed);
            }
        }

        type();
    }

    /**
     * Initialize auto-redirect if configured
     */
    function initAutoRedirect() {
        const autoRedirect = document.querySelector('[data-auto-redirect]');
        if (autoRedirect) {
            const seconds = parseInt(autoRedirect.dataset.autoRedirect);
            const countdownElement = document.querySelector('.countdown');
            
            if (countdownElement && seconds > 0) {
                let remaining = seconds;
                countdownElement.textContent = remaining;

                const countdown = setInterval(() => {
                    remaining--;
                    if (countdownElement) {
                        countdownElement.textContent = remaining;
                    }
                    if (remaining <= 0) {
                        clearInterval(countdown);
                        const redirectUrl = autoRedirect.dataset.redirectUrl || '/';
                        window.location.href = redirectUrl;
                    }
                }, 1000);
            }
        }
    }

    /**
     * Add loading state to buttons
     */
    function setButtonLoading(button, isLoading) {
        if (isLoading) {
            button.disabled = true;
            button.dataset.originalText = button.textContent;
            button.innerHTML = '<span class="loading-dots"><span></span><span></span><span></span></span>';
        } else {
            button.disabled = false;
            button.textContent = button.dataset.originalText || button.textContent;
        }
    }

    /**
     * Show error details toggle
     */
    function toggleErrorDetails() {
        const details = document.querySelector('.error-details');
        if (details) {
            details.style.display = details.style.display === 'none' ? 'block' : 'none';
        }
    }

    /**
     * Copy error information to clipboard
     */
    function copyErrorInfo() {
        const errorCode = document.querySelector('.error-code')?.textContent || '';
        const errorTitle = document.querySelector('.error-title')?.textContent || '';
        const errorMessage = document.querySelector('.error-message')?.textContent || '';
        const url = window.location.href;

        const errorInfo = `Error Code: ${errorCode}\nError: ${errorTitle}\nMessage: ${errorMessage}\nURL: ${url}`;

        if (navigator.clipboard) {
            navigator.clipboard.writeText(errorInfo).then(() => {
                showNotification('Error information copied to clipboard!');
            }).catch(() => {
                showNotification('Failed to copy error information', 'error');
            });
        } else {
            // Fallback for older browsers
            const textArea = document.createElement('textarea');
            textArea.value = errorInfo;
            document.body.appendChild(textArea);
            textArea.select();
            try {
                document.execCommand('copy');
                showNotification('Error information copied to clipboard!');
            } catch (err) {
                showNotification('Failed to copy error information', 'error');
            }
            document.body.removeChild(textArea);
        }
    }

    /**
     * Show notification
     */
    function showNotification(message, type = 'success') {
        const notification = document.createElement('div');
        notification.className = `notification notification-${type}`;
        notification.textContent = message;
        notification.style.cssText = `
            position: fixed;
            top: 20px;
            right: 20px;
            padding: 15px 25px;
            background: ${type === 'success' ? '#2d8659' : '#d32f2f'};
            color: white;
            border-radius: 8px;
            box-shadow: 0 4px 15px rgba(0,0,0,0.2);
            z-index: 10000;
            animation: slideInRight 0.3s ease-out;
        `;

        document.body.appendChild(notification);

        setTimeout(() => {
            notification.style.animation = 'slideOutRight 0.3s ease-out';
            setTimeout(() => {
                document.body.removeChild(notification);
            }, 300);
        }, 3000);
    }

    // Add CSS animations dynamically
    const style = document.createElement('style');
    style.textContent = `
        @keyframes slideInRight {
            from {
                transform: translateX(100%);
                opacity: 0;
            }
            to {
                transform: translateX(0);
                opacity: 1;
            }
        }
        @keyframes slideOutRight {
            from {
                transform: translateX(0);
                opacity: 1;
            }
            to {
                transform: translateX(100%);
                opacity: 0;
            }
        }
        .ripple {
            position: absolute;
            border-radius: 50%;
            background: rgba(255, 255, 255, 0.6);
            transform: scale(0);
            animation: ripple-animation 0.6s ease-out;
            pointer-events: none;
        }
        @keyframes ripple-animation {
            to {
                transform: scale(4);
                opacity: 0;
            }
        }
    `;
    document.head.appendChild(style);

    // Export functions for global use
    window.ErrorPageUtils = {
        toggleErrorDetails,
        copyErrorInfo,
        setButtonLoading,
        showNotification
    };
})();

