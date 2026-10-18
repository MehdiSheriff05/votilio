/* Votilio front-end behaviour. No dependencies; progressive enhancement over server-rendered pages. */
(function () {
  "use strict";

  var $ = function (sel, root) { return (root || document).querySelector(sel); };
  var $$ = function (sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); };
  var csrf = function () { var m = $('meta[name="csrf-token"]'); return m ? m.content : ""; };
  function on(event, selector, handler) {
    document.addEventListener(event, function (e) {
      var t = e.target.closest ? e.target.closest(selector) : null;
      if (t && document.contains(t)) handler(e, t);
    });
  }
  function icon(name) {
    return '<svg class="ic" aria-hidden="true"><use href="#i-' + name + '"/></svg>';
  }
  function esc(s) { var d = document.createElement("div"); d.textContent = s == null ? "" : String(s); return d.innerHTML; }

  /* ---------- toasts ---------- */
  var ICONS = { success: "check", danger: "alert", error: "alert", warning: "alert", info: "info" };
  function toast(message, type) {
    type = type || "info";
    var host = $("#toasts");
    if (!host) return;
    var el = document.createElement("div");
    el.className = "toast " + type;
    el.innerHTML = icon(ICONS[type] || "info") + "<span>" + esc(message) + "</span>";
    host.appendChild(el);
    var ttl = type === "danger" || type === "error" ? 7000 : 3800;
    setTimeout(function () { el.classList.add("out"); setTimeout(function () { el.remove(); }, 220); }, ttl);
  }
  window.VotilioToast = toast;
  try {
    JSON.parse(($("#flash-data") || {}).textContent || "[]").forEach(function (m) { toast(m[1], m[0]); });
  } catch (e) { /* ignore */ }

  /* ---------- theme ---------- */
  function setTheme(t) {
    document.documentElement.dataset.theme = t;
    try { localStorage.setItem("votilio-theme", t); } catch (e) { /* ignore */ }
    $$("[data-theme-toggle] use").forEach(function (u) { u.setAttribute("href", t === "dark" ? "#i-sun" : "#i-moon"); });
  }
  on("click", "[data-theme-toggle]", function () {
    setTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark");
  });
  setTheme(document.documentElement.dataset.theme || "dark");

  /* ---------- dialogs ---------- */
  function openDialog(dlg) { if (dlg && !dlg.open) { dlg.showModal(); var f = $("[autofocus], input:not([type=hidden]):not([type=file]), textarea, select", dlg); if (f && matchMedia("(hover: hover)").matches) f.focus(); } }
  on("click", "[data-open]", function (e, btn) {
    var dlg = $(btn.dataset.open);
    if (!dlg) return;
    var form = $("form", dlg);
    if (form) {
      form.reset();
      if (btn.dataset.action) form.action = btn.dataset.action;
      if (btn.dataset.fill) {
        var data = JSON.parse(btn.dataset.fill);
        Object.keys(data).forEach(function (k) {
          var field = form.elements[k];
          if (!field) return;
          if (field.type === "checkbox") field.checked = !!data[k]; else field.value = data[k] == null ? "" : data[k];
        });
      }
      $$("[data-dlg-title]", dlg).forEach(function (n) { n.textContent = btn.dataset.title || n.dataset.dlgTitle; });
      $$("[data-edit-only]", dlg).forEach(function (n) { n.classList.toggle("hide", btn.dataset.mode !== "edit"); });
      $$("[data-create-only]", dlg).forEach(function (n) { n.classList.toggle("hide", btn.dataset.mode === "edit"); });
      var prev = $("[data-photo-preview]", dlg);
      if (prev) { prev.innerHTML = btn.dataset.photo ? '<img class="avatar" style="width:48px;height:48px" alt="" src="' + esc(btn.dataset.photo) + '">' : ""; }
    }
    openDialog(dlg);
  });
  on("click", "[data-close]", function (e, btn) { var d = btn.closest("dialog"); if (d) d.close(); });
  document.addEventListener("click", function (e) {
    if (e.target.tagName === "DIALOG" && e.target.open && !e.target.hasAttribute("data-modal-strict")) {
      var r = e.target.getBoundingClientRect();
      if (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom) e.target.close();
    }
  });

  /* ---------- confirm ---------- */
  var confirmDlg = $("#confirm-dialog");
  function askConfirm(opts) {
    return new Promise(function (resolve) {
      if (!confirmDlg) return resolve(window.confirm(opts.message));
      $("#confirm-title").textContent = opts.title || "Are you sure?";
      $("#confirm-body").textContent = opts.message || "";
      var ok = $("[data-confirm-ok]", confirmDlg);
      ok.textContent = opts.ok || "Confirm";
      ok.className = "btn " + (opts.danger === false ? "btn-primary" : "btn-danger");
      var done = function (v) { confirmDlg.close(); cleanup(); resolve(v); };
      var onOk = function () { done(true); }, onCancel = function () { done(false); };
      var onClose = function () { cleanup(); resolve(false); };
      function cleanup() {
        ok.removeEventListener("click", onOk);
        $("[data-confirm-cancel]", confirmDlg).removeEventListener("click", onCancel);
        confirmDlg.removeEventListener("close", onClose);
      }
      ok.addEventListener("click", onOk);
      $("[data-confirm-cancel]", confirmDlg).addEventListener("click", onCancel);
      confirmDlg.addEventListener("close", onClose);
      confirmDlg.showModal();
    });
  }
  window.VotilioConfirm = askConfirm;

  /* ---------- async forms ---------- */
  function setBusy(form, busy) {
    $$('button[type="submit"], button:not([type])', form).forEach(function (b) {
      if (b.closest("dialog") && b.hasAttribute("data-close")) return;
      b.classList.toggle("is-loading", busy);
    });
  }
  function swapRegions(url, names) {
    return fetch(url || location.href, { headers: { "X-Requested-With": "fetch-page" }, credentials: "same-origin" })
      .then(function (r) { return r.text(); })
      .then(function (html) {
        var doc = new DOMParser().parseFromString(html, "text/html");
        $$("[data-region]").forEach(function (cur) {
          if (names && names.indexOf(cur.dataset.region) === -1) return;
          var next = doc.querySelector('[data-region="' + cur.dataset.region + '"]');
          if (next) cur.replaceWith(next);
        });
        document.dispatchEvent(new CustomEvent("regions:updated"));
      });
  }
  window.VotilioSwap = swapRegions;

  function submitAsync(form, submitter) {
    var fd = new FormData(form);
    if (submitter && submitter.name) fd.append(submitter.name, submitter.value);
    if (form.dataset.collect) {
      $$("[data-row]:checked").forEach(function (c) { fd.append(form.dataset.collect, c.value); });
    }
    setBusy(form, true);
    return fetch(form.action, {
      method: (form.method || "post").toUpperCase(), body: fd, credentials: "same-origin",
      headers: { "X-Requested-With": "fetch", "Accept": "application/json" }
    }).then(function (r) {
      return r.json().catch(function () { return { ok: false, message: "Unexpected response from the server." }; })
        .then(function (data) { data._status = r.status; return data; });
    }).then(function (data) {
      setBusy(form, false);
      if (!data.ok) { toast(data.message || "That didn't work.", "danger"); return; }
      toast(data.message || "Saved.", "success");
      var dlg = form.closest("dialog"); if (dlg) dlg.close();
      if (form.dataset.nav) { location.href = data.redirect || form.dataset.nav; return; }
      if (form.dataset.reload) { location.reload(); return; }
      var regions = form.dataset.swap ? form.dataset.swap.split(",") : null;
      return swapRegions(data.redirect || location.href, regions).then(function () {
        form.dispatchEvent(new CustomEvent("async:saved", { bubbles: true, detail: data }));
      });
    }).catch(function () {
      setBusy(form, false);
      toast("Network problem. Check your connection and try again.", "danger");
    });
  }

  document.addEventListener("submit", function (e) {
    var form = e.target;
    if (!(form instanceof HTMLFormElement)) return;
    var submitter = e.submitter;
    var needsConfirm = (submitter && submitter.dataset.confirm) || form.dataset.confirm;
    if (needsConfirm && !form.dataset.confirmed) {
      e.preventDefault();
      var src = (submitter && submitter.dataset.confirm) ? submitter : form;
      askConfirm({ title: src.dataset.confirmTitle, message: src.dataset.confirm, ok: src.dataset.confirmOk, danger: src.dataset.confirmDanger !== "false" })
        .then(function (yes) {
          if (!yes) return;
          if (form.hasAttribute("data-async")) submitAsync(form, submitter);
          else { form.dataset.confirmed = "1"; form.requestSubmit ? form.requestSubmit(submitter) : form.submit(); }
        });
      return;
    }
    if (form.hasAttribute("data-async")) { e.preventDefault(); submitAsync(form, submitter); return; }
    var btn = submitter || $('button[type="submit"]', form);
    if (btn && !btn.hasAttribute("data-no-loading")) setTimeout(function () { btn.classList.add("is-loading"); }, 0);
  });
  window.addEventListener("pageshow", function () { $$(".is-loading").forEach(function (b) { b.classList.remove("is-loading"); }); });

  /* ---------- copy ---------- */
  on("click", "[data-copy]", function (e, btn) {
    var text = btn.dataset.copy;
    if (text.charAt(0) === "#") { var el = $(text); text = el ? (el.value || el.textContent) : ""; }
    (navigator.clipboard ? navigator.clipboard.writeText(text) : Promise.reject()).then(function () { toast("Copied to clipboard.", "success"); }, function () {
      var ta = document.createElement("textarea"); ta.value = text; document.body.appendChild(ta); ta.select();
      try { document.execCommand("copy"); toast("Copied to clipboard.", "success"); } catch (err) { toast("Couldn't copy. Select and copy manually.", "warning"); }
      ta.remove();
    });
  });

  /* ---------- live search ---------- */
  var searchTimer;
  on("input", "[data-live-search]", function (e, input) {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(function () {
      var url = new URL(location.href);
      if (input.value) url.searchParams.set("q", input.value); else url.searchParams.delete("q");
      url.searchParams.delete("page");
      history.replaceState(null, "", url);
      swapRegions(url.toString(), ["voters-list"]).then(function () { refreshBulk(); });
    }, 220);
  });

  /* ---------- bulk selection ---------- */
  function refreshBulk() {
    var rows = $$("[data-row]"), checked = rows.filter(function (c) { return c.checked; });
    var all = $("[data-all]");
    if (all) { all.checked = rows.length > 0 && checked.length === rows.length; all.indeterminate = checked.length > 0 && checked.length < rows.length; }
    rows.forEach(function (c) { var r = c.closest(".vrow"); if (r) r.classList.toggle("selected", c.checked); });
    var bar = $("#bulkbar");
    if (bar) {
      bar.classList.toggle("show", checked.length > 0);
      var n = $("[data-bulk-count]", bar); if (n) n.textContent = checked.length;
    }
  }
  on("change", "[data-row]", refreshBulk);
  on("change", "[data-all]", function (e, all) { $$("[data-row]").forEach(function (c) { c.checked = all.checked; }); refreshBulk(); });
  document.addEventListener("regions:updated", refreshBulk);
  on("click", "[data-bulk-clear]", function () { $$("[data-row]").forEach(function (c) { c.checked = false; }); refreshBulk(); });

  /* ---------- chunked sending ---------- */
  var sending = false;
  on("click", "[data-send]", function (e, btn) {
    if (sending) return;
    var dlg = $("#send-dialog"); if (!dlg) return;
    var kind = btn.dataset.kind, endpoint = btn.dataset.endpoint, ids = null, label = btn.dataset.label || "emails";
    if (btn.dataset.ids === "selected") {
      ids = $$("[data-row]:checked").map(function (c) { return Number(c.value); });
      if (!ids.length) { toast("Select at least one voter.", "warning"); return; }
    } else if (btn.dataset.ids) { ids = [Number(btn.dataset.ids)]; }
    var total = Number(btn.dataset.total || (ids ? ids.length : 0));
    $("[data-send-title]", dlg).textContent = kind === "reminder" ? "Sending reminders" : "Sending invitations";
    var bar = $("[data-send-bar]", dlg), big = $("[data-send-big]", dlg), sub = $("[data-send-sub]", dlg), fails = $("[data-send-fails]", dlg), close = $("[data-send-done]", dlg);
    bar.style.width = "0%"; big.textContent = "0"; sub.textContent = "Starting…"; fails.classList.add("hide"); fails.innerHTML = "";
    close.disabled = true; close.textContent = "Working…";
    dlg.setAttribute("data-modal-strict", ""); dlg.addEventListener("cancel", blockCancel);
    function blockCancel(ev) { if (sending) ev.preventDefault(); }
    dlg.showModal(); sending = true;
    var sent = 0, failed = [], cursor = 0, initial = total;
    function finish(msg) {
      sending = false; dlg.removeEventListener("cancel", blockCancel); dlg.removeAttribute("data-modal-strict");
      close.disabled = false; close.textContent = "Done";
      sub.textContent = msg;
      bar.style.width = "100%";
      swapRegions(location.href, ["voters-list", "voters-head", "ws-stats"]).then(refreshBulk);
    }
    function step() {
      fetch(endpoint, {
        method: "POST", credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-CSRFToken": csrf(), "X-Requested-With": "fetch", "Accept": "application/json" },
        body: JSON.stringify({ kind: kind, ids: ids, cursor: cursor })
      }).then(function (r) { return r.json().then(function (d) { d._ok = r.ok; return d; }); }).then(function (d) {
        if (!d._ok || d.ok === false) { finish(d.message || "Sending stopped because of an error."); toast(d.message || "Sending failed.", "danger"); return; }
        sent += d.sent; failed = failed.concat(d.failed || []); cursor = d.cursor;
        if (!initial) initial = sent + failed.length + d.remaining;
        var processed = sent + failed.length;
        big.textContent = sent;
        bar.style.width = Math.min(99, Math.round(100 * processed / Math.max(initial, processed + d.remaining, 1))) + "%";
        sub.textContent = processed + " of " + Math.max(initial, processed + d.remaining) + " processed" + (failed.length ? " · " + failed.length + " failed" : "");
        if (failed.length) {
          fails.classList.remove("hide");
          fails.innerHTML = failed.map(function (f) { return "<div><b>" + esc(f.email || "") + "</b> — " + esc(f.error) + "</div>"; }).join("");
        }
        if (d.done) {
          finish(sent === 0 && !failed.length ? "Nothing to send." : sent + " sent" + (failed.length ? ", " + failed.length + " failed. Fix the issue and send again; sent voters are skipped." : "."));
          if (sent && !failed.length) toast(sent + " " + label + " sent.", "success");
        } else step();
      }).catch(function () { finish("Lost connection. Sent so far: " + sent + ". Run it again to continue."); });
    }
    step();
  });
  on("click", "[data-send-done]", function (e, btn) { var d = btn.closest("dialog"); if (d && !sending) d.close(); });

  /* ---------- sortable lists (pointer based: works with mouse and touch) ---------- */
  var drag = null;
  on("pointerdown", ".grip", function (e, grip) {
    var item = grip.closest("[data-sort-item]"), list = item && item.parentElement.closest("[data-sortable]");
    if (!item || !list) return;
    e.preventDefault();
    drag = { item: item, list: list, moved: false };
    item.classList.add("dragging");
    try { grip.setPointerCapture(e.pointerId); } catch (err) { /* ignore */ }
  });
  document.addEventListener("pointermove", function (e) {
    if (!drag) return;
    drag.moved = true;
    var siblings = $$(":scope > [data-sort-item]", drag.list).filter(function (n) { return n !== drag.item; });
    for (var i = 0; i < siblings.length; i++) {
      var r = siblings[i].getBoundingClientRect();
      if (e.clientY < r.top + r.height / 2) { drag.list.insertBefore(drag.item, siblings[i]); return; }
    }
    var last = siblings[siblings.length - 1];
    if (last) last.after(drag.item);
  });
  function endDrag() {
    if (!drag) return;
    var d = drag; drag = null; d.item.classList.remove("dragging");
    if (!d.moved) return;
    var ids = $$(":scope > [data-sort-item]", d.list).map(function (n) { return Number(n.dataset.id); });
    fetch(d.list.dataset.reorderUrl, {
      method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrf(), "X-Requested-With": "fetch" },
      body: JSON.stringify({ ids: ids })
    }).then(function (r) { toast(r.ok ? "Order saved." : "Couldn't save the new order.", r.ok ? "success" : "danger"); })
      .catch(function () { toast("Couldn't save the new order.", "danger"); });
  }
  document.addEventListener("pointerup", endDrag);
  document.addEventListener("pointercancel", endDrag);
  on("click", "[data-move]", function (e, btn) {
    var item = btn.closest("[data-sort-item]"), list = item.parentElement;
    var dir = btn.dataset.move, sib = dir === "up" ? item.previousElementSibling : item.nextElementSibling;
    if (!sib) return;
    if (dir === "up") list.insertBefore(item, sib); else sib.after(item);
    drag = { item: item, list: list, moved: true }; endDrag();
  });

  /* ---------- dirty-bar for long forms ---------- */
  function initDirty() {
    var form = $("form[data-dirty]"), bar = $("#save-bar");
    if (!form || !bar || form.dataset.dirtyInit) return;
    form.dataset.dirtyInit = "1";
    var show = function () { bar.classList.add("show"); };
    form.addEventListener("input", show); form.addEventListener("change", show);
    $("[data-discard]", bar).addEventListener("click", function () { form.reset(); bar.classList.remove("show"); updatePreview(); });
    $("[data-save]", bar).addEventListener("click", function () { form.requestSubmit(); });
    form.addEventListener("async:saved", function () { bar.classList.remove("show"); });
    window.addEventListener("beforeunload", function (ev) { if (bar.classList.contains("show")) { ev.preventDefault(); ev.returnValue = ""; } });
  }
  function updatePreview() {
    var p = $("#brand-preview"); if (!p) return;
    var c = $('input[name="theme_primary"]'); if (c) p.style.setProperty("--brand", c.value);
  }
  on("input", 'input[name="theme_primary"]', updatePreview);
  on("click", "[data-clear-color]", function (e, b) {
    var i = $('input[name="' + b.dataset.clearColor + '"]'); if (i) { i.value = "#7b7bff"; i.dispatchEvent(new Event("input", { bubbles: true })); }
  });

  /* ---------- settings: provider switch, test email, placeholders ---------- */
  function syncProvider() {
    var sel = $('input[name="email_provider"]:checked'); if (!sel) return;
    $$(".provider-panel").forEach(function (p) { p.hidden = p.dataset.provider !== sel.value; });
  }
  on("change", 'input[name="email_provider"]', syncProvider);
  on("click", "[data-test-email]", function (e, btn) {
    var form = btn.closest("form"), to = $("#test-to").value.trim(), out = $("#test-result");
    var f = form.elements;
    var body = { to: to, provider: ($('input[name="email_provider"]:checked') || {}).value, mail_sender: f.mail_sender.value,
      smtp_host: f.smtp_host.value, smtp_port: f.smtp_port.value, smtp_security: f.smtp_security.value, smtp_user: f.smtp_user.value,
      smtp_password: f.smtp_password.value, resend_api_key: f.resend_api_key ? f.resend_api_key.value : "" };
    out.className = "test-result muted"; out.textContent = "Sending…"; btn.classList.add("is-loading");
    fetch(btn.dataset.endpoint, { method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrf(), "X-Requested-With": "fetch" }, body: JSON.stringify(body) })
      .then(function (r) { return r.json(); }).then(function (d) {
        btn.classList.remove("is-loading");
        if (d.ok) { out.className = "test-result ok"; out.textContent = "Sent via " + d.provider.toUpperCase() + ". Check the inbox for " + to + "."; }
        else { out.className = "test-result bad"; out.textContent = d.error || "Sending failed."; }
      }).catch(function () { btn.classList.remove("is-loading"); out.className = "test-result bad"; out.textContent = "Network error."; });
  });
  var lastField = null;
  document.addEventListener("focusin", function (e) { if (e.target.matches && e.target.matches("[data-ph-target]")) lastField = e.target; });
  on("click", "[data-ph]", function (e, chip) {
    if (!lastField) lastField = $("[data-ph-target]");
    var t = lastField, v = "{{ " + chip.dataset.ph + " }}";
    var s = t.selectionStart == null ? t.value.length : t.selectionStart, en = t.selectionEnd == null ? s : t.selectionEnd;
    t.value = t.value.slice(0, s) + v + t.value.slice(en); t.focus(); t.setSelectionRange(s + v.length, s + v.length);
    t.dispatchEvent(new Event("input", { bubbles: true }));
  });

  /* ---------- misc controls ---------- */
  on("click", "[data-reveal]", function (e, b) {
    var i = $(b.dataset.reveal); if (!i) return;
    var show = i.type === "password"; i.type = show ? "text" : "password";
    $("use", b).setAttribute("href", show ? "#i-eye-off" : "#i-eye");
  });
  on("input", ".keyinput", function (e, i) { i.value = i.value.replace(/\D/g, "").slice(0, 6); });
  on("click", "[data-reveal-key]", function (e, b) {
    fetch(b.dataset.revealKey, { credentials: "same-origin", headers: { "X-Requested-With": "fetch" } })
      .then(function (r) { return r.json(); }).then(function (d) {
        var key = d.key || "no key";
        navigator.clipboard && d.key && navigator.clipboard.writeText(d.key).catch(function () {});
        toast("Voting key: " + key + (d.key ? " (copied)" : ""), "info");
      });
  });
  on("change", 'input[type="file"][data-preview]', function (e, input) {
    var target = $(input.dataset.preview), f = input.files && input.files[0];
    if (target && f) target.innerHTML = '<img class="avatar" style="width:48px;height:48px" alt="" src="' + URL.createObjectURL(f) + '">';
  });

  /* ---------- ballot progress ---------- */
  function updateBallot() {
    var groups = $$("fieldset.v-pos"); if (!groups.length) return;
    var chosen = groups.filter(function (g) { return $("input:checked", g); }).length;
    var t = $("[data-progress-text]"), bar = $("[data-progress-bar]");
    if (t) t.textContent = chosen + " of " + groups.length;
    if (bar) bar.style.width = (100 * chosen / groups.length) + "%";
  }
  on("change", "fieldset.v-pos input", updateBallot);
  on("click", "[data-clear-choice]", function (e, b) {
    $$("input", b.closest("fieldset")).forEach(function (i) { i.checked = false; }); updateBallot();
  });

  /* ---------- command palette ---------- */
  var pal = $("#palette");
  var palItems = [], palIdx = 0;
  function buildPalette() {
    var data = {}; try { data = JSON.parse(($("#palette-data") || {}).textContent || "{}"); } catch (e) { /* ignore */ }
    var items = [{ t: "Elections", h: "/admin/", i: "vote", s: "Go to" }];
    (data.elections || []).forEach(function (el) {
      items.push({ t: el.name, h: "/admin/elections/" + el.id + "/setup", i: "vote", s: "Setup" });
      items.push({ t: el.name + " — Voters", h: "/admin/elections/" + el.id + "/voters", i: "users", s: "Voters" });
      items.push({ t: el.name + " — Results", h: "/admin/elections/" + el.id + "/results", i: "chart", s: "Results" });
    });
    items.push({ t: "New election", h: "/admin/elections/create", i: "plus", s: "Create" });
    if (data.super) { items.push({ t: "Email settings", h: "/admin/settings/email", i: "mail", s: "Settings" }, { t: "Admins", h: "/admin/settings/admins", i: "shield", s: "Settings" }); }
    items.push({ t: "Audit log", h: "/admin/settings/logs", i: "list", s: "Settings" }, { t: "Toggle theme", a: "theme", i: "sun", s: "Action" }, { t: "Sign out", a: "logout", i: "logout", s: "Action" });
    return items;
  }
  function renderPalette(q) {
    var list = $(".pal-list", pal); q = (q || "").toLowerCase();
    palItems = buildPalette().filter(function (i) { return !q || i.t.toLowerCase().indexOf(q) !== -1; }).slice(0, 30);
    palIdx = 0;
    list.innerHTML = palItems.length ? palItems.map(function (i, n) {
      return '<div class="pal-item" role="option" data-n="' + n + '" aria-selected="' + (n === 0) + '">' + icon(i.i) + "<span>" + esc(i.t) + "</span><small>" + esc(i.s) + "</small></div>";
    }).join("") : '<div class="pal-empty">No matches</div>';
  }
  function runPalette(item) {
    if (!item) return;
    pal.close();
    if (item.a === "theme") $("[data-theme-toggle]") ? $("[data-theme-toggle]").click() : setTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark");
    else if (item.a === "logout") { var f = $("#logout-form"); if (f) f.submit(); }
    else location.href = item.h;
  }
  function openPalette() { if (!pal) return; renderPalette(""); $("input", pal).value = ""; pal.showModal(); $("input", pal).focus(); }
  document.addEventListener("keydown", function (e) {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k" && pal) { e.preventDefault(); pal.open ? pal.close() : openPalette(); }
  });
  on("click", "[data-palette]", openPalette);
  if (pal) {
    $("input", pal).addEventListener("input", function (e) { renderPalette(e.target.value); });
    pal.addEventListener("keydown", function (e) {
      var rows = $$(".pal-item", pal);
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault(); palIdx = (palIdx + (e.key === "ArrowDown" ? 1 : -1) + rows.length) % Math.max(rows.length, 1);
        rows.forEach(function (r, n) { r.setAttribute("aria-selected", n === palIdx); }); if (rows[palIdx]) rows[palIdx].scrollIntoView({ block: "nearest" });
      } else if (e.key === "Enter") { e.preventDefault(); runPalette(palItems[palIdx]); }
    });
    pal.addEventListener("click", function (e) { var r = e.target.closest(".pal-item"); if (r) runPalette(palItems[Number(r.dataset.n)]); });
  }

  /* ---------- csv editor bridge (bundle is loaded on pages that need it) ---------- */
  on("click", "[data-csv-open]", function (e, btn) {
    var dlg = $("#import-dialog"); if (!dlg) return;
    var opts = { kind: btn.dataset.csvOpen, endpoint: btn.dataset.endpoint, template: btn.dataset.template, csrf: csrf(),
      positions: btn.dataset.positions ? JSON.parse(btn.dataset.positions) : [] };
    $("[data-import-title]", dlg).textContent = opts.kind === "voters" ? "Import voters" : "Import candidates";
    openDialog(dlg);
    if (window.VotilioCsv) window.VotilioCsv.open($("#csv-mount"), opts, function () {
      dlg.close(); swapRegions(location.href, ["voters-list", "voters-head", "ws-stats", "positions-list"]).then(refreshBulk);
    });
    else $("#csv-mount").innerHTML = '<div class="empty"><h3>Editor not loaded</h3><p>Reload the page and try again.</p></div>';
  });

  document.addEventListener("regions:updated", initDirty);
  syncProvider(); initDirty(); updatePreview(); updateBallot(); refreshBulk();
})();
