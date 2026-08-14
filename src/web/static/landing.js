const API_BASE = window.COCO_API_BASE || "";

let clientId = null;

async function loadClientId() {
  try {
    const res = await fetch(`${API_BASE}/api/config`);
    const data = await res.json();
    clientId = data.discord_client_id || null;
  } catch (error) {
    console.error("could not load public config", error);
  }
}

function goToOauth() {
  if (!clientId) {
    alert("this bot isn't fully configured yet - DISCORD_CLIENT_ID is missing.");
    return;
  }
  const redirect = encodeURIComponent(`${window.location.origin}/dashboard`);
  window.location.href = `https://discord.com/api/oauth2/authorize?client_id=${clientId}&redirect_uri=${redirect}&response_type=token&scope=identify%20guilds`;
}

function goToInvite() {
  if (!clientId) {
    alert("this bot isn't fully configured yet - DISCORD_CLIENT_ID is missing.");
    return;
  }
  window.location.href = `https://discord.com/oauth2/authorize?client_id=${clientId}&permissions=8&scope=bot%20applications.commands`;
}

async function init() {
  await loadClientId();
  document.getElementById("login-button").addEventListener("click", goToOauth);
  document.getElementById("invite-button").addEventListener("click", goToInvite);
}

init();
