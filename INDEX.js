// ==========================================================
// EVCharge front end - talks to the FastAPI backend
// ==========================================================

// ---------- SETTINGS ----------
// The website is served by the backend itself, so "/api" works.
// (If you open index.html straight from a folder, it falls back to the local server.)
const API = location.protocol === "file:" ? "http://127.0.0.1:8000/api" : "/api";

const USER_LOCATION = { lat: 13.0827, lon: 80.2707 };   // demo location; could use navigator.geolocation
const BATTERY_KWH = 40;          // size of the demo vehicle's battery
const RANGE_KM_AT_FULL = 400;    // range at 100%
const ESTIMATE_PRICE = 18;       // Rs per kWh used for the hero card estimate

const RING_RADIUS = 52;                    // must match r="52" in the SVG
const CIRC = 2 * Math.PI * RING_RADIUS;    // ring circumference


// ---------- STATE ----------
let token = localStorage.getItem("evc_token");
let currentUser = null;
let stations = [];
let selectedStation = null;
let activeSessionId = null;
let pollTimer = null;
let pollFailures = 0;
let vehicleSoc = 42;          // battery % of the demo vehicle (reload the page to reset)
let authMode = "login";
let searchTimer = null;
let chargerRequestId = 0;


// ---------- SMALL HELPERS ----------
function esc(text) {
    return String(text).replace(/[&<>"']/g, ch => (
        { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]
    ));
}

function money(amount) {
    return "₹" + (Math.round(Number(amount) * 100) / 100).toLocaleString("en-IN");
}

let toastTimer;
function toast(message, type = "", ms = 3500) {
    const el = document.getElementById("toast");
    el.textContent = message;
    el.className = "toast show " + type;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.remove("show"), ms);
}

// One place that talks to the server: adds the login token and turns errors into messages.
async function api(path, options = {}) {

    const headers = { "Content-Type": "application/json" };
    if (token) headers.Authorization = "Bearer " + token;

    let res;
    try {
        res = await fetch(API + path, { ...options, headers });
    } catch (err) {
        throw new Error("Cannot reach the server. Is the backend running?");
    }

    let data = null;
    try { data = await res.json(); } catch (err) { /* empty body */ }

    if (!res.ok) {
        if (res.status === 401 && token && !path.startsWith("/auth/login")) {
            logout(false);
            toast("Your session expired. Please log in again.", "error");
        }
        let message = "Something went wrong";
        if (data && typeof data.detail === "string") {
            message = data.detail;
        } else if (data && Array.isArray(data.detail) && data.detail.length) {
            const field = data.detail[0].loc[data.detail[0].loc.length - 1];
            message = field + ": " + data.detail[0].msg;
        }
        throw new Error(message);
    }
    return data;
}


// ==========================================================
// SMOOTH SCROLL
// ==========================================================

function scrollToChargers() {
    document.getElementById("chargers").scrollIntoView({ behavior: "smooth" });
}


// ==========================================================
// ACCOUNT: login, sign up, wallet
// ==========================================================

function openAccount() {
    document.getElementById("accountModal").style.display = "flex";
    if (currentUser) loadWallet();
}

function closeAccount() {
    document.getElementById("accountModal").style.display = "none";
}

function switchAuth(mode) {
    authMode = mode;
    const register = mode === "register";
    document.getElementById("tabLogin").classList.toggle("active", !register);
    document.getElementById("tabRegister").classList.toggle("active", register);
    document.getElementById("authName").hidden = !register;
    document.getElementById("authSubmit").textContent = register ? "Create account" : "Log in";
    document.getElementById("authPassword").autocomplete = register ? "new-password" : "current-password";
    document.getElementById("authError").textContent = "";
}

async function submitAuth() {

    const name = document.getElementById("authName").value.trim();
    const email = document.getElementById("authEmail").value.trim();
    const password = document.getElementById("authPassword").value;
    const errorEl = document.getElementById("authError");
    const btn = document.getElementById("authSubmit");

    errorEl.textContent = "";
    if (authMode === "register" && name.length < 2) {
        errorEl.textContent = "Please enter your name";
        return;
    }
    if (!email || !password) {
        errorEl.textContent = "Please enter your email and password";
        return;
    }

    btn.disabled = true;
    try {
        const body = authMode === "register" ? { name, email, password } : { email, password };
        const data = await api(authMode === "register" ? "/auth/register" : "/auth/login", {
            method: "POST",
            body: JSON.stringify(body)
        });

        token = data.access_token;
        localStorage.setItem("evc_token", token);
        currentUser = data.user;
        document.getElementById("authPassword").value = "";

        renderAccount();
        closeAccount();
        toast(
            authMode === "register"
                ? "Welcome, " + currentUser.name + "! " + money(currentUser.wallet_balance) + " is in your wallet."
                : "Welcome back, " + currentUser.name,
            "success"
        );
        loadHistory();
        resumeActiveSession();

    } catch (err) {
        errorEl.textContent = err.message;
    } finally {
        btn.disabled = false;
    }
}

