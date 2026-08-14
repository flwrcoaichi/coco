const API_BASE = window.COCO_API_BASE || "";

const state = { token: null, guild: null };

const panels = document.querySelectorAll("[data-panel-id]");
const tabs = document.querySelectorAll(".dash-tab");
const signedOutPanel = document.getElementById("signed-out-panel");
const dashTabs = document.getElementById("dash-tabs");
const guildNameEl = document.getElementById("guild-name");

const CONFIG_FIELDS = [
  { key: "moderator_role", input: "select", source: "roles" },
  { key: "admin_role", input: "select", source: "roles" },
  { key: "member_role", input: "select", source: "roles" },
  { key: "image_role", input: "select", source: "roles" },
  { key: "music_role", input: "select", source: "roles" },
  { key: "ticket_channel", input: "select", source: "text_channels" },
  { key: "ticket_message", input: "text" },
  { key: "announcement_channel", input: "select", source: "text_channels" },
  { key: "announcement_role", input: "select", source: "roles" },
  { key: "join_channel", input: "select", source: "text_channels" },
  { key: "join_messages", input: "lines" },
  { key: "leave_channel", input: "select", source: "text_channels" },
  { key: "leave_messages", input: "lines" },
  { key: "widget_enabled", input: "checkbox" },
];

const MODERATION_FIELDS = [
  { key: "mute_channel", input: "select", source: "text_channels" },
  { key: "lockdown_include_member_role", input: "checkbox" },
  { key: "require_confirm", input: "checkbox" },
  { key: "warn_dm", input: "lines" },
  { key: "warn_channel", input: "lines" },
  { key: "kick_dm", input: "lines" },
  { key: "kick_channel", input: "lines" },
  { key: "ban_dm", input: "lines" },
  { key: "ban_channel", input: "lines" },
  { key: "mute_dm", input: "lines" },
  { key: "mute_channel_msg", input: "lines" },
];

function authHeaders() {
  return { Authorization: `Bearer ${state.token}`, "Content-Type": "application/json" };
}

async function api(path, options = {}) {
  const res = await fetch(`${API_BASE}${path}`, { ...options, headers: { ...authHeaders(), ...(options.headers || {}) } });
  return res.json();
}

function fieldEl(root, key) {
  return root.querySelector(`[data-field="${key}"]`);
}

function fillSelect(select, items, selected) {
  select.innerHTML = "<option value=''>none</option>";
  items.forEach((item) => {
    const option = document.createElement("option");
    option.value = item.id;
    option.textContent = item.name;
    if (item.id === selected) option.selected = true;
    select.appendChild(option);
  });
}

function linesToList(value) {
  return value.split("\n").map((line) => line.trim()).filter(Boolean);
}

function listToLines(items) {
  return (items || []).join("\n");
}

function loadFields(root, fields, data, roles, textChannels) {
  const sources = { roles, text_channels: textChannels };
  fields.forEach(({ key, input, source }) => {
    const wrap = fieldEl(root, key);
    if (!wrap) return;
    const value = data[key];
    if (input === "select") {
      fillSelect(wrap.querySelector("select"), sources[source] || [], value || "");
    } else if (input === "checkbox") {
      wrap.querySelector("input").checked = Boolean(value);
    } else if (input === "lines") {
      wrap.querySelector("textarea").value = listToLines(value);
    } else {
      wrap.querySelector("input").value = value || "";
    }
  });
}

function saveFields(root, fields) {
  const payload = {};
  fields.forEach(({ key, input }) => {
    const wrap = fieldEl(root, key);
    if (!wrap) return;
    if (input === "select") {
      payload[key] = wrap.querySelector("select").value || null;
    } else if (input === "checkbox") {
      payload[key] = wrap.querySelector("input").checked;
    } else if (input === "lines") {
      payload[key] = linesToList(wrap.querySelector("textarea").value);
    } else {
      payload[key] = wrap.querySelector("input").value || null;
    }
  });
  return payload;
}

