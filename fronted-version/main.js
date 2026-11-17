const fs = require('fs');

// ==========================================
// GLOBAL CONFIGURATION
// ==========================================
const POLL_INTERVAL_SECONDS = 30;
const COOKIES = ''; //copy cookies
const DATA_FILE = './positions.jsonl';
const STATE_FILE = './state.json';
// ==========================================

// Load the last saved timestamp, or default to 1 minute ago
function loadInitialTimestamp() {
  try {
    if (fs.existsSync(STATE_FILE)) {
      const state = JSON.parse(fs.readFileSync(STATE_FILE, 'utf8'));
      if (state.since) return state.since;
    }
  } catch (err) {
    console.warn('Could not load previous state, starting from current time.');
  }
  return new Date(Date.now() - 60_000).toISOString();
}

let since = loadInitialTimestamp();

async function fetchPositions() {
  const url = `https://mapy.com/api/share-position/subscriptions/me/current?since=${encodeURIComponent(since)}`;

  try {
    const response = await fetch(url, {
      headers: {
        'Accept': 'application/json',
        'Cookie': COOKIES,
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
      }
    });

    if (response.status === 401 || response.status === 403) {
      console.error(`[${new Date().toLocaleTimeString()}] ERROR: Session cookies expired (${response.status}). Please update COOKIES.`);
      return;
    }

    if (!response.ok) {
      console.warn(`[${new Date().toLocaleTimeString()}] Server returned HTTP ${response.status}, retrying in ${POLL_INTERVAL_SECONDS}s.`);
      return;
    }

    const data = await response.json();

    // Persist the updated server timestamp for the next poll
    if (data.timestamp) {
      since = data.timestamp;
      fs.writeFileSync(STATE_FILE, JSON.stringify({ since }), 'utf8');
    }

    const activeRunners = (data.items || []).filter(
      item => item.sharingStatus === 'active' && item.position
    );

    if (activeRunners.length === 0) {
      console.log(`[${new Date().toLocaleTimeString()}] No runners actively sharing location.`);
      return;
    }

    // Append each runner's position as a JSON line (crash-safe)
    const lines = activeRunners.map(item => JSON.stringify({
      recordedAt: new Date().toISOString(),
      subscriptionId: item.subscriptionId,
      deviceId: item.deviceId,
      deviceName: item.deviceName,
      lat: item.position.lat,
      lon: item.position.lon,
      accuracy: item.position.accuracy,
      azimuth: item.position.azimuth,
      positionTime: item.positionTime,
      battery: item.deviceInfo?.battery
    }));

    fs.appendFileSync(DATA_FILE, lines.join('\n') + '\n', 'utf8');
    console.log(`[${new Date().toLocaleTimeString()}] Saved ${activeRunners.length} position(s).`);

  } catch (err) {
    // Gracefully handle temporary network drops or laptop sleep/wake cycles
    console.warn(`[${new Date().toLocaleTimeString()}] Network error (${err.message}), continuing...`);
  }
}

console.log(`Starting position tracker (interval: ${POLL_INTERVAL_SECONDS}s)...`);
fetchPositions();
setInterval(fetchPositions, POLL_INTERVAL_SECONDS * 1000);