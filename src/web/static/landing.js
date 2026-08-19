const API_BASE = window.COCO_API_BASE || "";

let clientId = null;

async function loadClientId() {
  try {
    const res = await fetch(`${API_BASE}/api/config`);
    const data = await res.json();
    clientId = data.discord_client_id || null;
  } catch (e) {
    console.error("could not load public config", e);
  }
}

function storedToken() {
  const t = localStorage.getItem("coco_token");
  const exp = Number(localStorage.getItem("coco_token_exp") || 0);
  if (!t || Date.now() > exp) return null;
  return t;
}

async function checkExistingSession() {
  const token = storedToken();
  if (!token) return false;
  
  const res = await fetch("https://discord.com/api/v10/users/@me", {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (res.status !== 200) {
    localStorage.removeItem("coco_token");
    localStorage.removeItem("coco_token_exp");
    return false;
  }
  const user = await res.json();
  return user;
}

function goToOauth() {
  if (!clientId) {
    alert("this bot isn't fully configured yet — DISCORD_CLIENT_ID is missing.");
    return;
  }
  const redirect = encodeURIComponent(`${window.location.origin}/lite/dashboard`);
  window.location.href = `https://discord.com/api/oauth2/authorize?client_id=${clientId}&redirect_uri=${redirect}&response_type=token&scope=identify%20guilds`;
}

function goToInvite() {
  if (!clientId) {
    alert("this bot isn't fully configured yet — DISCORD_CLIENT_ID is missing.");
    return;
  }
  window.location.href = `https://discord.com/oauth2/authorize?client_id=${clientId}&permissions=8&scope=bot%20applications.commands`;
}

async function init() {
  await loadClientId();

  const loginBtn = document.getElementById("login-button");

  
  const user = await checkExistingSession();
  if (user) {
    
    loginBtn.textContent = `${user.username}`;
    loginBtn.addEventListener("click", () => window.location.href = "/lite/dashboard");
    
    if (user.avatar) {
      const img = document.createElement("img");
      img.src = `https://cdn.discordapp.com/avatars/${user.id}/${user.avatar}.png?size=32`;
      img.style.cssText = "width:24px;height:24px;border-radius:50%;vertical-align:middle;margin-right:6px;border:2px solid var(--brown-dark)";
      loginBtn.prepend(img);
    }
  } else {
    loginBtn.addEventListener("click", goToOauth);
  }

  document.getElementById("invite-button")?.addEventListener("click", goToInvite);
}

init();