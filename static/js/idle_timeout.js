// Global idle timeout handling for authenticated dashboard pages
// - Shows a warning popup after 28 minutes of no user activity
// - Automatically logs the user out after 30 minutes of inactivity
// - Any activity resets the timers and hides the warning

(function () {
    // TEST CONFIG: 1-minute warning, 3-minute auto logout
    // For production, restore to 28 / 30 minutes.
    const WARNING_MINUTES = 28; // show popup at 1 minute
    const LOGOUT_MINUTES = 30;  // hard logout at 3 minutes

    const WARNING_TIMEOUT = WARNING_MINUTES * 60 * 1000;
    const LOGOUT_TIMEOUT = LOGOUT_MINUTES * 60 * 1000;

    // If you ever change the logout URL in Django, update this as well.
    const LOGOUT_URL = "/authentication/logout/";

    let warningTimer = null;
    let logoutTimer = null;
    let warningVisible = false;

    function clearTimers() {
        if (warningTimer) {
            clearTimeout(warningTimer);
            warningTimer = null;
        }
        if (logoutTimer) {
            clearTimeout(logoutTimer);
            logoutTimer = null;
        }
    }

    function createWarningModal() {
        if (document.getElementById("idle-timeout-overlay")) {
            return;
        }

        const overlay = document.createElement("div");
        overlay.id = "idle-timeout-overlay";
        overlay.style.position = "fixed";
        overlay.style.top = "0";
        overlay.style.left = "0";
        overlay.style.width = "100%";
        overlay.style.height = "100%";
        overlay.style.backgroundColor = "rgba(0, 0, 0, 0.45)";
        overlay.style.display = "none";
        overlay.style.alignItems = "center";
        overlay.style.justifyContent = "center";
        overlay.style.zIndex = "9999";

        const modal = document.createElement("div");
        modal.style.backgroundColor = "#fff";
        modal.style.borderRadius = "12px";
        modal.style.padding = "24px";
        modal.style.maxWidth = "420px";
        modal.style.width = "90%";
        modal.style.boxShadow = "0 12px 24px rgba(0,0,0,0.15)";
        modal.style.fontFamily = "system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";

        const title = document.createElement("h2");
        title.textContent = "You’re about to be logged out";
        title.style.margin = "0 0 8px 0";
        title.style.fontSize = "20px";
        title.style.color = "#222";

        const message = document.createElement("p");
        message.textContent = "You’ve been inactive for a while. For security, you will be logged out in 2 minutes unless you choose to stay signed in.";
        message.style.margin = "0 0 16px 0";
        message.style.fontSize = "14px";
        message.style.color = "#555";
        message.style.lineHeight = "1.4";

        const buttonRow = document.createElement("div");
        buttonRow.style.display = "flex";
        buttonRow.style.justifyContent = "flex-end";
        buttonRow.style.gap = "8px";
        buttonRow.style.marginTop = "8px";

        const stayButton = document.createElement("button");
        stayButton.type = "button";
        stayButton.textContent = "Stay Logged In";
        stayButton.style.padding = "8px 16px";
        stayButton.style.borderRadius = "8px";
        stayButton.style.border = "none";
        stayButton.style.backgroundColor = "#2ed573";
        stayButton.style.color = "#fff";
        stayButton.style.cursor = "pointer";
        stayButton.style.fontSize = "14px";
        stayButton.style.fontWeight = "600";

        const logoutButton = document.createElement("button");
        logoutButton.type = "button";
        logoutButton.textContent = "Log Out Now";
        logoutButton.style.padding = "8px 16px";
        logoutButton.style.borderRadius = "8px";
        logoutButton.style.border = "1px solid #ccc";
        logoutButton.style.backgroundColor = "#fff";
        logoutButton.style.color = "#333";
        logoutButton.style.cursor = "pointer";
        logoutButton.style.fontSize = "14px";

        stayButton.addEventListener("click", function () {
            hideWarning();
            resetIdleTimers();
        });

        logoutButton.addEventListener("click", function () {
            performLogout();
        });

        buttonRow.appendChild(logoutButton);
        buttonRow.appendChild(stayButton);

        modal.appendChild(title);
        modal.appendChild(message);
        modal.appendChild(buttonRow);

        overlay.appendChild(modal);
        document.body.appendChild(overlay);
    }

    function showWarning() {
        createWarningModal();
        const overlay = document.getElementById("idle-timeout-overlay");
        if (!overlay) return;
        overlay.style.display = "flex";
        warningVisible = true;
    }

    function hideWarning() {
        const overlay = document.getElementById("idle-timeout-overlay");
        if (!overlay) return;
        overlay.style.display = "none";
        warningVisible = false;
    }

    function performLogout() {
        // Best-effort cleanup; redirect will perform real logout on server
        clearTimers();
        hideWarning();
        window.location.href = LOGOUT_URL;
    }

    function resetIdleTimers() {
        // Don’t run on the public login page, only on authenticated dashboards.
        // We loosely detect this by checking for the sidebar element.
        if (!document.getElementById("sidebar")) {
            clearTimers();
            hideWarning();
            return;
        }

        clearTimers();
        hideWarning();

        warningTimer = setTimeout(function () {
            showWarning();
        }, WARNING_TIMEOUT);

        logoutTimer = setTimeout(function () {
            performLogout();
        }, LOGOUT_TIMEOUT);
    }

    function handleActivity() {
        // Ignore activity if the document is not visible to avoid constant resets in background tabs
        if (document.hidden) {
            return;
        }
        resetIdleTimers();
    }

    function initIdleTimeout() {
        // Guard against running before DOM is ready
        if (!document.body) {
            return;
        }

        // Attach listeners for common user interactions
        const events = ["mousemove", "mousedown", "keydown", "scroll", "touchstart"];
        events.forEach(function (evt) {
            window.addEventListener(evt, handleActivity, { passive: true });
        });

        document.addEventListener("visibilitychange", function () {
            // When the user returns to the tab, immediately reset timers
            if (!document.hidden) {
                handleActivity();
            }
        });

        // Start timers initially
        resetIdleTimers();
    }

    if (document.readyState === "complete" || document.readyState === "interactive") {
        initIdleTimeout();
    } else {
        document.addEventListener("DOMContentLoaded", initIdleTimeout);
    }
})();

