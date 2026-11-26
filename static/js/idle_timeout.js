// Global idle timeout handling for authenticated dashboard pages
// - Synchronizes user activity with Django server session (pings keep-alive every 5 mins during active use)
// - Synchronizes activity across multiple tabs via localStorage
// - Shows a warning popup after 28 minutes of inactivity
// - Automatically logs the user out after 30 minutes of inactivity
// - Clicking "Stay Logged In" pings server and renews the 30-minute session

(function () {
    const WARNING_MINUTES = 28;
    const LOGOUT_MINUTES = 30;
    const PING_INTERVAL_MS = 5 * 60 * 1000; // 5 minutes

    const WARNING_TIMEOUT = WARNING_MINUTES * 60 * 1000;
    const LOGOUT_TIMEOUT = LOGOUT_MINUTES * 60 * 1000;

    const LOGOUT_URL = "/authentication/logout/";
    const PING_URL = "/authentication/session-ping/";
    const STORAGE_KEY = "avcri_last_active_time";

    let warningTimer = null;
    let logoutTimer = null;
    let warningVisible = false;
    let lastPingTime = Date.now();

    function getLastActiveTime() {
        try {
            const val = localStorage.getItem(STORAGE_KEY);
            if (val) {
                const parsed = parseInt(val, 10);
                if (!isNaN(parsed) && parsed > 0) {
                    return parsed;
                }
            }
        } catch (e) {
            // LocalStorage might be disabled or restricted
        }
        return Date.now();
    }

    function setLastActiveTime(timestamp) {
        try {
            localStorage.setItem(STORAGE_KEY, timestamp.toString());
        } catch (e) {
            // Ignore storage errors
        }
    }

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

    function pingServer(onSuccess) {
        fetch(PING_URL, {
            method: "GET",
            headers: {
                "X-Requested-With": "XMLHttpRequest"
            },
            credentials: "same-origin"
        })
        .then(function (res) {
            if (res.ok) {
                lastPingTime = Date.now();
                if (typeof onSuccess === "function") {
                    onSuccess();
                }
            } else if (res.status === 401) {
                // Session expired on server; perform clean redirect
                performLogout();
            }
        })
        .catch(function (err) {
            // Network issue, continue locally
            console.warn("[IDLE] Session ping error:", err);
        });
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
        overlay.style.zIndex = "99999";

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
            // Ping server to extend backend session cookie
            pingServer(function () {
                const now = Date.now();
                setLastActiveTime(now);
                hideWarning();
                resetIdleTimers();
            });
            hideWarning();
            setLastActiveTime(Date.now());
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
        clearTimers();
        hideWarning();
        window.location.href = LOGOUT_URL;
    }

    function resetIdleTimers() {
        // Don’t run on the public login page, only on authenticated dashboards
        if (!document.getElementById("sidebar")) {
            clearTimers();
            hideWarning();
            return;
        }

        clearTimers();

        const now = Date.now();
        const lastActive = getLastActiveTime();
        const elapsed = Math.max(0, now - lastActive);

        // If inactive for 30+ minutes across tabs, log out
        if (elapsed >= LOGOUT_TIMEOUT) {
            performLogout();
            return;
        }

        // If inactive for 28+ minutes, show warning and schedule remaining time until logout
        if (elapsed >= WARNING_TIMEOUT) {
            showWarning();
            const remainLogout = LOGOUT_TIMEOUT - elapsed;
            logoutTimer = setTimeout(function () {
                const checkNow = Date.now();
                if (checkNow - getLastActiveTime() >= LOGOUT_TIMEOUT) {
                    performLogout();
                } else {
                    resetIdleTimers();
                }
            }, Math.max(1000, remainLogout));
            return;
        }

        hideWarning();

        const remainWarning = WARNING_TIMEOUT - elapsed;
        const remainLogout = LOGOUT_TIMEOUT - elapsed;

        warningTimer = setTimeout(function () {
            const checkNow = Date.now();
            if (checkNow - getLastActiveTime() >= WARNING_TIMEOUT) {
                showWarning();
            } else {
                resetIdleTimers();
            }
        }, Math.max(1000, remainWarning));

        logoutTimer = setTimeout(function () {
            const checkNow = Date.now();
            if (checkNow - getLastActiveTime() >= LOGOUT_TIMEOUT) {
                performLogout();
            } else {
                resetIdleTimers();
            }
        }, Math.max(2000, remainLogout));
    }

    function handleActivity() {
        if (document.hidden) {
            return;
        }
        const now = Date.now();
        setLastActiveTime(now);

        // Throttle server session keep-alive to every 5 minutes during active user interaction
        if (now - lastPingTime > PING_INTERVAL_MS) {
            lastPingTime = now;
            pingServer();
        }

        resetIdleTimers();
    }

    function initIdleTimeout() {
        if (!document.body) {
            return;
        }

        // Initialize last active time
        setLastActiveTime(Date.now());

        // Attach listeners for common user interactions
        const events = ["mousemove", "mousedown", "keydown", "scroll", "touchstart"];
        events.forEach(function (evt) {
            window.addEventListener(evt, handleActivity, { passive: true });
        });

        // Cross-tab synchronization via localStorage storage event
        window.addEventListener("storage", function (e) {
            if (e.key === STORAGE_KEY) {
                resetIdleTimers();
            }
        });

        document.addEventListener("visibilitychange", function () {
            if (!document.hidden) {
                const now = Date.now();
                if (now - lastPingTime > PING_INTERVAL_MS) {
                    lastPingTime = now;
                    pingServer();
                }
                resetIdleTimers();
            }
        });

        // Initial setup
        resetIdleTimers();
    }

    if (document.readyState === "complete" || document.readyState === "interactive") {
        initIdleTimeout();
    } else {
        document.addEventListener("DOMContentLoaded", initIdleTimeout);
    }
})();

