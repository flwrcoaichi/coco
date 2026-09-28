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
  const safeToken = String(token || "").trim();
  if (!safeToken) return false;
  localStorage.setItem("coco_token", safeToken);
  localStorage.setItem("coco_token_exp", String(Date.now() + Number(expiresIn || 604800) * 1000));
  state.token = safeToken;
  return true;
}

function clearToken() {
  localStorage.removeItem("coco_token");
  localStorage.removeItem("coco_token_exp");
  state.token = null;
  state.user = null;
}

function loadToken() {
  const token = localStorage.getItem("coco_token");
  const expiry = Number(localStorage.getItem("coco_token_exp") || 0);
  if (!token || Date.now() > expiry) { clearToken(); return null; }
  return token;
}

async function api(path, options = {}) {
  const token = state.token || loadToken();
  if (!token) {
    showSignedOut();
    return null;
  }
  state.token = token;

  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json", ...(options.headers || {}) },
  });
  if (!response.ok) {
    const errorText = await response.text().catch(() => '');
    console.error(`API Error [${response.status}] on ${path}:`, errorText);

    if (response.status === 401) {
      return null;
    }
    return null;
  }
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
  if (!guilds?.length) { list.innerHTML = "<p>no servers found where you have admin permissions and niskbot is installed.</p>"; return; }
  guilds.forEach(guild => {
    const button = document.createElement("button");
    button.className = "button button-secondary"; button.textContent = guild.name;
    button.addEventListener("click", () => selectGuild(guild)); list.appendChild(button);
  });
  showPanel("servers");
}

