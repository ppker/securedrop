// Add "copy to clipboard" functionality to all copy buttons
document.querySelectorAll(".copy-btn").forEach(btn => {
    btn.addEventListener("click", () => {
        const selector = btn.dataset.target;
        const text = document.querySelector(selector).textContent.trim();
        navigator.clipboard.writeText(text);

        // Display exactly one ephemeral success message
        const cell = btn.parentNode;
        const existing = cell.querySelector(".copiedtip");
        if (existing) {
            existing.remove();
        }
        const tip = document.createElement("span");
        tip.className = "copiedtip";
        tip.textContent = "Copied to clipboard!";
        cell.appendChild(tip);
        setTimeout(() => tip.remove(), 2500);
    });
});

// Cycle through TOTP codes
function updateOTP() {
    const secret = document.getElementById("totpsecretvalue").textContent.trim();
    const totp = new jsOTP.totp();
    document.getElementById("totpvalue").textContent = totp.getOtp(secret);

    const epoch = Math.round(new Date().getTime() / 1000.0);
    const remaining = 30 - (epoch % 30);
    const seconds = `${remaining}`.padStart(2, "0");
    document.getElementById("totpttl").textContent = `(:${seconds} remaining)`;

    if (remaining < 10) {
        document.getElementById("totp").classList.add("expiring");
    } else {
        document.getElementById("totp").classList.remove("expiring");
    }
}
updateOTP();
setInterval(updateOTP, 1000);