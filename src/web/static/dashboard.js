const API_BASE = window.COCO_API_BASE || "";
const state = { token: null, user: null, guild: null, roles: [], textChannels: [] };
let toastTimer;

function toast(message, kind = "ok") {
  const element = document.getElementById("toast");
  element.textContent = message;
  element.className = `show ${kind}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => element.classList.remove("show"), 3000);
}

function saveToken(token, expiresIn = 604800) {
  localStorage.setItem("coco_token", token);
  localStorage.setItem("coco_token_exp", String(Date.now() + expiresIn * 1000));
}

function clearToken() {
  localStorage.removeItem("coco_token");
  localStorage.removeItem("coco_token_exp");
}

function loadToken() {
  const token = localStorage.getItem("coco_token");
  const expiry = Number(localStorage.getItem("coco_token_exp") || 0);
  if (!token || Date.now() > expiry) { clearToken(); return null; }
  return token;
}

async function api(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: { Authorization: `Bearer ${state.token}`, "Content-Type": "application/json", ...(options.headers || {}) },
  });
  if (response.status === 401) { clearToken(); showSignedOut(); return null; }
  try { return await response.json(); } catch { return null; }
}

const configFields = [
  ["moderator_role", "select", "roles"], ["admin_role", "select", "roles"], ["member_role", "select", "roles"],
  ["image_role", "select", "roles"], ["music_role", "select", "roles"], ["announcement_channel", "select", "channels"],
  ["announcement_role", "select", "roles"], ["join_channel", "select", "channels"], ["join_messages", "lines"],
  ["leave_channel", "select", "channels"], ["leave_messages", "lines"], ["widget_enabled", "checkbox"],
];
const moderationFields = [
  ["mute_channel", "select", "channels"], ["lockdown_include_member_role", "checkbox"], ["require_confirm", "checkbox"],
  ["warn_dm", "lines"], ["warn_channel", "lines"], ["kick_dm", "lines"], ["kick_channel", "lines"],
  ["ban_dm", "lines"], ["ban_channel", "lines"], ["mute_dm", "lines"], ["mute_channel_msg", "lines"],
];

function fillSelect(select, items, selected) {
  if (!select) return;
  select.innerHTML = "<option value=''>- none -</option>";
  items.forEach(item => {
    const option = document.createElement("option");
    option.value = String(item.id); option.textContent = item.name;
    option.selected = String(item.id) === String(selected ?? "");
    select.appendChild(option);
  });
}

function loadFields(root, fields, data) {
  fields.forEach(([key, type, source]) => {
    const wrapper = root.querySelector(`[data-field="${key}"]`);
    if (!wrapper) return;
    if (type === "select") fillSelect(wrapper.querySelector("select"), source === "roles" ? state.roles : state.textChannels, data[key]);
    if (type === "checkbox") wrapper.querySelector("input").checked = Boolean(data[key]);
    if (type === "lines") wrapper.querySelector("textarea").value = Array.isArray(data[key]) ? data[key].join("\n") : (data[key] || "");
  });
}

function saveFields(root, fields) {
  const payload = {};
  fields.forEach(([key, type]) => {
    const wrapper = root.querySelector(`[data-field="${key}"]`);
    if (!wrapper) return;
    if (type === "select") payload[key] = wrapper.querySelector("select").value || null;
    if (type === "checkbox") payload[key] = wrapper.querySelector("input").checked;
    if (type === "lines") payload[key] = wrapper.querySelector("textarea").value.split("\n").map(line => line.trim()).filter(Boolean);
  });
  return payload;
}

function showPanel(name) {
  document.querySelectorAll("[data-panel-id]").forEach(panel => panel.classList.toggle("active", panel.dataset.panelId === name));
  document.querySelectorAll(".dash-tab").forEach(tab => tab.classList.toggle("active", tab.dataset.panel === name));
  if (name === "moderation") loadModeration();
  if (name === "tickets") loadTicketPanels();
  if (name === "builder") loadSavedMessages();
}

function showSignedOut() {
  document.getElementById("signed-out-panel").style.display = "";
  document.getElementById("dash-tabs").hidden = true;
  document.getElementById("session-bar").hidden = true;
  document.getElementById("login-link").hidden = false;
  document.getElementById("logout-button").hidden = true;
  document.querySelectorAll("[data-panel-id]").forEach(panel => panel.classList.remove("active"));
}

function showDashboard() {
  document.getElementById("signed-out-panel").style.display = "none";
  document.getElementById("dash-tabs").hidden = false;
  document.getElementById("session-bar").hidden = false;
  document.getElementById("login-link").hidden = true;
  document.getElementById("logout-button").hidden = false;
}

async function fetchCurrentUser() {
  const response = await fetch("https://discord.com/api/v10/users/@me", { headers: { Authorization: `Bearer ${state.token}` } });
  return response.status === 200 ? response.json() : null;
}

async function loadGuilds() {
  const guilds = await api("/api/guilds");
  const list = document.getElementById("guild-list");
  list.innerHTML = "";
  if (!guilds?.length) { list.innerHTML = "<p>no servers found where you have admin permissions and coco is installed.</p>"; return; }
  guilds.forEach(guild => {
    const button = document.createElement("button");
    button.className = "button button-secondary"; button.textContent = guild.name;
    button.addEventListener("click", () => selectGuild(guild)); list.appendChild(button);
  });
  showPanel("servers");
}

async function selectGuild(guild) {
  state.guild = guild; document.getElementById("guild-name").textContent = guild.name;
  const [roles, channels] = await Promise.all([api(`/api/guild/${guild.id}/roles`), api(`/api/guild/${guild.id}/channels`)]);
  state.roles = roles || []; state.textChannels = (channels || []).filter(channel => channel.type === "text");
  const config = await api(`/api/guild/${guild.id}/config`);
  loadFields(document.getElementById("config-fields"), configFields, config || {});
  fillSelect(document.getElementById("ticket-panel-channel"), state.textChannels);
  fillSelect(document.getElementById("ticket-panel-staff-role"), state.roles);
  showPanel("config");
}

async function saveConfig() {
  const result = await api(`/api/guild/${state.guild.id}/config`, { method: "POST", body: JSON.stringify(saveFields(document.getElementById("config-fields"), configFields)) });
  result?.ok ? toast("settings saved") : toast(result?.error || "failed to save", "err");
}

async function loadModeration() {
  if (!state.guild) return;
  const data = await api(`/api/guild/${state.guild.id}/moderation`);
  if (data) loadFields(document.getElementById("moderation-fields"), moderationFields, data);
}

async function saveModeration() {
  const result = await api(`/api/guild/${state.guild.id}/moderation`, { method: "POST", body: JSON.stringify(saveFields(document.getElementById("moderation-fields"), moderationFields)) });
  result?.ok ? toast("moderation settings saved") : toast(result?.error || "failed to save", "err");
}

async function loadTicketPanels() {
  if (!state.guild) return;
  const panels = await api(`/api/guild/${state.guild.id}/ticket_panels`);
  const list = document.getElementById("ticket-panels-list"); list.innerHTML = "";
  (panels || []).forEach(panel => { const item = document.createElement("p"); item.textContent = `${panel.title} - channel ${panel.channel_id}`; list.appendChild(item); });
  if (!panels?.length) list.innerHTML = "<p>no panels yet.</p>";
}

async function createTicketPanel() {
  const payload = { channel_id: document.getElementById("ticket-panel-channel").value, staff_role_id: document.getElementById("ticket-panel-staff-role").value || null, title: document.getElementById("ticket-panel-title").value || "support", description: document.getElementById("ticket-panel-description").value || "click below to open a ticket" };
  if (!payload.channel_id) { toast("pick a channel first", "err"); return; }
  const result = await api(`/api/guild/${state.guild.id}/ticket_panels`, { method: "POST", body: JSON.stringify(payload) });
  result?.ok ? (toast("ticket panel posted"), loadTicketPanels()) : toast(result?.error || "failed", "err");
}

async function loadSavedMessages() {
  if (!state.guild) return;
  const messages = await api(`/api/guild/${state.guild.id}/messages`);
  const list = document.getElementById("saved-messages-list");
  if (list) list.textContent = messages?.length ? `${messages.length} saved message(s)` : "no saved messages yet.";
}

function signOut() { clearToken(); state.token = null; state.guild = null; showSignedOut(); }

async function init() {
  const hash = new URLSearchParams(window.location.hash.substring(1));
  if (hash.has("access_token")) { saveToken(hash.get("access_token"), Number(hash.get("expires_in") || 604800)); history.replaceState({}, document.title, window.location.pathname); }
  state.token = loadToken();
  if (state.token) { state.user = await fetchCurrentUser(); if (state.user) { showDashboard(); await loadGuilds(); } else signOut(); }
  else showSignedOut();
  document.getElementById("logout-button").addEventListener("click", signOut);
  document.querySelectorAll(".dash-tab").forEach(tab => tab.addEventListener("click", () => state.guild || tab.dataset.panel === "servers" ? showPanel(tab.dataset.panel) : toast("select a server first", "err")));
  document.getElementById("save-config")?.addEventListener("click", saveConfig);
  document.getElementById("save-moderation")?.addEventListener("click", saveModeration);
  document.getElementById("create-ticket-panel")?.addEventListener("click", createTicketPanel);
}

init();