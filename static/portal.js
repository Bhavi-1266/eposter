(() => {
  "use strict";
  const byId = (id) => document.getElementById(id);
  const csrf = document.querySelector('meta[name="csrf-token"]').content;

  document.querySelectorAll("[data-reveal]").forEach((button) => {
    button.addEventListener("click", () => {
      const input = byId(button.dataset.reveal);
      const show = input.type === "password";
      input.type = show ? "text" : "password";
      button.textContent = show ? "Hide" : "Show";
      button.setAttribute("aria-pressed", String(show));
    });
  });

  const login = byId("login-form");
  if (login) {
    login.addEventListener("submit", async (event) => {
      event.preventDefault();
      const button = login.querySelector('[type="submit"]');
      if (button.disabled) return;
      const body = new URLSearchParams(new FormData(login));
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 10000);
      button.disabled = true;
      button.textContent = "Signing in...";
      try {
        const response = await fetch(login.action, {
          method: "POST", body, signal: controller.signal, credentials: "same-origin"
        });
        const html = await response.text();
        if (response.ok && response.redirected) {
          window.location.assign("/");
          return;
        }
        const page = new DOMParser().parseFromString(html, "text/html");
        const notice = page.querySelector(".notice");
        throw new Error(notice ? notice.textContent.trim() : "Sign-in failed. Reload the page and try again.");
      } catch (error) {
        byId("login-hint").textContent = error.name === "AbortError"
          ? "The board did not respond within 10 seconds. Check your connection and try again."
          : (error instanceof TypeError ? "Cannot reach the board. Check your connection." : error.message);
        byId("login-hint").classList.add("field-error");
      } finally {
        clearTimeout(timer);
        button.disabled = false;
        button.textContent = "Sign in";
      }
    });
    return;
  }

  const form = byId("settings-form");
  if (!form) return;
  const state = {dirty: false, busy: false, statusBusy: false, failures: 0, timer: null, power: null};
  const ignored = new Set(["csrf_token", "revision", "admin_password"]);
  const controls = () => Array.from(form.elements).filter((el) => el.name && !ignored.has(el.name));
  const fingerprint = () => JSON.stringify(controls().map((el) => [el.name, el.type === "checkbox" ? el.checked : el.value]));
  let baseline = fingerprint();
  form.noValidate = true;

  function updateDirty() {
    state.dirty = fingerprint() !== baseline;
    byId("edit-state").textContent = state.busy ? "Working..." : (state.dirty ? "Unsaved changes" : "No unsaved changes");
    byId("save-button").disabled = state.busy || !state.dirty;
    byId("discard").disabled = state.busy || !state.dirty;
    byId("update-button").disabled = state.busy || state.dirty || state.updating;
  }

  function announce(message, kind, focus = false) {
    const box = byId("feedback");
    box.className = "notice " + kind;
    box.textContent = message;
    box.hidden = false;
    if (focus) box.focus();
  }

  function revealField(input) {
    let parent = input.parentElement;
    while (parent) {
      if (parent.tagName === "DETAILS") parent.open = true;
      parent = parent.parentElement;
    }
    input.focus();
  }

  function showErrors(error) {
    announce(error.message, "error", true);
    let first = null;
    Object.entries(error.fields || {}).forEach(([name, message]) => {
      const input = form.elements.namedItem(name);
      const hint = byId(name + "-error");
      if (!input || !hint) return;
      input.setAttribute("aria-invalid", "true");
      hint.textContent = message;
      if (!first) first = input;
    });
    if (first) revealField(first);
    if (error.status === 401) byId("session-actions").hidden = false;
  }

  function clearErrors() {
    form.querySelectorAll("[aria-invalid]").forEach((input) => input.removeAttribute("aria-invalid"));
    form.querySelectorAll(".field-error").forEach((hint) => { hint.textContent = ""; });
  }

  async function api(path, options = {}, timeout = 10000) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeout);
    try {
      const response = await fetch(path, {
        ...options, credentials: "same-origin", cache: "no-store", signal: controller.signal,
        headers: {Accept: "application/json", "X-CSRF-Token": csrf, ...(options.headers || {})}
      });
      if (!(response.headers.get("content-type") || "").includes("application/json")) {
        throw new Error("Unexpected response from the board. Reload the portal after updating its software.");
      }
      const data = await response.json();
      if (!response.ok || !data.success) {
        const error = new Error(data.message || "The request could not be completed.");
        error.status = response.status;
        error.fields = data.fields || {};
        throw error;
      }
      return data;
    } catch (error) {
      if (error.name === "AbortError" || error instanceof TypeError) {
        const changing = options.method && options.method !== "GET";
        throw new Error(changing
          ? "The board stopped responding. The change may have been saved. Your fields are kept here; check or reload the device before retrying."
          : "Cannot reach the board. Check your network; the status shown may be out of date.");
      }
      throw error;
    } finally {
      clearTimeout(timer);
    }
  }

  function rememberDefaults() {
    Array.from(form.elements).forEach((el) => {
      if (el.type === "checkbox") el.defaultChecked = el.checked;
      else if (el.tagName === "SELECT") Array.from(el.options).forEach((opt) => { opt.defaultSelected = opt.selected; });
      else if (el.tagName === "INPUT") el.defaultValue = el.value;
    });
    baseline = fingerprint();
  }

  form.addEventListener("input", (event) => {
    event.target.removeAttribute("aria-invalid");
    const hint = byId(event.target.name + "-error");
    if (hint) hint.textContent = "";
    updateDirty();
  });
  form.addEventListener("change", updateDirty);
  form.addEventListener("invalid", (event) => revealField(event.target), true);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (state.busy) return;
    clearErrors();
    if (!form.reportValidity()) {
      announce("Complete the required fields before saving.", "error");
      return;
    }
    const body = new URLSearchParams(new FormData(form));
    state.busy = true;
    byId("settings-fields").disabled = true;
    byId("admin_password").disabled = true;
    byId("save-button").textContent = "Saving...";
    form.setAttribute("aria-busy", "true");
    updateDirty();
    try {
      const result = await api(form.action, {method: "POST", body});
      form.elements.namedItem("revision").value = result.revision;
      ["pass1", "pass2", "poster_token", "admin_password"].forEach((name) => {
        const input = form.elements.namedItem(name);
        input.value = "";
        input.type = "password";
      });
      document.querySelectorAll("[data-reveal]").forEach((button) => {
        button.textContent = "Show";
        button.setAttribute("aria-pressed", "false");
      });
      ["pass1", "pass2", "poster_token"].forEach((name) => {
        form.elements.namedItem("clear_" + name).checked = false;
        document.querySelector('[data-secret-state="' + name + '"]').textContent = result.secret_saved[name]
          ? "A value is saved on the board." : "No value is currently saved.";
      });
      rememberDefaults();
      announce(result.message, "success", true);
      refreshStatus();
    } catch (error) {
      // Restore controls before focusing any field-level error.
      byId("settings-fields").disabled = false;
      byId("admin_password").disabled = false;
      showErrors(error);
    } finally {
      state.busy = false;
      byId("settings-fields").disabled = false;
      byId("admin_password").disabled = false;
      byId("save-button").textContent = "Save settings";
      form.removeAttribute("aria-busy");
      updatePowerButtons();
      updateDirty();
    }
  });

  byId("discard").addEventListener("click", () => {
    if (!state.dirty || !window.confirm("Discard your unsaved settings?")) return;
    form.reset();
    clearErrors();
    byId("feedback").hidden = true;
    updateDirty();
  });
  window.addEventListener("beforeunload", (event) => {
    if (!state.dirty && !state.busy) return;
    event.preventDefault();
    event.returnValue = "";
  });
  byId("logout-form").addEventListener("submit", (event) => {
    if (state.busy || (state.dirty && !window.confirm("Sign out and discard unsaved changes?"))) {
      event.preventDefault();
    } else {
      state.dirty = false;
    }
  });

  function formatUptime(seconds) {
    if (seconds == null) return "Uptime unavailable";
    const hours = Math.floor(seconds / 3600);
    return "Up " + Math.floor(hours / 24) + "d " + hours % 24 + "h " + Math.floor(seconds % 3600 / 60) + "m";
  }

  function scheduleStatus() {
    clearTimeout(state.timer);
    if (!document.hidden) {
      state.timer = setTimeout(refreshStatus, Math.min(120000, 30000 * Math.pow(2, state.failures)));
    }
  }

  async function refreshStatus() {
    if (document.hidden || state.statusBusy) return;
    clearTimeout(state.timer);
    state.statusBusy = true;
    const button = byId("refresh-status");
    button.disabled = true;
    button.textContent = "Checking...";
    try {
      const result = await api("/api/status");
      const data = result.device;
      state.failures = 0;
      byId("connection").textContent = "Portal connected";
      byId("connection").className = "pill success";
      byId("connection-notice").hidden = true;
      byId("service-state").textContent = data.display_service;
      byId("memory-state").textContent = data.memory_used_percent == null ? "Unknown" : data.memory_used_percent + "%";
      byId("uptime-state").textContent = formatUptime(data.uptime_seconds);
      byId("disk-state").textContent = data.disk_free_mb == null ? "Unknown" : (data.disk_free_mb / 1024).toFixed(1) + " GB";
      byId("cache-state").textContent = data.cache_files == null ? "Unknown" : String(data.cache_files) + (data.cache_capped ? "+" : "");
      byId("player-state").textContent = data.video_player ? "Video player: " + data.video_player : "No video player found";
      byId("device-ip").textContent = "Local address: " + data.ip;
      byId("device-identity").textContent = "Screen " + data.device_id + " / " + data.mode + " mode";
      byId("status-checked").textContent = "Board sampled: " + data.checked_at;
      byId("feed-updated").textContent = data.feed_updated_at || "No saved feed";
      const list = byId("device-notices");
      list.replaceChildren();
      const warnings = data.warnings || [];
      (warnings.length ? warnings : ["No issues found by these basic device checks."]).forEach((message) => {
        const item = document.createElement("li");
        item.textContent = message;
        list.append(item);
      });
      byId("notice-count").textContent = warnings.length;
    } catch (error) {
      state.failures = Math.min(2, state.failures + 1);
      byId("connection").textContent = error.status === 401 ? "Sign-in required" : "Status unavailable";
      byId("connection").className = "pill warning";
      byId("connection-notice").textContent = error.message;
      byId("connection-notice").hidden = false;
      if (error.status === 401) byId("session-actions").hidden = false;
    } finally {
      state.statusBusy = false;
      button.disabled = false;
      button.textContent = "Refresh status";
      scheduleStatus();
    }
  }

  function updatePowerButtons() {
    byId("check-power").disabled = state.busy;
    byId("power-off").disabled = state.busy || !state.power || state.power === "OFF";
    byId("power-on").disabled = state.busy || !state.power || state.power === "ON";
  }

  async function powerAction(enable) {
    if (state.busy) return;
    const checking = enable === undefined;
    const password = byId("admin_password");
    if (!checking && !password.value) {
      byId("power-feedback").textContent = "Enter your admin password in the save bar before changing this setting.";
      revealField(password);
      return;
    }
    state.busy = true;
    updatePowerButtons();
    updateDirty();
    byId("power-feedback").textContent = checking ? "Checking the active Wi-Fi profile..." : "Updating the Wi-Fi profile...";
    try {
      const result = checking ? await api("/powersave_status", {}, 12000)
        : await api("/toggle_powersave", {method: "POST", headers: {"Content-Type": "application/json"},
            body: JSON.stringify({enable, admin_password: password.value})}, 12000);
      state.power = ["ON", "OFF", "DEFAULT", "UNCHANGED"].includes(result.status) ? result.status : null;
      byId("power-state").textContent = result.status;
      byId("power-feedback").textContent = result.message || "Saved profile setting; effective after reconnection.";
      if (!checking) password.value = "";
    } catch (error) {
      state.power = null;
      byId("power-state").textContent = "Unavailable";
      byId("power-feedback").textContent = error.message;
      if (error.status === 401) byId("session-actions").hidden = false;
    } finally {
      state.busy = false;
      updatePowerButtons();
      updateDirty();
    }
  }

  function renderUpdate(data) {
    state.updating = ["queued", "running"].includes(data.state);
    byId("update-feedback").textContent = data.message;
    byId("update-button").textContent = state.updating ? "Updating…" : "Update software";
    updateDirty();
  }

  async function refreshUpdate() {
    if (document.hidden) return;
    try {
      const result = await api("/api/update");
      renderUpdate(result.update);
    } catch (error) {
      byId("update-feedback").textContent = state.updating
        ? "Waiting for the portal to reconnect. The update may still be running."
        : error.message;
    }
  }

  byId("update-button").addEventListener("click", async () => {
    if (state.busy || state.dirty || state.updating) return;
    const password = byId("admin_password");
    if (!password.value) {
      byId("update-feedback").textContent = "Enter your admin password in the save bar first.";
      revealField(password);
      return;
    }
    state.busy = true;
    updateDirty();
    try {
      const result = await api("/api/update", {method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({admin_password: password.value})});
      password.value = "";
      renderUpdate(result.update);
    } catch (error) {
      byId("update-feedback").textContent = error.message + " Checking whether the update started…";
      await refreshUpdate();
      if (!state.updating) byId("update-feedback").textContent = error.message;
    } finally {
      state.busy = false;
      updateDirty();
    }
  });
  refreshUpdate();
  setInterval(refreshUpdate, 10000);

  byId("check-power").addEventListener("click", () => powerAction());
  byId("power-off").addEventListener("click", () => powerAction(false));
  byId("power-on").addEventListener("click", () => powerAction(true));
  byId("refresh-status").addEventListener("click", refreshStatus);
  document.addEventListener("visibilitychange", () => {
    clearTimeout(state.timer);
    if (!document.hidden) refreshStatus();
  });
  window.addEventListener("online", refreshStatus);
  window.addEventListener("offline", () => {
    byId("connection").textContent = "Browser offline";
    byId("connection").className = "pill warning";
    byId("connection-notice").textContent = "Your browser is offline. Unsaved settings are kept on this page.";
    byId("connection-notice").hidden = false;
  });
  updateDirty();
  updatePowerButtons();
  refreshStatus();
})();