async function selectGuild(guild) {
  state.guild = guild; document.getElementById("guild-name").textContent = guild.name;

  const roles = await api(`/api/guild/${guild.id}/roles`);
  const channels = await api(`/api/guild/${guild.id}/channels`);

  state.roles = roles || [];
  state.textChannels = (channels || []).filter(channel => channel.type === "text");

  const config = await api(`/api/guild/${guild.id}/config`);
  loadFields(document.getElementById("config-fields"), configFields, config || {});
  fillSelect(document.getElementById("ticket-panel-channel"), state.textChannels);
  fillSelect(document.getElementById("ticket-panel-staff-role"), state.roles);
  fillSelect(document.getElementById("builder-channel"), state.textChannels);
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

function splitTopLevel(text, delimiter = ":") {
  if (!text) return [];
  const parts = [];
  let current = "";
  let depth = 0;
  for (const ch of text) {
    if (ch === "{") depth += 1;
    if (ch === "}") depth = Math.max(0, depth - 1);
    if (ch === delimiter && depth === 0) {
      parts.push(current.trim());
      current = "";
      continue;
    }
    current += ch;
  }
  if (current.trim() || parts.length) {
    parts.push(current.trim());
  }
  return parts.filter(part => part !== "");
}

function parseBuilderLayout(rawText) {
  if (!rawText || !rawText.trim()) return [];
  const items = [];
  let depth = 0;
  let start = -1;
  for (let i = 0; i < rawText.length; i += 1) {
    const ch = rawText[i];
    if (ch === "{") {
      if (depth === 0) start = i + 1;
      depth += 1;
      continue;
    }
    if (ch === "}") {
      depth -= 1;
      if (depth === 0 && start >= 0) {
        const block = rawText.slice(start, i).trim();
        if (!block) { start = -1; continue; }
        if (block === "separator") {
          items.push({ type: "separator" });
        } else if (block.startsWith("display:")) {
          const ids = block.slice("display:".length).split(",").map(part => part.trim()).filter(Boolean);
          items.push({ type: "display", item_ids: ids });
        } else if (block.startsWith("b:")) {
          const remainder = block.slice(2);
          const parts = splitTopLevel(remainder);
          const id = parts[0] || `button-${items.length}`;
          const label = parts[1] || id;
          const style = (parts[2] || "secondary").trim() || "secondary";
          const action = (parts[3] || "disabled").trim() || "disabled";
          const cleanedAction = action.replace(/^\{/, "").replace(/\}$/, "");
          items.push({
            id: id.trim(),
            label: label.trim(),
            style: style === "disabled" ? "secondary" : style,
            action: cleanedAction || "disabled",
            data: {},
          });
        }
        start = -1;
      }
    }
  }
  return items;
}

function renderBuilderLayoutPreview() {
  const rawText = document.getElementById("builder-layout")?.value || "";
  const preview = document.getElementById("preview-btns");
  if (!preview) return;
  preview.innerHTML = "";

  const items = parseBuilderLayout(rawText);
  if (!items.length) {
    preview.innerHTML = "<p class='builder-empty'>add a button layout to preview it.</p>";
    return;
  }

  const buttonMap = {};
  items.filter(item => item && item.id).forEach(item => { buttonMap[item.id] = item; });

  const rows = [];
  let currentRow = [];
  const normalized = [];
  for (const item of items) {
    if (!item) continue;
    if (item.type === "separator") {
      normalized.push({ __separator__: true });
      continue;
    }
    if (item.type === "display") {
      const refs = Array.isArray(item.item_ids) ? item.item_ids : [];
      for (const ref of refs) {
        const target = buttonMap[ref];
        if (target) normalized.push(target);
      }
      continue;
    }
    normalized.push(item);
  }

  for (const item of normalized) {
    if (item && item.__separator__) {
      if (currentRow.length) { rows.push(currentRow); currentRow = []; }
      continue;
    }
    if (currentRow.length >= 5) {
      rows.push(currentRow);
      currentRow = [];
    }
    currentRow.push(item);
  }
  if (currentRow.length) rows.push(currentRow);

  rows.forEach(row => {
    const rowEl = document.createElement("div");
    rowEl.className = "button-row";
    row.forEach(item => {
      const btn = document.createElement("button");
      btn.type = "button";
      const styleClass = item.style === "danger" ? "danger" : item.style === "primary" ? "primary" : item.style === "success" ? "success" : "secondary";
      btn.className = `button button-${styleClass}`;
      btn.textContent = item.label || item.id || "button";
      btn.disabled = String(item.action || "").toLowerCase() === "disabled" || item.style === "disabled";
      rowEl.appendChild(btn);
    });
    preview.appendChild(rowEl);
  });
}

function buildBuilderContainerItems() {
  const items = parseBuilderLayout(document.getElementById("builder-layout")?.value || "");
  const buttonMap = {};
  const result = [];
  const order = [];

  for (const item of items) {
    if (!item || item.type === "separator") continue;
    if (item.type === "display") {
      for (const ref of item.item_ids || []) {
        if (!buttonMap[ref]) buttonMap[ref] = true;
        if (!order.includes(ref)) order.push(ref);
      }
      continue;
    }
    if (!item.id) continue;
    buttonMap[item.id] = item;
    if (!order.includes(item.id)) order.push(item.id);
  }

  for (const id of order) {
    const item = buttonMap[id];
    if (!item) continue;
    const action = String(item.action || "").trim();
    let normalizedAction = action;
    let data = {};
    if (action === "disabled") {
      normalizedAction = "disabled";
    } else if (action.startsWith("role:add:")) {
      normalizedAction = "grant_role";
    }
    result.push({
      id: String(item.id),
      label: String(item.label || item.id),
      style: String(item.style || "secondary"),
      action: normalizedAction,
      data,
    });
  }

  return result;
}

async function saveBuilderMessage(postAfter = false) {
  if (!state.guild) {
    toast("select a server first", "err");
    return;
  }
  const name = document.getElementById("builder-name")?.value.trim() || "";
  const content = document.getElementById("builder-content")?.value || "";
  const containerName = name;
  const channelValue = document.getElementById("builder-channel")?.value || "";

  if (!name) {
    toast("message name is required", "err");
    return;
  }
  if (!content.trim()) {
    toast("message text is required", "err");
    return;
  }

  const layoutItems = buildBuilderContainerItems();
  if (layoutItems.length) {
    const containerResult = await api(`/api/guild/${state.guild.id}/containers`, {
      method: "POST",
      body: JSON.stringify({ name: containerName, items: layoutItems, accent_color: null }),
    });
    if (!containerResult?.ok) {
      toast(containerResult?.error || "failed to save button layout", "err");
      return;
    }
  }

  const messageResult = await api(`/api/guild/${state.guild.id}/messages`, {
    method: "POST",
    body: JSON.stringify({
      name,
      content,
      action: "none",
      container: layoutItems.length ? containerName : null,
    }),
  });

  if (!messageResult?.ok) {
    toast(messageResult?.error || "failed to save message", "err");
    return;
  }

  if (postAfter) {
    if (!channelValue) {
      toast("pick a channel first", "err");
      return;
    }
    const postResult = await api(`/api/guild/${state.guild.id}/messages/${encodeURIComponent(name)}/send`, {
      method: "POST",
      body: JSON.stringify({ channel_id: Number(channelValue) }),
    });
    if (!postResult?.ok) {
      toast(postResult?.error || "failed to post message", "err");
      return;
    }
    toast("message posted");
  } else {
    toast("message saved");
  }

  await loadSavedMessages();
}

async function loadSavedMessages() {
  if (!state.guild) return;
  const messages = await api(`/api/guild/${state.guild.id}/messages`);
  const list = document.getElementById("saved-messages-list");
  if (list) list.textContent = messages?.length ? `${messages.length} saved message(s)` : "no saved messages yet.";
}

function signOut() {
  clearToken();
  state.guild = null;
  showSignedOut();
}

async function init() {
  const hash = new URLSearchParams(window.location.hash.substring(1));
  if (hash.has("access_token")) {
    const token = hash.get("access_token");
    const expiresIn = Number(hash.get("expires_in") || 604800);
    saveToken(token, expiresIn);
    history.replaceState({}, document.title, window.location.pathname);
  }
  state.token = loadToken();
  if (state.token) { state.user = await fetchCurrentUser(); if (state.user) { showDashboard(); await loadGuilds(); } else signOut(); }
  else showSignedOut();
  document.getElementById("logout-button").addEventListener("click", signOut);
  document.querySelectorAll(".dash-tab").forEach(tab => tab.addEventListener("click", () => state.guild || tab.dataset.panel === "servers" ? showPanel(tab.dataset.panel) : toast("select a server first", "err")));
  document.getElementById("save-config")?.addEventListener("click", saveConfig);
  document.getElementById("save-moderation")?.addEventListener("click", saveModeration);
  document.getElementById("create-ticket-panel")?.addEventListener("click", createTicketPanel);
  document.getElementById("builder-render-layout")?.addEventListener("click", renderBuilderLayoutPreview);
  document.getElementById("builder-layout")?.addEventListener("input", renderBuilderLayoutPreview);
  document.getElementById("builder-save")?.addEventListener("click", () => saveBuilderMessage(false));
  document.getElementById("builder-post")?.addEventListener("click", () => saveBuilderMessage(true));
  if (state.textChannels?.length) fillSelect(document.getElementById("builder-channel"), state.textChannels);
}

init();