const API_BASE = window.COCO_API_BASE || "";
const state = { token: null, user: null, guild: null, roles: [], textChannels: [], messages: [] };
let toastTimer;
let lastError = "";

const $ = id => document.getElementById(id);
const sleep = ms => new Promise(r => setTimeout(r, ms));

function toast(message, kind = "ok") {
  const element = $("toast");
  element.textContent = message;
  element.className = `show ${kind}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => element.classList.remove("show"), 3500);
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
  if (!token) { showSignedOut(); return null; }
  state.token = token;
  lastError = "";
  for (let attempt = 0; attempt < 3; attempt++) {
    let res;
    try {
      res = await fetch(`${API_BASE}${path}`, {
        ...options,
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json", ...(options.headers || {}) },
      });
    } catch {
      lastError = "network error";
      return null;
    }
    if ([429, 502, 503].includes(res.status) && attempt < 2) { await sleep(600 * (attempt + 1)); continue; }
    let body = null;
    try { body = await res.json(); } catch {}
    if (!res.ok) {
      lastError = body?.error || `request failed (${res.status})`;
      console.error(`API ${res.status} ${path}:`, lastError);
      if (res.status === 401) { signOut(); toast("session expired, log in again", "err"); }
      return null;
    }
    return body;
  }
  return null;
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

function fillSelect(select, items, selected, placeholder = "- none -") {
  if (!select) return;
  select.innerHTML = "";
  const none = document.createElement("option");
  none.value = "";
  none.textContent = placeholder;
  select.appendChild(none);
  items.forEach(item => {
    const option = document.createElement("option");
    option.value = String(item.id);
    option.textContent = item.name;
    select.appendChild(option);
  });
  select.value = selected == null ? "" : String(selected);
}

function loadFields(root, fields, data) {
  fields.forEach(([key, type, source]) => {
    const wrapper = root.querySelector(`[data-field="${key}"]`);
    if (!wrapper) return;
    const value = data[key];
    if (type === "select") fillSelect(wrapper.querySelector("select"), source === "roles" ? state.roles : state.textChannels, value);
    if (type === "checkbox") wrapper.querySelector("input").checked = Boolean(value);
    if (type === "lines") wrapper.querySelector("textarea").value = Array.isArray(value) ? value.join("\n") : (value || "");
  });
}

function saveFields(root, fields) {
  const payload = {};
  fields.forEach(([key, type]) => {
    const wrapper = root.querySelector(`[data-field="${key}"]`);
    if (!wrapper) return;
    if (type === "select") payload[key] = wrapper.querySelector("select").value || null;
    if (type === "checkbox") payload[key] = wrapper.querySelector("input").checked;
    if (type === "lines") payload[key] = wrapper.querySelector("textarea").value.split("\n").map(l => l.trim()).filter(Boolean);
  });
  return payload;
}

function showPanel(name) {
  document.querySelectorAll("[data-panel-id]").forEach(p => p.classList.toggle("active", p.dataset.panelId === name));
  document.querySelectorAll(".dash-tab").forEach(t => t.classList.toggle("active", t.dataset.panel === name));
  if (name === "moderation") loadModeration();
  if (name === "tickets") loadTicketPanels();
  if (name === "builder") loadSavedMessages();
}

function showSignedOut() {
  $("signed-out-panel").style.display = "";
  $("dash-tabs").hidden = true;
  $("session-bar").hidden = true;
  $("login-link").hidden = false;
  $("logout-button").hidden = true;
  document.querySelectorAll("[data-panel-id]").forEach(p => p.classList.remove("active"));
}

function showDashboard() {
  $("signed-out-panel").style.display = "none";
  $("dash-tabs").hidden = false;
  $("session-bar").hidden = false;
  $("login-link").hidden = true;
  $("logout-button").hidden = false;
  const avatar = $("user-avatar");
  if (state.user?.avatar) avatar.src = `https://cdn.discordapp.com/avatars/${state.user.id}/${state.user.avatar}.png?size=64`;
}

async function fetchCurrentUser() {
  const res = await fetch("https://discord.com/api/v10/users/@me", { headers: { Authorization: `Bearer ${state.token}` } });
  return res.status === 200 ? res.json() : null;
}

async function loadGuilds() {
  const guilds = await api("/api/guilds");
  const list = $("guild-list");
  list.innerHTML = "";
  if (!guilds?.length) {
    list.innerHTML = `<p>${lastError || "no servers found where you have admin permissions and niskbot is installed."}</p>`;
    return;
  }
  guilds.forEach(guild => {
    const button = document.createElement("button");
    button.className = "button button-secondary";
    button.textContent = guild.name;
    button.addEventListener("click", () => selectGuild(guild));
    list.appendChild(button);
  });
  showPanel("servers");
}

