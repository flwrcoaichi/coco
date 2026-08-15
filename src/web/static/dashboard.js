





const API_BASE = window.COCO_API_BASE || "";


const state = {
  token: null,
  user: null,       
  guild: null,
  roles: [],
  textChannels: [],
};


let _toastTimer = null;
function toast(msg, kind = "ok") {
  const el = document.getElementById("toast");
  el.textContent = msg;
  el.className = `show ${kind}`;
  clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => el.classList.remove("show"), 3000);
}


function saveToken(token, expiresIn = 604800) {
  localStorage.setItem("coco_token", token);
  localStorage.setItem("coco_token_exp", String(Date.now() + expiresIn * 1000));
}
function loadToken() {
  const t = localStorage.getItem("coco_token");
  const exp = Number(localStorage.getItem("coco_token_exp") || 0);
  if (!t || Date.now() > exp) { clearToken(); return null; }
  return t;
}
function clearToken() {
  localStorage.removeItem("coco_token");
  localStorage.removeItem("coco_token_exp");
}






function safeParseJson(text) {
  
  const safe = text.replace(/:\s*(\d{16,})/g, (_, n) => `: "${n}"`);
  return JSON.parse(safe);
}

async function api(path, options = {}) {
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      Authorization: `Bearer ${state.token}`,
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  });
  if (res.status === 401) {
    clearToken();
    showSignedOut();
    return null;
  }
  const text = await res.text();
  try { return safeParseJson(text); } catch { return null; }
}


const CONFIG_FIELDS = [
  { key: "moderator_role",      input: "select", source: "roles" },
  { key: "admin_role",          input: "select", source: "roles" },
  { key: "member_role",         input: "select", source: "roles" },
  { key: "image_role",          input: "select", source: "roles" },
  { key: "music_role",          input: "select", source: "roles" },
  { key: "announcement_channel",input: "select", source: "text_channels" },
  { key: "announcement_role",   input: "select", source: "roles" },
  { key: "join_channel",        input: "select", source: "text_channels" },
  { key: "join_messages",       input: "lines" },
  { key: "leave_channel",       input: "select", source: "text_channels" },
  { key: "leave_messages",      input: "lines" },
  { key: "widget_enabled",      input: "checkbox" },
];
const MODERATION_FIELDS = [
  { key: "mute_channel",                 input: "select", source: "text_channels" },
  { key: "lockdown_include_member_role", input: "checkbox" },
  { key: "require_confirm",              input: "checkbox" },
  { key: "warn_dm",        input: "lines" },
  { key: "warn_channel",   input: "lines" },
  { key: "kick_dm",        input: "lines" },
  { key: "kick_channel",   input: "lines" },
  { key: "ban_dm",         input: "lines" },
  { key: "ban_channel",    input: "lines" },
  { key: "mute_dm",        input: "lines" },
  { key: "mute_channel_msg",input: "lines" },
];

function fillSelect(select, items, selected) {
  if (!select) return;
  select.innerHTML = "<option value=''>— none —</option>";
  
  const sel = selected !== null && selected !== undefined ? String(selected) : "";
  items.forEach(item => {
    const opt = document.createElement("option");
    opt.value = String(item.id);
    opt.textContent = item.name;
    if (String(item.id) === sel) opt.selected = true;
    select.appendChild(opt);
  });
}

function loadFields(root, fields, data) {
  const sources = { roles: state.roles, text_channels: state.textChannels };
  fields.forEach(({ key, input, source }) => {
    const wrap = root.querySelector(`[data-field="${key}"]`);
    if (!wrap) return;
    const value = data[key];
    if (input === "select") {
      fillSelect(wrap.querySelector("select"), sources[source] || [], value);
    } else if (input === "checkbox") {
      const cb = wrap.querySelector("input[type=checkbox]");
      if (cb) cb.checked = Boolean(value);
    } else if (input === "lines") {
      const ta = wrap.querySelector("textarea");
      if (ta) ta.value = Array.isArray(value) ? value.join("\n") : (value || "");
    } else {
      const inp = wrap.querySelector("input");
      if (inp) inp.value = value || "";
    }
  });
}