function logout(showMessage = true) {
    stopPolling();
    activeSessionId = null;
    document.getElementById("chargingModal").style.display = "none";

    token = null;
    currentUser = null;
    localStorage.removeItem("evc_token");

    renderAccount();
    loadHistory();
    if (showMessage) {
        closeAccount();
        toast("You have been logged out");
    }
}

async function loadUser() {
    if (token) {
        try {
            currentUser = await api("/auth/me");
        } catch (err) {
            currentUser = null;
        }
    }
    renderAccount();
}

function renderAccount() {
    const chip = document.getElementById("walletChip");
    document.getElementById("authView").hidden = !!currentUser;
    document.getElementById("accountView").hidden = !currentUser;

    if (!currentUser) {
        chip.hidden = true;
        return;
    }
    chip.hidden = false;
    chip.textContent = "Wallet " + money(currentUser.wallet_balance);

    document.getElementById("accName").textContent = currentUser.name;
    document.getElementById("accEmail").textContent = currentUser.email;
    document.getElementById("accBalance").textContent = money(currentUser.wallet_balance);
}

async function loadWallet() {
    try {
        const wallet = await api("/wallet");
        currentUser.wallet_balance = wallet.balance;
        renderAccount();

        document.getElementById("txnList").innerHTML = wallet.transactions.length
            ? wallet.transactions.slice(0, 8).map(t => `
                <div class="txn">
                    <span>${esc(t.description)}</span>
                    <b class="${t.amount >= 0 ? "plus" : "minus"}">
                        ${t.amount >= 0 ? "+" : "-"}${money(Math.abs(t.amount))}
                    </b>
                </div>`).join("")
            : '<div class="txn"><span>No activity yet</span></div>';
    } catch (err) {
        toast(err.message, "error");
    }
}

async function topUp(amount) {
    try {
        const wallet = await api("/wallet/topup", {
            method: "POST",
            body: JSON.stringify({ amount })
        });
        currentUser.wallet_balance = wallet.balance;
        renderAccount();
        loadWallet();
        toast(money(amount) + " added to your wallet", "success");
    } catch (err) {
        toast(err.message, "error");
    }
}


// ==========================================================
// DISCOVERY: chargers from every network
// ==========================================================

const ICONS = ["⚡", "🔋", "🔌"];

function chargerCard(st) {

    const busy = st.available_ports === 0;

    return `
    <div class="charger-card">

        <div class="charger-header">
            <div class="charger-icon">${ICONS[st.id % ICONS.length]}</div>
            <span class="${busy ? "occupied" : "available"}">
                ● ${busy ? "Busy" : "Available"}
            </span>
        </div>

        <span class="network-tag">${esc(st.network)}</span>
        <h3>${esc(st.name)}</h3>
        <p class="location">📍 ${st.distance_km} km away</p>

        <div class="charger-details">
            <div><small>Power</small><strong>${st.power_kw} kW</strong></div>
            <div><small>Price</small><strong>₹${st.price_per_kwh}/kWh</strong></div>
            <div><small>Ports</small><strong>${st.available_ports}/${st.total_ports}</strong></div>
        </div>

        ${busy
            ? '<button class="reserve-btn disabled" disabled>Currently Busy</button>'
            : `<button class="reserve-btn" onclick="openCharger(${st.id})">View &amp; Reserve</button>`}

    </div>`;
}

async function loadChargers() {

    const grid = document.getElementById("chargerGrid");
    const myRequest = ++chargerRequestId;      // ignore slow answers that arrive out of order

    const params = new URLSearchParams({
        lat: USER_LOCATION.lat,
        lon: USER_LOCATION.lon,
        q: document.getElementById("searchInput").value.trim(),
        filter: document.getElementById("filterSelect").value
    });

    try {
        const list = await api("/chargers?" + params);
        if (myRequest !== chargerRequestId) return;

        stations = list;
        grid.innerHTML = list.length
            ? list.map(chargerCard).join("")
            : '<p class="empty">No chargers match your search.</p>';

    } catch (err) {
        if (myRequest !== chargerRequestId) return;
        grid.innerHTML = `<p class="empty">${esc(err.message)}</p>`;
    }
}

function searchChargers() {                   // called on every key press
    clearTimeout(searchTimer);
    searchTimer = setTimeout(loadChargers, 250);
}

function filterChargers() {
    loadChargers();
}

async function loadStats() {
    try {
        const s = await api("/stats");
        document.getElementById("statTotal").textContent = s.total_stations;
        document.getElementById("statAvailable").textContent = s.available_stations;
        document.getElementById("statFastest").textContent = s.fastest_kw + " kW";
        document.getElementById("statPrice").textContent = "₹" + s.lowest_price + "/kWh";
    } catch (err) { /* the chargers section already shows the connection error */ }
}