async function loadConfig() {
  const config = await api(`/api/guild/${state.guild.id}/config`);
  if (!config) { toast(lastError || "couldn't load settings", "err"); return; }
  loadFields($("config-fields"), configFields, config);
  renderWidget(config.widget_enabled);
}

function renderWidget(enabled) {
  const box = $("widget-preview");
  box.innerHTML = "";
  if (!enabled || !state.guild) return;
  const frame = document.createElement("iframe");
  frame.src = `https://discord.com/widget?id=${state.guild.id}&theme=dark`;
  frame.setAttribute("sandbox", "allow-popups allow-popups-to-escape-sandbox allow-same-origin allow-scripts");
  box.appendChild(frame);
}

async function selectGuild(guild) {
  state.guild = guild;
  $("guild-name").textContent = guild.name;

  const [roles, channels] = await Promise.all([
    api(`/api/guild/${guild.id}/roles`),
    api(`/api/guild/${guild.id}/channels`),
  ]);
  if (!roles || !channels) { toast(lastError || "couldn't load server data", "err"); return; }
  state.roles = roles;
  state.textChannels = channels.filter(c => c.type === "text");

  fillSelect($("ticket-panel-channel"), state.textChannels, null, "- pick a channel -");
  fillSelect($("ticket-panel-staff-role"), state.roles);
  fillSelect($("builder-channel"), state.textChannels, null, "- pick a channel -");
  await loadConfig();
  resetBuilder();
  showPanel("config");
}

async function saveConfig() {
  const result = await api(`/api/guild/${state.guild.id}/config`, { method: "POST", body: JSON.stringify(saveFields($("config-fields"), configFields)) });
  if (!result?.ok) { toast(lastError || "failed to save", "err"); return; }
  await loadConfig();
  toast("settings saved");
}

async function loadModeration() {
  if (!state.guild) return;
  const data = await api(`/api/guild/${state.guild.id}/moderation`);
  if (data) loadFields($("moderation-fields"), moderationFields, data);
  else toast(lastError || "couldn't load moderation settings", "err");
}

async function saveModeration() {
  const result = await api(`/api/guild/${state.guild.id}/moderation`, { method: "POST", body: JSON.stringify(saveFields($("moderation-fields"), moderationFields)) });
  if (!result?.ok) { toast(lastError || "failed to save", "err"); return; }
  await loadModeration();
  toast("moderation settings saved");
}

const channelName = id => state.textChannels.find(c => String(c.id) === String(id))?.name;

async function loadTicketPanels() {
  if (!state.guild) return;
  const panels = await api(`/api/guild/${state.guild.id}/ticket_panels`);
  const list = $("ticket-panels-list");
  list.innerHTML = "";
  if (!panels?.length) { list.textContent = "no panels yet."; return; }
  panels.forEach(panel => {
    const item = document.createElement("div");
    item.className = "panel-card";
    item.textContent = `${panel.title} — #${channelName(panel.channel_id) || panel.channel_id}`;
    list.appendChild(item);
  });
}

async function createTicketPanel() {
  const payload = {
    channel_id: $("ticket-panel-channel").value,
    staff_role_id: $("ticket-panel-staff-role").value || null,
    title: $("ticket-panel-title").value || "support",
    description: $("ticket-panel-description").value || "click below to open a ticket",
  };
  if (!payload.channel_id) { toast("pick a channel first", "err"); return; }
  const result = await api(`/api/guild/${state.guild.id}/ticket_panels`, { method: "POST", body: JSON.stringify(payload) });
  if (result?.ok) { toast("ticket panel posted"); loadTicketPanels(); }
  else toast(lastError || "failed", "err");
}

/* ---------- message builder ---------- */

const STYLES = ["primary", "secondary", "success", "danger"];
const ACTIONS = [["grant_role", "toggle role"], ["give_role", "give role (verify)"], ["disabled", "label only"]];
const DEFAULT_ACCENT = "#5865f2";
const builder = { name: "", content: "", accent: DEFAULT_ACCENT, items: [], editing: false };

const uid = () => Array.from(crypto.getRandomValues(new Uint8Array(4)), b => b.toString(16).padStart(2, "0")).join("");
const hexFromInt = n => `#${Number(n).toString(16).padStart(6, "0")}`;