function saveFields(root, fields) {
  const payload = {};
  fields.forEach(({ key, input }) => {
    const wrap = root.querySelector(`[data-field="${key}"]`);
    if (!wrap) return;
    if (input === "select") {
      payload[key] = wrap.querySelector("select").value || null;
    } else if (input === "checkbox") {
      payload[key] = wrap.querySelector("input[type=checkbox]").checked;
    } else if (input === "lines") {
      payload[key] = wrap.querySelector("textarea").value.split("\n").map(l => l.trim()).filter(Boolean);
    } else {
      payload[key] = wrap.querySelector("input").value || null;
    }
  });
  return payload;
}


function showPanel(name) {
  document.querySelectorAll("[data-panel-id]").forEach(el => {
    el.classList.toggle("active", el.dataset.panelId === name);
  });
  document.querySelectorAll(".dash-tab").forEach(el => {
    el.classList.toggle("active", el.dataset.panel === name);
  });
  if (name === "tickets")  loadTicketPanels();
  if (name === "moderation") loadModeration();
  if (name === "twitch")   loadTwitchSettings();
  if (name === "builder")  loadSavedMessages();
}


function parseOauthHash() {
  if (!window.location.hash) return null;
  const params = new URLSearchParams(window.location.hash.substring(1));
  if (!params.has("access_token")) return null;
  history.replaceState({}, document.title, window.location.pathname);
  const token = params.get("access_token");
  const expiresIn = Number(params.get("expires_in") || 604800);
  saveToken(token, expiresIn);
  return token;
}

function showSignedOut() {
  document.getElementById("signed-out-panel").style.display = "";
  document.getElementById("dash-tabs").hidden = true;
  document.getElementById("session-bar").hidden = true;
  document.getElementById("login-link").hidden = false;
  document.getElementById("logout-button").hidden = true;
  document.querySelectorAll("[data-panel-id]").forEach(el => el.classList.remove("active"));
}

function showDashboard() {
  document.getElementById("signed-out-panel").style.display = "none";
  document.getElementById("dash-tabs").hidden = false;
  document.getElementById("session-bar").hidden = false;
  document.getElementById("login-link").hidden = true;
  document.getElementById("logout-button").hidden = false;
  if (state.user) {
    const avatarEl = document.getElementById("user-avatar");
    if (state.user.avatar) {
      avatarEl.src = `https://cdn.discordapp.com/avatars/${state.user.id}/${state.user.avatar}.png?size=64`;
      avatarEl.hidden = false;
    }
  }
}

async function fetchCurrentUser() {
  const res = await fetch("https://discord.com/api/v10/users/@me", {
    headers: { Authorization: `Bearer ${state.token}` },
  });
  if (res.status !== 200) return null;
  return res.json();
}

function signOut() {
  clearToken();
  state.token = null;
  state.user = null;
  state.guild = null;
  showSignedOut();
}


async function loadGuilds() {
  const guilds = await api("/api/guilds");
  if (!guilds) return;
  const list = document.getElementById("guild-list");
  list.innerHTML = "";
  if (!guilds.length) {
    list.innerHTML = "<p>no servers found where you have admin permissions and coco is installed.</p>";
    return;
  }
  guilds.forEach(guild => {
    const btn = document.createElement("button");
    btn.className = "button button-secondary";
    btn.textContent = guild.name;
    btn.addEventListener("click", () => selectGuild(guild));
    list.appendChild(btn);
  });
  showPanel("servers");
}

async function selectGuild(guild) {
  state.guild = guild;
  document.getElementById("guild-name").textContent = guild.name;

  
  const [rolesData, channelsData] = await Promise.all([
    api(`/api/guild/${guild.id}/roles`),
    api(`/api/guild/${guild.id}/channels`),
  ]);
  state.roles = rolesData || [];
  state.textChannels = (channelsData || []).filter(c => c.type === "text");

  await loadConfigPanel();
  showPanel("config");
}