async function loadRecommendation() {
    const text = document.getElementById("recText");
    const score = document.getElementById("recScore");
    try {
        const r = await api(`/recommendation?lat=${USER_LOCATION.lat}&lon=${USER_LOCATION.lon}`);
        text.textContent =
            "Comparing every network, " + r.station.name + " (" + r.station.network +
            ") is the best option right now: " + r.reasons.join(", ") + ".";
        score.textContent = r.match_percent + "%";
    } catch (err) {
        text.textContent = err.message;
        score.textContent = "-";
    }
}


// "Find near by chargers" button: use the browser's location, then show the closest chargers first
async function findNearbyStations() {

    if (!navigator.geolocation) {
        toast("Your browser does not support location", "error");
        return;
    }

    toast("Getting your location...");

    navigator.geolocation.getCurrentPosition(
        async function (position) {

            // use the real coordinates for every distance on the page
            USER_LOCATION.lat = position.coords.latitude;
            USER_LOCATION.lon = position.coords.longitude;

            document.getElementById("searchInput").value = "";

            await loadChargers();          // the backend sorts nearest first
            loadRecommendation();
            scrollToChargers();

            if (stations.length) {
                toast(
                    "Nearest: " + stations[0].name + ", " + stations[0].distance_km + " km away",
                    "success"
                );
            }
        },

        function (error) {
            toast(
                error.code === 1
                    ? "Location access is blocked. Allow it in your browser and try again."
                    : "Could not get your location. Please try again.",
                "error",
                5000
            );
        },

        { timeout: 10000, maximumAge: 60000 }
    );
}


// ==========================================================
// CHARGER MODAL
// ==========================================================

function openCharger(id) {

    selectedStation = stations.find(s => s.id === id);
    if (!selectedStation) return;
    const st = selectedStation;

    document.getElementById("modalName").textContent = st.name;
    document.getElementById("modalLocation").textContent =
        st.network + " network, " + st.distance_km + " km away";
    document.getElementById("modalPower").textContent = st.power_kw + " kW";
    document.getElementById("modalPrice").textContent = "₹" + st.price_per_kwh + "/kWh";
    document.getElementById("modalPorts").textContent = st.available_ports + "/" + st.total_ports;
    document.getElementById("modalConnectors").textContent = "Connectors: " + st.connectors.join(", ");

    document.getElementById("chargerModal").style.display = "flex";
}

function closeModal() {
    document.getElementById("chargerModal").style.display = "none";
}


// ==========================================================
// RESERVE -> START -> LIVE SESSION
// ==========================================================

async function reserveCharger() {

    if (!currentUser) {
        closeModal();
        toast("Please log in to reserve a charger");
        openAccount();
        return;
    }
    if (vehicleSoc >= 99) {
        toast("Your battery is already full. Reload the page to reset the demo battery.");
        return;
    }

    const btn = document.getElementById("reserveBtn");
    btn.disabled = true;
    let reservation = null;

    try {
        reservation = await api("/reservations", {
            method: "POST",
            body: JSON.stringify({
                station_id: selectedStation.id,
                start_soc: vehicleSoc,
                battery_kwh: BATTERY_KWH
            })
        });
        const session = await api(`/sessions/${reservation.id}/start`, { method: "POST" });

        closeModal();
        openChargingModal(session);
        toast("Charger reserved. Charging started.", "success");
        loadChargers();
        loadStats();

    } catch (err) {
        if (reservation) {
            // started failing after the port was reserved: release the port again
            api(`/sessions/${reservation.id}/cancel`, { method: "POST" }).catch(() => {});
        }
        toast(err.message, "error", 5000);
    } finally {
        btn.disabled = false;
    }
}

function openChargingModal(session) {
    activeSessionId = session.id;
    pollFailures = 0;

    document.getElementById("sessionStation").textContent =
        session.station_name + " (" + session.network + ")";
    document.getElementById("chargingModal").style.display = "flex";
    updateChargingUI(session);

    stopPolling();
    pollTimer = setInterval(pollSession, 1000);
}

function stopPolling() {
    clearInterval(pollTimer);
    pollTimer = null;
}

async function pollSession() {
    if (!activeSessionId) return;
    try {
        const s = await api("/sessions/" + activeSessionId);
        pollFailures = 0;
        updateChargingUI(s);
        if (s.status !== "charging") finishSession(s);   // battery full, wallet empty, etc.
    } catch (err) {
        if (++pollFailures >= 5) {
            stopPolling();
            toast("Lost connection to the server. Log in again to resume your session.", "error", 6000);
        }
    }
}