function el(tag, props = {}, ...kids) {
  const node = document.createElement(tag);
  Object.assign(node, props);
  kids.forEach(k => node.append(k));
  return node;
}

function makeSelect(options, value, onchange) {
  const select = el("select");
  options.forEach(([v, label]) => select.appendChild(el("option", { value: v, textContent: label })));
  select.value = value ?? "";
  select.addEventListener("change", () => onchange(select.value));
  return select;
}

function inlineMd(s) {
  return s
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>")
    .replace(/\*([^*]+)\*/g, "<i>$1</i>")
    .replace(/__([^_]+)__/g, "<u>$1</u>");
}

function renderMd(text) {
  const esc = text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  return esc.split("\n").map(line => {
    if (/^#{1,3} /.test(line)) return `<div class="md-h1">${inlineMd(line.replace(/^#{1,3} /, ""))}</div>`;
    if (/^-# /.test(line)) return `<div class="md-small">${inlineMd(line.slice(3))}</div>`;
    return `<div>${inlineMd(line) || "&nbsp;"}</div>`;
  }).join("");
}

function fillPreview(textEl, btnsEl, containerEl, content, items, accent) {
  textEl.innerHTML = content.trim() ? renderMd(content) : `<span class="md-empty">your message will appear here</span>`;
  containerEl.style.borderLeftColor = accent;
  btnsEl.innerHTML = "";
  let row = null;
  const flush = () => { if (row && row.children.length) btnsEl.appendChild(row); row = null; };
  items.forEach(item => {
    if (item.type === "separator") { flush(); btnsEl.appendChild(el("hr", { className: "preview-sep" })); return; }
    if (item.type === "break") { flush(); return; }
    if (row && row.children.length >= 5) flush();
    if (!row) row = el("div", { className: "preview-row" });
    const off = item.action === "disabled";
    row.appendChild(el("button", { type: "button", className: `preview-btn ${item.style}${off ? " off" : ""}`, textContent: item.label || "button" }));
  });
  flush();
}

function renderPreview() {
  fillPreview($("preview-text"), $("preview-btns"), $("preview-container"), builder.content, builder.items, builder.accent);
}

function moveItem(i, dir) {
  const j = i + dir;
  if (j < 0 || j >= builder.items.length) return;
  [builder.items[i], builder.items[j]] = [builder.items[j], builder.items[i]];
  renderItemList();
}

function controls(i) {
  const up = el("button", { type: "button", textContent: "↑", disabled: i === 0, title: "move up" });
  const down = el("button", { type: "button", textContent: "↓", disabled: i === builder.items.length - 1, title: "move down" });
  const del = el("button", { type: "button", textContent: "✕", className: "del", title: "remove" });
  up.onclick = () => moveItem(i, -1);
  down.onclick = () => moveItem(i, 1);
  del.onclick = () => { builder.items.splice(i, 1); renderItemList(); };
  return el("div", { className: "item-controls" }, up, down, del);
}

function renderItemList() {
  const list = $("btn-list");
  list.innerHTML = "";
  if (!builder.items.length) list.appendChild(el("p", { className: "hint", textContent: "no buttons yet — add one below." }));
  builder.items.forEach((item, i) => {
    if (item.type) {
      const card = el("div", { className: `item-card ${item.type}` });
      card.append(el("span", { className: "item-tag", textContent: item.type === "separator" ? "── separator line ──" : "↵ start new row" }), controls(i));
      list.appendChild(card);
      return;
    }
    const card = el("div", { className: "item-card" });
    const fields = el("div", { className: "item-fields" });
    const label = el("input", { type: "text", value: item.label, placeholder: "button label", maxLength: 80 });
    label.addEventListener("input", () => { item.label = label.value; renderPreview(); });
    const style = makeSelect(STYLES.map(s => [s, s]), item.style, v => { item.style = v; renderPreview(); });
    const action = makeSelect(ACTIONS, item.action, v => { item.action = v; renderItemList(); });
    fields.append(label, style, action);
    if (item.action !== "disabled") {
      const role = makeSelect([["", "- pick a role -"], ...state.roles.map(r => [String(r.id), r.name])], item.role_id, v => { item.role_id = v; });
      role.className = "full";
      fields.appendChild(role);
    }
    card.append(fields, controls(i));
    list.appendChild(card);
  });
  renderPreview();
}

function addButton() {
  builder.items.push({ id: uid(), label: "button", style: "secondary", action: "grant_role", role_id: "" });
  renderItemList();
}
const addMarker = type => { builder.items.push({ type }); renderItemList(); };

function expandLegacy(items) {
  if (!items.some(i => i.type === "display")) return items;
  const byId = Object.fromEntries(items.filter(i => i.id).map(i => [i.id, i]));
  const out = [];
  items.forEach(i => {
    if (i.type === "separator") out.push(i);
    else if (i.type === "display") (i.item_ids || i.items || []).forEach(id => byId[id] && out.push(byId[id]));
  });
  return out;
}

function itemsFromServer(items) {
  return expandLegacy(items || []).map(i => {
    if (i.type === "separator" || i.type === "break") return { type: i.type };
    return { id: i.id, label: i.label || "", style: i.style || "secondary", action: i.action || "disabled", role_id: i.data?.role_id ? String(i.data.role_id) : "" };
  });
}

function serializeItems() {
  const out = [];
  for (const item of builder.items) {
    if (item.type) { out.push({ type: item.type }); continue; }
    if (!item.label.trim()) { toast("every button needs a label", "err"); return null; }
    if (item.action !== "disabled" && !item.role_id) { toast(`"${item.label}" needs a role`, "err"); return null; }
    out.push({
      id: item.id,
      label: item.label.trim(),
      style: item.style,
      action: item.action,
      data: item.action === "disabled" ? {} : { role_id: item.role_id },
    });
  }
  return out;
}

function syncBuilderInputs() {
  $("builder-name").value = builder.name;
  $("builder-name").disabled = builder.editing;
  $("builder-content").value = builder.content;
  $("builder-accent").value = builder.accent;
  $("builder-accent-hex").textContent = builder.accent;
  renderItemList();
}

function resetBuilder() {
  Object.assign(builder, { name: "", content: "", accent: DEFAULT_ACCENT, items: [], editing: false });
  syncBuilderInputs();
}

function editSaved(msg) {
  Object.assign(builder, {
    name: msg.name,
    content: msg.content,
    accent: msg.accent_color != null ? hexFromInt(msg.accent_color) : DEFAULT_ACCENT,
    items: itemsFromServer(msg.items),
    editing: true,
  });
  syncBuilderInputs();
  if (msg.channel_id && channelName(msg.channel_id)) $("builder-channel").value = String(msg.channel_id);
  $("builder-name").scrollIntoView({ behavior: "smooth", block: "center" });
  toast(`editing "${msg.name}"`);
}

async function saveBuilderMessage(postAfter) {
  if (!state.guild) { toast("select a server first", "err"); return; }
  const name = builder.name.trim();
  if (!name) { toast("message name is required", "err"); return; }
  if (!builder.content.trim()) { toast("message text is required", "err"); return; }
  const channelValue = $("builder-channel").value;
  if (postAfter && !channelValue) { toast("pick a channel first", "err"); return; }
  const items = serializeItems();
  if (!items) return;

  const container = await api(`/api/guild/${state.guild.id}/containers`, {
    method: "POST",
    body: JSON.stringify({ name, items, accent_color: parseInt(builder.accent.slice(1), 16) }),
  });
  if (!container?.ok) { toast(lastError || "failed to save buttons", "err"); return; }

  const saved = await api(`/api/guild/${state.guild.id}/messages`, {
    method: "POST",
    body: JSON.stringify({ name, content: builder.content, container: name }),
  });
  if (!saved?.ok) { toast(lastError || "failed to save message", "err"); return; }

  builder.editing = true;
  $("builder-name").disabled = true;

  if (postAfter) {
    const posted = await api(`/api/guild/${state.guild.id}/messages/${encodeURIComponent(name)}/send`, {
      method: "POST",
      body: JSON.stringify({ channel_id: channelValue }),
    });
    if (!posted?.ok) { toast(lastError || "saved, but posting failed", "err"); await loadSavedMessages(); return; }
    toast("message posted");
  } else {
    toast("message saved");
  }
  await loadSavedMessages();
}

async function sendSaved(msg, channelId, update) {
  if (!update && !channelId) { toast("pick a channel first", "err"); return; }
  const result = await api(`/api/guild/${state.guild.id}/messages/${encodeURIComponent(msg.name)}/send`, {
    method: "POST",
    body: JSON.stringify({ channel_id: channelId, update }),
  });
  if (result?.ok) { toast(update ? "posted message updated" : "message posted"); await loadSavedMessages(); }
  else toast(lastError || "failed to send", "err");
}

async function deleteSaved(msg) {
  if (!confirm(`delete "${msg.name}"? the already-posted message stays in discord but its buttons stop working.`)) return;
  const result = await api(`/api/guild/${state.guild.id}/messages/${encodeURIComponent(msg.name)}`, { method: "DELETE" });
  if (result?.ok) {
    if (builder.editing && builder.name === msg.name) resetBuilder();
    toast("message deleted");
    await loadSavedMessages();
  } else toast(lastError || "failed to delete", "err");
}

function renderSavedMessages() {
  const list = $("saved-messages-list");
  list.innerHTML = "";
  if (!state.messages.length) { list.textContent = "no saved messages yet."; return; }
  state.messages.forEach(msg => {
    const posted = Boolean(msg.message_id && String(msg.message_id) !== "0");
    const where = posted ? channelName(msg.channel_id) : null;
    const buttonCount = itemsFromServer(msg.items).filter(i => !i.type).length;

    const head = el("div", { className: "msg-head" },
      el("span", { className: "msg-name", textContent: msg.name }),
      el("span", { className: `msg-status${posted ? " live" : ""}`, textContent: `${buttonCount} button${buttonCount === 1 ? "" : "s"} · ${posted ? `posted in #${where || "unknown"}` : "not posted"}` }));

    const preview = el("div", { className: "msg-preview" });
    const text = el("div", { className: "md" });
    const btns = el("div");
    preview.append(text, btns);
    fillPreview(text, btns, preview, msg.content.length > 300 ? `${msg.content.slice(0, 300)}…` : msg.content, itemsFromServer(msg.items), msg.accent_color != null ? hexFromInt(msg.accent_color) : DEFAULT_ACCENT);

    const chan = el("select");
    fillSelect(chan, state.textChannels, posted ? msg.channel_id : null, "- pick a channel -");
    const actions = el("div", { className: "msg-actions" }, chan);
    const btn = (label, cls, fn) => { const b = el("button", { type: "button", className: `button ${cls}`, textContent: label }); b.onclick = fn; return b; };
    actions.append(btn("send", "button-primary", () => sendSaved(msg, chan.value, false)));
    if (posted) actions.append(btn("update posted", "button-secondary", () => sendSaved(msg, null, true)));
    actions.append(btn("edit", "button-tertiary", () => editSaved(msg)), btn("delete", "button-danger", () => deleteSaved(msg)));

    list.appendChild(el("div", { className: "msg-card" }, head, preview, actions));
  });
}

async function loadSavedMessages() {
  if (!state.guild) return;
  const messages = await api(`/api/guild/${state.guild.id}/messages`);
  if (!messages) { $("saved-messages-list").textContent = lastError || "couldn't load messages."; return; }
  state.messages = messages;
  renderSavedMessages();
}

function signOut() {
  clearToken();
  state.guild = null;
  showSignedOut();
}

async function init() {
  const hash = new URLSearchParams(window.location.hash.substring(1));
  if (hash.has("access_token")) {
    saveToken(hash.get("access_token"), Number(hash.get("expires_in") || 604800));
    history.replaceState({}, document.title, window.location.pathname);
  }
  state.token = loadToken();
  if (state.token) {
    state.user = await fetchCurrentUser();
    if (state.user) { showDashboard(); await loadGuilds(); } else signOut();
  } else showSignedOut();

  $("logout-button").addEventListener("click", signOut);
  document.querySelectorAll(".dash-tab").forEach(tab => tab.addEventListener("click", () =>
    state.guild || tab.dataset.panel === "servers" ? showPanel(tab.dataset.panel) : toast("select a server first", "err")));
  $("save-config").addEventListener("click", saveConfig);
  $("save-moderation").addEventListener("click", saveModeration);
  $("create-ticket-panel").addEventListener("click", createTicketPanel);

  $("builder-name").addEventListener("input", e => { builder.name = e.target.value; });
  $("builder-content").addEventListener("input", e => { builder.content = e.target.value; renderPreview(); });
  $("builder-accent").addEventListener("input", e => { builder.accent = e.target.value; $("builder-accent-hex").textContent = e.target.value; renderPreview(); });
  $("add-btn").addEventListener("click", addButton);
  $("add-sep").addEventListener("click", () => addMarker("separator"));
  $("add-break").addEventListener("click", () => addMarker("break"));
  $("builder-save").addEventListener("click", () => saveBuilderMessage(false));
  $("builder-post").addEventListener("click", () => saveBuilderMessage(true));
  $("builder-reset").addEventListener("click", resetBuilder);
  document.querySelector('[data-field="widget_enabled"] input')?.addEventListener("change", e => renderWidget(e.target.checked));
  renderItemList();
}

init();