async function loadConfigPanel() {
  const config = await api(`/api/guild/${state.guild.id}/config`);
  if (!config) return;
  const root = document.getElementById("config-fields");
  loadFields(root, CONFIG_FIELDS, config);

  
  fillSelect(document.getElementById("ticket-panel-channel"), state.textChannels, "");
  fillSelect(document.getElementById("ticket-panel-staff-role"), state.roles, "");
  
  fillSelect(document.getElementById("builder-channel"), state.textChannels, "");

  renderWidgetPreview(state.guild.id, Boolean(config.widget_enabled));
}

function renderWidgetPreview(guildId, enabled) {
  const el = document.getElementById("widget-preview");
  el.innerHTML = "";
  if (!enabled) return;
  const iframe = document.createElement("iframe");
  iframe.src = `https://discord.com/widget?id=${guildId}&theme=dark`;
  iframe.width = "350"; iframe.height = "500";
  iframe.allowTransparency = "true"; iframe.frameBorder = "0";
  iframe.sandbox = "allow-popups allow-popups-to-escape-sandbox allow-same-origin allow-scripts";
  el.appendChild(iframe);
}


async function saveConfig() {
  const payload = saveFields(document.getElementById("config-fields"), CONFIG_FIELDS);
  const result = await api(`/api/guild/${state.guild.id}/config`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
  if (result?.ok) {
    toast("settings saved");
    renderWidgetPreview(state.guild.id, Boolean(payload.widget_enabled));
  } else {
    toast(result?.error || "failed to save", "err");
  }
}


async function loadModeration() {
  if (!state.guild) return;
  const mod = await api(`/api/guild/${state.guild.id}/moderation`);
  if (!mod) return;
  loadFields(document.getElementById("moderation-fields"), MODERATION_FIELDS, mod);
}

async function saveModeration() {
  const payload = saveFields(document.getElementById("moderation-fields"), MODERATION_FIELDS);
  const result = await api(`/api/guild/${state.guild.id}/moderation`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
  result?.ok ? toast("moderation settings saved") : toast(result?.error || "failed", "err");
}


async function loadTicketPanels() {
  if (!state.guild) return;
  const panels = await api(`/api/guild/${state.guild.id}/ticket_panels`);
  if (!panels) return;
  const list = document.getElementById("ticket-panels-list");
  list.innerHTML = "";
  if (!panels.length) { list.innerHTML = "<p style='color:var(--ink-soft)'>no panels yet.</p>"; return; }
  panels.forEach(p => {
    const card = document.createElement("div");
    card.className = "panel-card";
    card.innerHTML = `<strong>${escHtml(p.title)}</strong><div style="font-size:15px;color:var(--ink-soft)">${escHtml(p.description)}</div><div style="font-size:14px;margin-top:4px">channel: <code>${p.channel_id}</code></div>`;
    list.appendChild(card);
  });
}

async function createTicketPanel() {
  if (!state.guild) return;
  const payload = {
    channel_id: document.getElementById("ticket-panel-channel").value || null,
    staff_role_id: document.getElementById("ticket-panel-staff-role").value || null,
    title: document.getElementById("ticket-panel-title").value || "support",
    description: document.getElementById("ticket-panel-description").value || "click below to open a ticket",
  };
  if (!payload.channel_id) { toast("pick a channel first", "err"); return; }
  const result = await api(`/api/guild/${state.guild.id}/ticket_panels`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
  if (result?.ok) { toast("ticket panel posted!"); loadTicketPanels(); }
  else toast(result?.error || "failed", "err");
}





async function loadTwitchSettings() {
  if (!state.guild) return;
  
  
  
  
  
  
  const [settings, overrides, cmds] = await Promise.all([
    api(`/api/guild/${state.guild.id}/twitch_chat`),
    api(`/api/guild/${state.guild.id}/twitch_chat/shoutout_overrides`),
    api(`/api/guild/${state.guild.id}/twitch_chat/commands`),
  ]);

  if (settings && !settings.error) {
    document.getElementById("shoutout-message").value = settings.shoutout_message || "";
  }
  renderOverrides(overrides?.error ? [] : (overrides || []));
  renderCmds(cmds?.error ? [] : (cmds || []));
}

function renderOverrides(overrides) {
  const list = document.getElementById("shoutout-override-list");
  list.innerHTML = "";
  overrides.forEach(o => {
    const row = document.createElement("div");
    row.className = "override-row";
    row.innerHTML = `
      <input type="text" value="${escHtml(o.twitch_login)}" readonly style="background:var(--cream-deep)" />
      <input type="text" value="${escHtml(o.message)}" data-login="${escAttr(o.twitch_login)}" class="override-msg" />
      <button class="button button-danger remove-btn" data-login="${escAttr(o.twitch_login)}">✕</button>
    `;
    row.querySelector(".remove-btn").addEventListener("click", () => removeOverride(o.twitch_login));
    list.appendChild(row);
  });
}

function renderCmds(cmds) {
  const list = document.getElementById("cmd-list");
  list.innerHTML = "";
  cmds.forEach(c => {
    const row = document.createElement("div");
    row.className = "cmd-row";
    row.innerHTML = `
      <input type="text" value="${escHtml(c.trigger)}" readonly style="background:var(--cream-deep)" />
      <input type="text" value="${escHtml(c.template)}" readonly style="background:var(--cream-deep)" />
      <button class="button button-danger remove-btn" data-trigger="${escAttr(c.trigger)}">✕</button>
    `;
    row.querySelector(".remove-btn").addEventListener("click", () => removeCmd(c.trigger));
    list.appendChild(row);
  });
}

async function saveShoutoutMsg() {
  if (!state.guild) return;
  const msg = document.getElementById("shoutout-message").value.trim();
  const result = await api(`/api/guild/${state.guild.id}/twitch_chat`, {
    method: "POST",
    body: JSON.stringify({ shoutout_message: msg }),
  });
  result?.ok ? toast("shoutout message saved") : toast(result?.error || "failed — make sure the bot has this API endpoint", "err");
}

async function addOverride() {
  if (!state.guild) return;
  const user = document.getElementById("new-override-user").value.trim();
  const msg  = document.getElementById("new-override-msg").value.trim();
  if (!user || !msg) { toast("fill in both fields", "err"); return; }
  const result = await api(`/api/guild/${state.guild.id}/twitch_chat/shoutout_overrides`, {
    method: "POST",
    body: JSON.stringify({ twitch_login: user, message: msg }),
  });
  if (result?.ok) {
    toast(`override saved for ${user}`);
    document.getElementById("new-override-user").value = "";
    document.getElementById("new-override-msg").value = "";
    loadTwitchSettings();
  } else toast(result?.error || "failed", "err");
}

async function removeOverride(login) {
  if (!state.guild) return;
  const result = await api(`/api/guild/${state.guild.id}/twitch_chat/shoutout_overrides/${encodeURIComponent(login)}`, {
    method: "DELETE",
  });
  result?.ok ? (toast(`removed ${login}`), loadTwitchSettings()) : toast("failed", "err");
}

async function addCmd() {
  if (!state.guild) return;
  const trigger  = document.getElementById("new-cmd-trigger").value.trim();
  const template = document.getElementById("new-cmd-template").value.trim();
  if (!trigger || !template) { toast("fill in both fields", "err"); return; }
  const result = await api(`/api/guild/${state.guild.id}/twitch_chat/commands`, {
    method: "POST",
    body: JSON.stringify({ trigger, template }),
  });
  if (result?.ok) {
    toast(`command ${trigger} added`);
    document.getElementById("new-cmd-trigger").value = "";
    document.getElementById("new-cmd-template").value = "";
    loadTwitchSettings();
  } else toast(result?.error || "failed", "err");
}

async function removeCmd(trigger) {
  if (!state.guild) return;
  const result = await api(`/api/guild/${state.guild.id}/twitch_chat/commands/${encodeURIComponent(trigger)}`, {
    method: "DELETE",
  });
  result?.ok ? (toast(`removed ${trigger}`), loadTwitchSettings()) : toast("failed", "err");
}



let builderButtons = [];

function renderBuilderPreview() {
  const raw = document.getElementById("builder-content").value;
  const text = raw.replace(/\\n/g, "\n");
  const previewText = document.getElementById("preview-text");
  previewText.textContent = text || "your message will appear here";

  const hexInput = document.getElementById("builder-accent").value.trim();
  const color = /^#?[0-9a-fA-F]{6}$/.test(hexInput)
    ? "#" + hexInput.replace("#", "")
    : "#5865F2";
  previewText.style.borderLeftColor = color;

  const btnContainer = document.getElementById("preview-btns");
  btnContainer.innerHTML = "";
  builderButtons.forEach(btn => {
    const b = document.createElement("button");
    b.className = `preview-btn ${btn.style}`;
    b.textContent = btn.label || "button";
    b.disabled = true;
    btnContainer.appendChild(b);
  });
}

function addBuilderButton() {
  builderButtons.push({ label: "", style: "secondary", action: "grant_role", roleId: "" });
  renderBtnList();
  renderBuilderPreview();
}

function removeBuilderButton(i) {
  builderButtons.splice(i, 1);
  renderBtnList();
  renderBuilderPreview();
}

function renderBtnList() {
  const list = document.getElementById("btn-list");
  list.innerHTML = "";
  builderButtons.forEach((btn, i) => {
    const row = document.createElement("div");
    row.className = "btn-item-row";
    row.innerHTML = `
      <div class="field-group">
        <label>label</label>
        <input type="text" placeholder="click me" value="${escAttr(btn.label)}" data-i="${i}" data-prop="label" />
      </div>
      <div class="field-group">
        <label>style</label>
        <select data-i="${i}" data-prop="style">
          ${["primary","secondary","success","danger"].map(s =>
            `<option value="${s}" ${btn.style===s?"selected":""}>${s}</option>`).join("")}
        </select>
      </div>
      <div class="field-group">
        <label>action</label>
        <select data-i="${i}" data-prop="action">
          <option value="grant_role" ${btn.action==="grant_role"?"selected":""}>toggle role</option>
          <option value="give_role"  ${btn.action==="give_role"?"selected":""}>give role (one-way)</option>
        </select>
      </div>
      <button class="button remove-btn" data-remove="${i}">✕</button>
    `;

    
    const roleRow = document.createElement("div");
    roleRow.style.cssText = "grid-column:1/-1;display:grid;grid-template-columns:1fr;gap:6px;margin-top:-6px";
    const roleGroup = document.createElement("div");
    roleGroup.className = "field-group wide";
    const roleLabel = document.createElement("label");
    roleLabel.textContent = "role";
    const roleSelect = document.createElement("select");
    roleSelect.dataset.i = i;
    roleSelect.dataset.prop = "roleId";
    fillSelect(roleSelect, state.roles, btn.roleId);
    roleGroup.appendChild(roleLabel);
    roleGroup.appendChild(roleSelect);
    roleRow.appendChild(roleGroup);
    row.appendChild(roleRow);

    row.querySelectorAll("input,select").forEach(el => {
      el.addEventListener("input", () => {
        if (el.dataset.prop) builderButtons[el.dataset.i][el.dataset.prop] = el.value;
        renderBuilderPreview();
      });
    });
    row.querySelector(`[data-remove]`).addEventListener("click", () => removeBuilderButton(i));
    list.appendChild(row);
  });
}

async function loadSavedMessages() {
  if (!state.guild) return;
  const msgs = await api(`/api/guild/${state.guild.id}/messages`);
  const list = document.getElementById("saved-messages-list");
  list.innerHTML = "";
  if (!msgs || msgs.error || !msgs.length) {
    list.innerHTML = "<p style='color:var(--ink-soft)'>no saved messages yet.</p>";
    return;
  }
  msgs.forEach(m => {
    const card = document.createElement("div");
    card.className = "panel-card";
    const posted = m.message_id ? `posted in <code>${m.channel_id}</code>` : "not posted yet";
    card.innerHTML = `<strong>${escHtml(m.name)}</strong> — ${posted}
      <div style="font-size:14px;margin-top:4px;color:var(--ink-soft)">${escHtml((m.content||"").substring(0,80))}${m.content?.length>80?"…":""}</div>`;
    list.appendChild(card);
  });
}

async function builderPost() {
  await builderSubmit(true);
}
async function builderSave() {
  await builderSubmit(false);
}

async function builderSubmit(doPost) {
  if (!state.guild) return;
  const name    = document.getElementById("builder-name").value.trim();
  const content = document.getElementById("builder-content").value.trim().replace(/\\n/g, "\n");
  const accent  = document.getElementById("builder-accent").value.trim();
  const channelId = document.getElementById("builder-channel").value;

  if (!name)    { toast("give this message a name", "err"); return; }
  if (!content) { toast("message can't be empty", "err"); return; }
  if (doPost && !channelId) { toast("pick a channel to post to", "err"); return; }

  
  let containerName = null;
  if (builderButtons.length) {
    containerName = `__builder_${name}`;
    const items = builderButtons.map(btn => ({
      label:  btn.label || "button",
      style:  btn.style,
      action: btn.action,
      data:   btn.roleId ? { role_id: parseInt(btn.roleId) } : {},
    }));
    const accentInt = /^#?[0-9a-fA-F]{6}$/.test(accent)
      ? parseInt(accent.replace("#",""), 16) : 0x5865F2;
    await api(`/api/guild/${state.guild.id}/containers`, {
      method: "POST",
      body: JSON.stringify({ name: containerName, items, accent_color: accentInt }),
    });
  }

  
  const action = "none";
  const saveResult = await api(`/api/guild/${state.guild.id}/messages`, {
    method: "POST",
    body: JSON.stringify({ name, content, action, container: containerName }),
  });
  if (!saveResult?.ok) { toast(saveResult?.error || "failed to save message", "err"); return; }

  
  if (doPost) {
    const postResult = await api(`/api/guild/${state.guild.id}/messages/${encodeURIComponent(name)}/send`, {
      method: "POST",
      body: JSON.stringify({ channel_id: channelId }),
    });
    if (postResult?.ok) {
      toast("message posted!");
    } else {
      toast(postResult?.error || "saved but posting failed", "err");
    }
  } else {
    toast("message saved");
  }
  loadSavedMessages();
}


async function executeAction(action) {
  if (!state.guild) { toast("select a server first", "err"); return; }
  const body = {};
  if (action === "play") {
    body.url = prompt("enter a YouTube URL:");
    if (!body.url) return;
  }
  const result = await api(`/api/guild/${state.guild.id}/actions/${action}`, {
    method: "POST",
    body: JSON.stringify(body),
  });
  result?.ok ? toast(result.message || "done") : toast(result?.error || "action failed", "err");
}


function escHtml(s) {
  if (!s) return "";
  return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
}
function escAttr(s) { return escHtml(s); }


async function init() {
  
  const hashToken = parseOauthHash();
  if (hashToken) state.token = hashToken;

  
  if (!state.token) state.token = loadToken();

  if (state.token) {
    
    const user = await fetchCurrentUser();
    if (!user) {
      
      clearToken();
      state.token = null;
      showSignedOut();
      return;
    }
    state.user = user;
    showDashboard();
    await loadGuilds();
  } else {
    showSignedOut();
  }

  
  document.getElementById("logout-button").addEventListener("click", signOut);
  document.querySelectorAll(".dash-tab").forEach(tab => {
    tab.addEventListener("click", () => {
      if (!state.guild && tab.dataset.panel !== "servers") {
        toast("select a server first", "err"); return;
      }
      showPanel(tab.dataset.panel);
    });
  });

  document.getElementById("save-config")       ?.addEventListener("click", saveConfig);
  document.getElementById("save-moderation")   ?.addEventListener("click", saveModeration);
  document.getElementById("create-ticket-panel")?.addEventListener("click", createTicketPanel);
  document.getElementById("save-shoutout-msg") ?.addEventListener("click", saveShoutoutMsg);
  document.getElementById("add-override")      ?.addEventListener("click", addOverride);
  document.getElementById("add-cmd")           ?.addEventListener("click", addCmd);
  document.getElementById("add-btn")           ?.addEventListener("click", addBuilderButton);
  document.getElementById("builder-post")      ?.addEventListener("click", builderPost);
  document.getElementById("builder-save")      ?.addEventListener("click", builderSave);

  
  ["builder-content", "builder-accent"].forEach(id => {
    document.getElementById(id)?.addEventListener("input", renderBuilderPreview);
  });

  
  document.querySelectorAll(".tile-action").forEach(btn => {
    btn.addEventListener("click", () => executeAction(btn.dataset.action));
  });
}

init();