function updateChargingUI(s) {

    document.getElementById("batteryPercent").textContent = Math.round(s.soc) + "%";
    document.getElementById("powerValue").textContent = Math.round(s.power_kw) + " kW";
    document.getElementById("energyValue").textContent = s.energy_kwh.toFixed(1) + " kWh";
    document.getElementById("costValue").textContent = "₹" + Math.round(s.cost);

    // move the SVG ring (0 = full ring, CIRC = empty ring)
    const ring = document.getElementById("ringProgress");
    ring.style.strokeDasharray = CIRC;
    ring.style.strokeDashoffset = CIRC * (1 - s.soc / 100);

    // keep the hero card in sync with the live charge
    vehicleSoc = s.soc;
    renderHero();
}

function renderHero() {
    document.getElementById("heroBattery").textContent = Math.round(vehicleSoc) + "%";
    document.getElementById("heroLevel").style.width = vehicleSoc + "%";
    document.getElementById("heroRange").textContent =
        Math.round(vehicleSoc / 100 * RANGE_KM_AT_FULL) + " km";
    document.getElementById("heroEstimate").textContent =
        "₹" + Math.round((100 - vehicleSoc) / 100 * BATTERY_KWH * ESTIMATE_PRICE);
}

async function stopCharging() {

    if (!activeSessionId) return;
    const btn = document.getElementById("stopBtn");
    btn.disabled = true;

    try {
        const s = await api(`/sessions/${activeSessionId}/stop`, { method: "POST" });
        finishSession(s);
    } catch (err) {
        toast(err.message, "error");
    } finally {
        btn.disabled = false;
    }
}

function closeCharging() {
    // closing the window while charging = stop and pay for the energy used
    if (activeSessionId) {
        if (confirm("Stop charging and pay for the energy used so far?")) stopCharging();
    } else {
        document.getElementById("chargingModal").style.display = "none";
    }
}

function finishSession(s) {

    stopPolling();
    activeSessionId = null;
    document.getElementById("chargingModal").style.display = "none";

    if (currentUser) {
        currentUser.wallet_balance = s.wallet_balance;
        renderAccount();
    }

    if (s.status === "completed") {
        const why = {
            battery_full: "Battery is full.",
            wallet_empty: "Your wallet balance ran out.",
            user_stopped: "Charging stopped."
        }[s.stop_reason] || "Charging finished.";

        toast(
            why + "\nEnergy: " + s.energy_kwh.toFixed(1) + " kWh\nPaid: " + money(s.cost) + " from your wallet",
            "success",
            7000
        );
    } else {
        toast("This session is " + s.status + ".");
    }

    loadHistory();
    loadChargers();
    loadStats();
    loadRecommendation();
}

// If the page is reloaded (or you log in again) while charging, pick the session back up.
async function resumeActiveSession() {
    if (!currentUser) return;
    try {
        const s = await api("/sessions/active");
        if (!s) return;

        if (s.status === "charging") {
            vehicleSoc = s.soc;
            openChargingModal(s);
            toast("Welcome back. Your charging session is still running.");
        } else if (s.status === "reserved") {
            await api(`/sessions/${s.id}/cancel`, { method: "POST" });   // never started: free the port
            loadChargers();
        }
    } catch (err) { /* nothing to resume */ }
}


// ==========================================================
// HISTORY
// ==========================================================

async function loadHistory() {

    const body = document.getElementById("historyBody");

    if (!currentUser) {
        body.innerHTML = '<div class="history-empty">Log in to see your charging history.</div>';
        return;
    }

    try {
        const rows = await api("/history");
        body.innerHTML = rows.length
            ? rows.map(r => `
                <div class="history-row">
                    <span>${esc(r.station_name)}</span>
                    <span>${new Date(r.date).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" })}</span>
                    <span>${r.energy_kwh} kWh</span>
                    <strong>${money(r.amount)}</strong>
                </div>`).join("")
            : '<div class="history-empty">No charging sessions yet. Reserve a charger to get started.</div>';
    } catch (err) {
        body.innerHTML = `<div class="history-empty">${esc(err.message)}</div>`;
    }
}


// ==========================================================
// CLOSE MODALS BY CLICKING OUTSIDE
// ==========================================================

// The charging window is NOT closed by clicking outside, so a stray click
// can't stop a live session.
window.addEventListener("click", function (event) {
    if (event.target === document.getElementById("chargerModal")) closeModal();
    if (event.target === document.getElementById("accountModal")) closeAccount();
});

// Press Enter inside the login form to submit it
document.getElementById("accountModal").addEventListener("keydown", function (event) {
    if (event.key === "Enter" && !document.getElementById("authView").hidden) submitAuth();
});


// ==========================================================
// START
// ==========================================================

async function init() {
    renderHero();
    switchAuth("login");
    await loadUser();
    loadChargers();
    loadStats();
    loadRecommendation();
    loadHistory();
    resumeActiveSession();
}

init();