function showPanel(name) {
  panels.forEach((panel) => (panel.hidden = panel.dataset.panelId !== name));
  tabs.forEach((tab) => tab.classList.toggle("active", tab.dataset.panel === name));
  if (name === "tickets") loadTicketPanels();
  if (name === "containers") loadContainers();
  if (name === "moderation") loadModeration();
}

async function loadGuilds() {
  const guilds = await api("/api/guilds");
  if (guilds.error) return alert(guilds.error);
  const list = document.getElementById("guild-list");
  list.innerHTML = "";
  guilds.forEach((guild) => {
    const card = document.createElement("button");
    card.className = "button button-secondary";
    card.textContent = guild.name;
    card.addEventListener("click", () => selectGuild(guild));
    list.appendChild(card);
  });
  showPanel("servers");
}

async function selectGuild(guild) {
  state.guild = guild;
  guildNameEl.textContent = guild.name;
  await loadConfigPanel();
  showPanel("config");
}

async function loadConfigPanel() {
  const guildId = state.guild.id;
  const [roles, channels, config] = await Promise.all([
    api(`/api/guild/${guildId}/roles`),
    api(`/api/guild/${guildId}/channels`),
    api(`/api/guild/${guildId}/config`),
  ]);
  const textChannels = channels.filter((c) => c.type === "text");
  const categories = channels.filter((c) => c.type === "category");
  const root = document.getElementById("config-fields");
  loadFields(root, CONFIG_FIELDS, config, roles, textChannels);
  fillSelect(document.getElementById("ticket-panel-channel"), textChannels, "");
  fillSelect(document.getElementById("ticket-panel-category"), categories, "");
  fillSelect(document.getElementById("ticket-panel-staff-role"), roles, "");
  renderWidgetPreview(guildId, Boolean(config.widget_enabled));
}

function renderWidgetPreview(guildId, enabled) {
  const preview = document.getElementById("widget-preview");
  preview.innerHTML = "";
  if (!enabled) return;
  const iframe = document.createElement("iframe");
  iframe.src = `https://discord.com/widget?id=${guildId}&theme=dark`;
  iframe.width = "350";
  iframe.height = "500";
  iframe.allowTransparency = "true";
  iframe.frameBorder = "0";
  iframe.sandbox = "allow-popups allow-popups-to-escape-sandbox allow-same-origin allow-scripts";
  preview.appendChild(iframe);
}

async function saveConfig() {
  const payload = saveFields(document.getElementById("config-fields"), CONFIG_FIELDS);
  const result = await api(`/api/guild/${state.guild.id}/config`, { method: "POST", body: JSON.stringify(payload) });
  if (result.ok) {
    alert("settings saved");
    renderWidgetPreview(state.guild.id, Boolean(payload.widget_enabled));
  } else {
    alert(result.error || "failed to save settings");
  }
}

async function loadModeration() {
  const guildId = state.guild.id;
  const [roles, channels, mod] = await Promise.all([
    api(`/api/guild/${guildId}/roles`),
    api(`/api/guild/${guildId}/channels`),
    api(`/api/guild/${guildId}/moderation`),
  ]);
  if (mod.error) return alert(mod.error);
  loadFields(document.getElementById("moderation-fields"), MODERATION_FIELDS, mod, roles, channels.filter((c) => c.type === "text"));
}

async function saveModeration() {
  const payload = saveFields(document.getElementById("moderation-fields"), MODERATION_FIELDS);
  const result = await api(`/api/guild/${state.guild.id}/moderation`, { method: "POST", body: JSON.stringify(payload) });
  alert(result.ok ? "moderation settings saved" : result.error || "failed to save moderation settings");
}

function renderList(container, items, renderItem) {
  container.innerHTML = "";
  items.forEach((item) => container.appendChild(renderItem(item)));
}

async function loadTicketPanels() {
  const panels_ = await api(`/api/guild/${state.guild.id}/ticket_panels`);
  if (panels_.error) return alert(panels_.error);
  renderList(document.getElementById("ticket-panels-list"), panels_, (panel) => {
    const card = document.createElement("div");
    card.className = "panel-card";
    card.innerHTML = `<strong>${panel.title}</strong><div>${panel.description}</div><div>channel: ${panel.channel_id}</div>`;
    return card;
  });
}

async function createTicketPanel() {
  const payload = {
    channel_id: document.getElementById("ticket-panel-channel").value || null,
    category_id: document.getElementById("ticket-panel-category").value || null,
    staff_role_id: document.getElementById("ticket-panel-staff-role").value || null,
    title: document.getElementById("ticket-panel-title").value || "support",
    description: document.getElementById("ticket-panel-description").value || "click below to open a ticket",
  };
  const result = await api(`/api/guild/${state.guild.id}/ticket_panels`, { method: "POST", body: JSON.stringify(payload) });
  if (result.ok) {
    alert("ticket panel created");
    loadTicketPanels();
  } else {
    alert(result.error || "failed to create ticket panel");
  }
}

async function loadContainers() {
  const containers = await api(`/api/guild/${state.guild.id}/containers`);
  if (containers.error) return alert(containers.error);
  renderList(document.getElementById("container-list"), containers, (container) => {
    const card = document.createElement("div");
    card.className = "panel-card";
    card.innerHTML = `<strong>${container.name}</strong><div>items: ${JSON.stringify(container.items)}</div><div>accent: ${container.accent_color ?? "none"}</div>`;
    return card;
  });
}

async function saveContainer() {
  let items;
  try {
    items = JSON.parse(document.getElementById("container-items").value || "[]");
  } catch (error) {
    return alert("container items must be valid JSON");
  }
  const name = document.getElementById("container-name").value.trim();
  if (!name) return alert("container name is required");
  const accentRaw = document.getElementById("container-accent").value;
  const payload = { name, items, accent_color: accentRaw ? Number(accentRaw) : null };
  const result = await api(`/api/guild/${state.guild.id}/containers`, { method: "POST", body: JSON.stringify(payload) });
  if (result.ok) {
    alert("container saved");
    loadContainers();
  } else {
    alert(result.error || "failed to save container");
  }
}

async function executeAction(action) {
  const body = { url: "" };
  if (action === "play") {
    body.url = prompt("enter a YouTube URL to play:");
    if (!body.url) return;
  }
  if (action === "open_twitch") {
    body.url = prompt("enter a Twitch channel URL:");
    if (!body.url) return;
  }
  const result = await api(`/api/guild/${state.guild.id}/actions/${action}`, { method: "POST", body: JSON.stringify(body) });
  alert(result.ok ? result.message || "action completed" : result.error || "action failed");
}

function signOut() {
  window.location.href = "/";
}

function initEvents() {
  tabs.forEach((tab) => tab.addEventListener("click", () => showPanel(tab.dataset.panel)));
  document.getElementById("logout-button").addEventListener("click", signOut);
  document.getElementById("save-config").addEventListener("click", saveConfig);
  document.getElementById("save-moderation").addEventListener("click", saveModeration);
  document.getElementById("create-ticket-panel").addEventListener("click", createTicketPanel);
  document.getElementById("save-container").addEventListener("click", saveContainer);
  document.querySelectorAll(".tile-action").forEach((button) => {
    button.addEventListener("click", () => executeAction(button.dataset.action));
  });
}

function tokenFromHash() {
  const params = new URLSearchParams(window.location.hash.substring(1));
  if (!params.has("access_token")) return null;
  history.replaceState({}, document.title, window.location.pathname);
  return params.get("access_token");
}

async function init() {
  state.token = tokenFromHash();
  if (!state.token) {
    signedOutPanel.hidden = false;
    return;
  }
  signedOutPanel.hidden = true;
  dashTabs.hidden = false;
  initEvents();
  await loadGuilds();
}

init();
