<script>
  import { SCHEMAS, validateRows } from "./lib/validate.js";
  import {
    buildSheet, parseFile, parseText, emptyRow, defaultColumns, toRecords, toCsv, download, nextId, MAX_ROWS,
  } from "./lib/csv.js";

  let { opts, onDone } = $props();

  const kind = opts.kind;
  const schema = SCHEMAS[kind];
  const ROW_H = 38;
  const GUTTER = 84;
  const noun = kind === "voters" ? "voter" : "candidate";

  let stage = $state("start"); // start | edit | done
  let columns = $state.raw([]);
  let rows = $state.raw([]);
  let past = $state.raw([]);
  let future = $state.raw([]);

  let search = $state("");
  let errorsOnly = $state(false);
  let sortBy = $state.raw(null); // {colId, dir}
  let createMissing = $state(false);
  let skipInvalid = $state(false);

  let sel = $state.raw(null); // {rowId, colId}
  let editing = $state.raw(null); // {rowId, colId, value}
  let checked = $state.raw(new Set());
  let serverErrors = $state.raw(new Map());
  let colMenu = $state.raw(null);
  let renaming = $state.raw(null);

  let scrollTop = $state(0);
  let vpHeight = $state(500);
  let vpEl = $state();
  let dragging = $state(false);
  let pasteText = $state("");
  let notice = $state("");
  let busy = $state(false);
  let result = $state.raw(null);
  let validating = $state(false);
  let fileInput = $state();

  // ---------- derived ----------
  const records = $derived.by(() => toRecords(kind, columns, rows));
  const localErrors = $derived.by(() => {
    const errs = validateRows(kind, records.map((r) => r.data), { positions: opts.positions, createMissing });
    const map = new Map();
    records.forEach((r, i) => map.set(r.id, errs[i]));
    return map;
  });
  function errorsFor(rowId) {
    const local = localErrors.get(rowId);
    const server = serverErrors.get(rowId);
    if (!local && !server) return null;
    const merged = { ...(server || {}), ...(local || {}) };
    return Object.keys(merged).length ? merged : null;
  }
  const errorMap = $derived.by(() => {
    const m = new Map();
    for (const r of records) {
      const e = errorsFor(r.id);
      if (e) m.set(r.id, e);
    }
    return m;
  });
  const errorCount = $derived(errorMap.size);
  const readyCount = $derived(records.length - errorCount);
  const fieldColumn = $derived.by(() => {
    const m = {};
    for (const c of columns) if (c.field && !(c.field in m)) m[c.field] = c.id;
    return m;
  });
  const missingRequired = $derived(schema.fields.filter((f) => f.required && !fieldColumn[f.key]));
  const view = $derived.by(() => {
    let list = rows;
    const q = search.trim().toLowerCase();
    if (q) list = list.filter((r) => columns.some((c) => (r.c[c.id] ?? "").toLowerCase().includes(q)));
    if (errorsOnly) list = list.filter((r) => errorMap.has(r.id));
    if (sortBy) {
      const { colId, dir } = sortBy;
      list = [...list].sort((a, b) => (a.c[colId] ?? "").localeCompare(b.c[colId] ?? "", undefined, { numeric: true, sensitivity: "base" }) * dir);
    }
    return list;
  });
  const rowNumber = $derived.by(() => {
    const m = new Map();
    rows.forEach((r, i) => m.set(r.id, i + 1));
    return m;
  });
  const totalWidth = $derived(GUTTER + columns.reduce((s, c) => s + c.width, 0) + 56);
  const startIdx = $derived(Math.max(0, Math.floor(scrollTop / ROW_H) - 8));
  const endIdx = $derived(Math.min(view.length, startIdx + Math.ceil(vpHeight / ROW_H) + 18));
  const windowRows = $derived(view.slice(startIdx, endIdx));
  const allChecked = $derived(view.length > 0 && view.every((r) => checked.has(r.id)));
  const importCount = $derived(skipInvalid ? readyCount : records.length);
  const canImport = $derived(records.length > 0 && !busy && missingRequired.length === 0 && (errorCount === 0 || (skipInvalid && readyCount > 0)));

  // ---------- history ----------
  function commit(nextColumns, nextRows) {
    past = [...past.slice(-99), { columns, rows }];
    future = [];
    columns = nextColumns;
    rows = nextRows;
    queueValidate();
  }
  function undo() {
    if (!past.length) return;
    future = [{ columns, rows }, ...future];
    const prev = past[past.length - 1];
    past = past.slice(0, -1);
    columns = prev.columns;
    rows = prev.rows;
    editing = null;
    queueValidate();
  }
  function redo() {
    if (!future.length) return;
    past = [...past, { columns, rows }];
    const next = future[0];
    future = future.slice(1);
    columns = next.columns;
    rows = next.rows;
    editing = null;
    queueValidate();
  }

  // ---------- loading data ----------
  function load(matrix, { append = false } = {}) {
    const sheet = buildSheet(kind, matrix);
    if (sheet.rows.length > MAX_ROWS) { notice = `That's ${sheet.rows.length.toLocaleString()} rows. The limit is ${MAX_ROWS.toLocaleString()} per import.`; return; }
    notice = "";
    past = []; future = []; checked = new Set(); serverErrors = new Map(); sortBy = null; search = ""; errorsOnly = false;
    columns = sheet.columns.length ? sheet.columns : defaultColumns(kind);
    rows = sheet.rows.length ? sheet.rows : [emptyRow(columns)];
    stage = "edit";
    result = null;
    sel = { rowId: rows[0].id, colId: columns[0].id };
    queueValidate(0);
  }
  async function loadFile(file) {
    if (!file) return;
    try { load(await parseFile(file)); } catch (e) { notice = e.message; }
  }
  function startBlank() { columns = defaultColumns(kind); rows = [emptyRow(columns)]; past = []; future = []; stage = "edit"; sel = { rowId: rows[0].id, colId: columns[0].id }; }
  function usePasted() {
    if (!pasteText.trim()) { notice = "Paste some rows first."; return; }
    load(parseText(pasteText));
  }
  async function replaceWithFile(file) {
    if (rows.length && records.length) {
      const ok = window.VotilioConfirm ? await window.VotilioConfirm({ title: "Replace current data?", message: "Loading a new file replaces everything in the editor.", ok: "Replace", danger: false }) : true;
      if (!ok) return;
    }
    await loadFile(file);
  }
  function onDrop(e) {
    e.preventDefault();
    dragging = false;
    const file = e.dataTransfer?.files?.[0];
    if (file) (stage === "edit" ? replaceWithFile(file) : loadFile(file));
  }

  // ---------- server validation ----------
  let vTimer;
  let vSeq = 0;
  function queueValidate(delay = 600) {
    clearTimeout(vTimer);
    vTimer = setTimeout(runValidate, delay);
  }
  function api(path, body) {
    return fetch(opts.endpoint + path, {
      method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRFToken": opts.csrf, "X-Requested-With": "fetch", Accept: "application/json" },
      body: JSON.stringify(body),
    });
  }
  async function runValidate() {
    if (stage !== "edit" || !records.length) { serverErrors = new Map(); return; }
    const seq = ++vSeq;
    validating = true;
    try {
      const res = await api("/validate", { rows: records.map((r) => r.data), create_missing: createMissing });
      const data = await res.json();
      if (seq !== vSeq || !data.rows) return;
      const m = new Map();
      data.rows.forEach((r) => { if (Object.keys(r.errors).length && records[r.index]) m.set(records[r.index].id, r.errors); });
      serverErrors = m;
    } catch (e) { /* offline: local validation still applies */ } finally { if (seq === vSeq) validating = false; }
  }
  $effect(() => { createMissing; if (stage === "edit") queueValidate(150); });

  // ---------- editing ----------
  const colIndex = (id) => columns.findIndex((c) => c.id === id);
  function setCell(rowId, colId, value) {
    const idx = rows.findIndex((r) => r.id === rowId);
    if (idx < 0 || (rows[idx].c[colId] ?? "") === value) return;
    const next = rows.slice();
    next[idx] = { ...rows[idx], c: { ...rows[idx].c, [colId]: value } };
    if (serverErrors.has(rowId)) { const m = new Map(serverErrors); m.delete(rowId); serverErrors = m; }
    commit(columns, next);
  }
  function beginEdit(rowId, colId, seed) {
    const row = rows.find((r) => r.id === rowId);
    if (!row) return;
    sel = { rowId, colId };
    editing = { rowId, colId, value: seed ?? row.c[colId] ?? "" };
  }
  function finishEdit(save = true, move = null) {
    if (!editing) return;
    const e = editing;
    editing = null;
    if (save) setCell(e.rowId, e.colId, e.value);
    if (move) moveSel(move.dr, move.dc);
    vpEl?.focus({ preventScroll: true });
  }
  function moveSel(dr, dc) {
    if (!sel || !view.length) return;
    let r = view.findIndex((x) => x.id === sel.rowId);
    let c = colIndex(sel.colId);
    if (r < 0) r = 0;
    c += dc;
    if (c >= columns.length) { c = 0; r += 1; }
    if (c < 0) { c = columns.length - 1; r -= 1; }
    r = Math.min(view.length - 1, Math.max(0, r + dr));
    c = Math.min(columns.length - 1, Math.max(0, c));
    sel = { rowId: view[r].id, colId: columns[c].id };
    ensureVisible(r);
  }
  function ensureVisible(r) {
    if (!vpEl) return;
    const top = r * ROW_H, bottom = top + ROW_H, head = ROW_H + 4;
    if (top < vpEl.scrollTop) vpEl.scrollTop = top;
    else if (bottom + head > vpEl.scrollTop + vpEl.clientHeight) vpEl.scrollTop = bottom + head - vpEl.clientHeight;
  }
  function onKey(e) {
    if (editing || stage !== "edit") return;
    const mod = e.metaKey || e.ctrlKey;
    if (mod && e.key.toLowerCase() === "z") { e.preventDefault(); e.shiftKey ? redo() : undo(); return; }
    if (mod && e.key.toLowerCase() === "y") { e.preventDefault(); redo(); return; }
    if (mod && e.key.toLowerCase() === "c" && sel) {
      const row = rows.find((r) => r.id === sel.rowId);
      if (row) navigator.clipboard?.writeText(row.c[sel.colId] ?? "");
      return;
    }
    if (!sel) return;
    const k = e.key;
    if (k === "ArrowDown") { e.preventDefault(); moveSel(1, 0); }
    else if (k === "ArrowUp") { e.preventDefault(); moveSel(-1, 0); }
    else if (k === "ArrowRight") { e.preventDefault(); moveSel(0, 1); }
    else if (k === "ArrowLeft") { e.preventDefault(); moveSel(0, -1); }
    else if (k === "Tab") { e.preventDefault(); moveSel(0, e.shiftKey ? -1 : 1); }
    else if (k === "Enter" || k === "F2") { e.preventDefault(); beginEdit(sel.rowId, sel.colId); }
    else if (k === "Delete" || k === "Backspace") { e.preventDefault(); setCell(sel.rowId, sel.colId, ""); }
    else if (k.length === 1 && !mod && !e.altKey) { e.preventDefault(); beginEdit(sel.rowId, sel.colId, k); }
  }
  function onEditKey(e) {
    if (e.key === "Enter") { e.preventDefault(); finishEdit(true, { dr: e.shiftKey ? -1 : 1, dc: 0 }); }
    else if (e.key === "Tab") { e.preventDefault(); finishEdit(true, { dr: 0, dc: e.shiftKey ? -1 : 1 }); }
    else if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); finishEdit(false); }
  }
  function onPaste(e) {
    if (editing || stage !== "edit" || !sel) return;
    const text = e.clipboardData?.getData("text/plain");
    if (!text) return;
    e.preventDefault();
    const grid = parseText(text.includes("\t") || text.includes("\n") ? text : text + "\n").map((r) => r.map(String));
    let r0 = rows.findIndex((r) => r.id === sel.rowId);
    const c0 = colIndex(sel.colId);
    if (r0 < 0 || c0 < 0) return;
    const next = rows.slice();
    while (next.length < r0 + grid.length) next.push(emptyRow(columns));
    grid.forEach((line, i) => {
      const row = next[r0 + i];
      const cells = { ...row.c };
      line.forEach((val, j) => { const col = columns[c0 + j]; if (col) cells[col.id] = val; });
      next[r0 + i] = { ...row, c: cells };
    });
    if (next.length > MAX_ROWS) { notice = `The limit is ${MAX_ROWS.toLocaleString()} rows.`; return; }
    serverErrors = new Map();
    commit(columns, next);
  }

  // ---------- rows & columns ----------
  function addRow() {
    const row = emptyRow(columns);
    const at = sel ? rows.findIndex((r) => r.id === sel.rowId) : -1;
    const next = rows.slice();
    next.splice(at >= 0 ? at + 1 : next.length, 0, row);
    errorsOnly = false; search = ""; sortBy = null;
    commit(columns, next);
    sel = { rowId: row.id, colId: sel?.colId ?? columns[0].id };
    queueMicrotask(() => { const i = view.findIndex((r) => r.id === row.id); if (i >= 0) ensureVisible(i); });
  }
  function deleteRows(ids) {
    if (!ids.size) return;
    const next = rows.filter((r) => !ids.has(r.id));
    checked = new Set();
    commit(columns, next.length ? next : [emptyRow(columns)]);
  }
  function moveRow(id, dir) {
    const i = rows.findIndex((r) => r.id === id), j = i + dir;
    if (i < 0 || j < 0 || j >= rows.length) return;
    const next = rows.slice();
    [next[i], next[j]] = [next[j], next[i]];
    commit(columns, next);
  }
  function toggleRow(id) { const s = new Set(checked); s.has(id) ? s.delete(id) : s.add(id); checked = s; }
  function toggleAll() { checked = allChecked ? new Set() : new Set(view.map((r) => r.id)); }

  function addColumn() {
    const col = { id: nextId(), header: `Column ${columns.length + 1}`, field: null, width: 200 };
    const next = rows.map((r) => ({ ...r, c: { ...r.c, [col.id]: "" } }));
    commit([...columns, col], next);
    queueMicrotask(() => vpEl?.scrollTo({ left: vpEl.scrollWidth }));
  }
  function deleteColumn(id) {
    if (columns.length <= 1) return;
    commit(columns.filter((c) => c.id !== id), rows);
    if (sel?.colId === id) sel = { rowId: sel.rowId, colId: columns.find((c) => c.id !== id).id };
    colMenu = null;
  }
  function moveColumn(id, dir) {
    const i = colIndex(id), j = i + dir;
    if (j < 0 || j >= columns.length) return;
    const next = columns.slice();
    [next[i], next[j]] = [next[j], next[i]];
    commit(next, rows);
    colMenu = null;
  }
  function mapColumn(id, field) {
    const next = columns.map((c) => (c.id === id ? { ...c, field: field || null, width: field ? Math.max(c.width, schema.fields.find((f) => f.key === field).width) : c.width }
      : (field && c.field === field ? { ...c, field: null } : c)));
    commit(next, rows);
  }
  function renameColumn(id, header) {
    renaming = null;
    const h = header.trim();
    if (!h) return;
    commit(columns.map((c) => (c.id === id ? { ...c, header: h } : c)), rows);
  }
  function sortColumn(id, dir) {
    sortBy = sortBy && sortBy.colId === id && sortBy.dir === dir ? null : { colId: id, dir };
    colMenu = null;
  }
  function headerClick(c) {
    sortBy = !sortBy || sortBy.colId !== c.id ? { colId: c.id, dir: 1 } : sortBy.dir === 1 ? { colId: c.id, dir: -1 } : null;
  }
  function openColMenu(e, c) {
    e.stopPropagation();
    const r = e.currentTarget.getBoundingClientRect();
    colMenu = { colId: c.id, x: Math.min(r.left, window.innerWidth - 240), y: r.bottom + 6 };
  }

  // ---------- output ----------
  function csvName() { return `${kind}-${new Date().toISOString().slice(0, 10)}.csv`; }
  function exportCsv() { download(csvName(), toCsv(columns, rows)); }
  async function doImport() {
    if (!canImport) return;
    busy = true; notice = "";
    try {
      const res = await api("", { rows: records.map((r) => r.data), skip_invalid: skipInvalid, create_missing: createMissing });
      const data = await res.json().catch(() => ({}));
      if (res.ok && data.ok) {
        result = { ...data, ids: records.map((r) => r.id) };
        stage = "done";
      } else if (res.status === 422 && data.rows) {
        const m = new Map();
        data.rows.forEach((r) => { if (Object.keys(r.errors).length && records[r.index]) m.set(records[r.index].id, r.errors); });
        serverErrors = m;
        notice = data.message || "Some rows need fixing.";
        errorsOnly = true;
      } else {
        notice = data.message || `The import failed (${res.status}).`;
      }
    } catch (e) {
      notice = "Network problem. Your data is still here; try again.";
    } finally { busy = false; }
  }
  function rejectedCsv() {
    const rej = result?.rejected || [];
    const cols = schema.fields.map((f) => f.label).concat("Problem");
    const body = rej.map((r) => schema.fields.map((f) => r.row[f.key] ?? "").concat(Object.values(r.errors).join("; ")));
    return toCsv(cols.map((h, i) => ({ id: i, header: h })), body.map((cells) => ({ c: Object.fromEntries(cells.map((v, i) => [i, v])) })));
  }
  function fixRejected() {
    const rej = result?.rejected || [];
    const matrix = [schema.fields.map((f) => f.label), ...rej.map((r) => schema.fields.map((f) => r.row[f.key] ?? ""))];
    load(matrix);
    skipInvalid = false;
  }
  function finish() { onDone?.(); }

  // ---------- actions ----------
  function focusOnMount(node) { node.focus(); node.select?.(); }
  function onWindowClick() { colMenu = null; }
  function cellTitle(rowId, c) {
    const e = errorMap.get(rowId);
    return c.field && e && e[c.field] ? e[c.field] : undefined;
  }
</script>

<svelte:window onclick={onWindowClick} onkeydown={(e) => { if (e.key === "Escape") colMenu = null; }} />

<div class="ce" class:drag={dragging} role="presentation"
  ondragover={(e) => { e.preventDefault(); dragging = true; }} ondragleave={(e) => { if (!e.relatedTarget || !e.currentTarget.contains(e.relatedTarget)) dragging = false; }} ondrop={onDrop}>

  {#if stage === "start"}
    <div class="start">
      <div class="drop" role="button" tabindex="0" onclick={() => fileInput.click()} onkeydown={(e) => (e.key === "Enter" || e.key === " ") && fileInput.click()}>
        <svg class="ic ic-lg" aria-hidden="true"><use href="#i-upload" /></svg>
        <b>Drop a CSV file here</b>
        <span>or click to choose one. Works with exports from Excel, Google Sheets and Numbers.</span>
        <input bind:this={fileInput} type="file" accept=".csv,.tsv,.txt,text/csv" hidden onchange={(e) => loadFile(e.currentTarget.files[0])} />
      </div>
      <div class="or">or</div>
      <div class="paste">
        <label class="label" for="ce-paste">Paste rows from a spreadsheet</label>
        <textarea id="ce-paste" class="textarea" rows="5" bind:value={pasteText} placeholder={kind === "voters" ? "Name\tEmail\nAmina Yusuf\tamina@example.com" : "Position\tName\tBio\nPresident\tAmina Yusuf\tThird-year engineering student"}></textarea>
        <div class="row">
          <button class="btn btn-primary btn-sm" onclick={usePasted}>Use pasted rows</button>
          <button class="btn btn-sm" onclick={startBlank}>Start from a blank sheet</button>
          <a class="btn btn-ghost btn-sm" href={opts.template}><svg class="ic" aria-hidden="true"><use href="#i-download" /></svg>Download template</a>
        </div>
      </div>
      {#if notice}<div class="notice notice-danger"><svg class="ic" aria-hidden="true"><use href="#i-alert" /></svg><div>{notice}</div></div>{/if}
      <p class="hint">Needed columns: {schema.fields.filter((f) => f.required).map((f) => f.label).join(", ")}{schema.fields.some((f) => !f.required) ? ". Optional: " + schema.fields.filter((f) => !f.required).map((f) => f.label).join(", ") : ""}. Column names are matched automatically.</p>
    </div>

  {:else if stage === "edit"}
    <div class="bar">
      <div class="input-icon grow-s"><svg class="ic" aria-hidden="true"><use href="#i-search" /></svg>
        <input class="input" type="search" placeholder="Search rows" bind:value={search} aria-label="Search rows" /></div>
      <button class="chip" class:active={errorsOnly} onclick={() => (errorsOnly = !errorsOnly)} aria-pressed={errorsOnly}>
        {#if errorCount}<span class="dot"></span>{/if}Errors only <span class="n">{errorCount}</span></button>
      <span class="sp"></span>
      <button class="btn btn-ghost btn-icon btn-sm" onclick={undo} disabled={!past.length} aria-label="Undo" title="Undo (Ctrl/⌘ Z)"><svg class="ic" aria-hidden="true"><use href="#i-undo" /></svg></button>
      <button class="btn btn-ghost btn-icon btn-sm" onclick={redo} disabled={!future.length} aria-label="Redo" title="Redo"><svg class="ic" aria-hidden="true"><use href="#i-redo" /></svg></button>
      <button class="btn btn-sm" onclick={addRow}><svg class="ic" aria-hidden="true"><use href="#i-plus" /></svg>Row</button>
      <button class="btn btn-sm" onclick={addColumn}><svg class="ic" aria-hidden="true"><use href="#i-plus" /></svg>Column</button>
      {#if checked.size}<button class="btn btn-sm btn-danger" onclick={() => deleteRows(checked)}><svg class="ic" aria-hidden="true"><use href="#i-trash" /></svg>Delete {checked.size}</button>{/if}
      <button class="btn btn-sm" onclick={() => fileInput.click()}><svg class="ic" aria-hidden="true"><use href="#i-upload" /></svg>Replace</button>
      <input bind:this={fileInput} type="file" accept=".csv,.tsv,.txt,text/csv" hidden onchange={(e) => { replaceWithFile(e.currentTarget.files[0]); e.currentTarget.value = ""; }} />
      <button class="btn btn-sm" onclick={exportCsv}><svg class="ic" aria-hidden="true"><use href="#i-download" /></svg>Download</button>
    </div>

    {#if missingRequired.length}
      <div class="notice notice-warn mapnote"><svg class="ic" aria-hidden="true"><use href="#i-alert" /></svg>
        <div>
          {#each missingRequired as f (f.key)}
            <span class="maprow">Which column is <b>{f.label}</b>?
              <select class="select sel-sm" onchange={(e) => e.currentTarget.value && mapColumn(Number(e.currentTarget.value), f.key)}>
                <option value="">Choose a column…</option>
                {#each columns as c (c.id)}<option value={c.id}>{c.header}</option>{/each}
              </select></span>
          {/each}
        </div></div>
    {/if}
    {#if notice}<div class="notice notice-danger mapnote"><svg class="ic" aria-hidden="true"><use href="#i-alert" /></svg><div>{notice}</div></div>{/if}

    <div class="vp" bind:this={vpEl} bind:clientHeight={vpHeight} onscroll={(e) => (scrollTop = e.currentTarget.scrollTop)}
      role="grid" aria-rowcount={view.length + 1} aria-colcount={columns.length} tabindex="0" onkeydown={onKey} onpaste={onPaste} aria-label="{noun} data">
      <div class="head" style="width:{totalWidth}px" role="row">
        <div class="gutter hcell" style="width:{GUTTER}px"><input class="cb" type="checkbox" checked={allChecked} onchange={toggleAll} aria-label="Select all rows" /></div>
        {#each columns as c (c.id)}
          {@const required = c.field && schema.fields.find((f) => f.key === c.field)?.required}
          <div class="hcell" class:unmapped={!c.field} style="width:{c.width}px" role="columnheader" aria-sort={sortBy?.colId === c.id ? (sortBy.dir === 1 ? "ascending" : "descending") : "none"}>
            {#if renaming === c.id}
              <input class="hedit" value={c.header} use:focusOnMount onblur={(e) => renameColumn(c.id, e.currentTarget.value)} onkeydown={(e) => { if (e.key === "Enter") e.currentTarget.blur(); if (e.key === "Escape") renaming = null; }} />
            {:else}
              <button class="hname" onclick={() => headerClick(c)} ondblclick={() => (renaming = c.id)} title="Click to sort, double-click to rename">
                <span class="t">{c.header}</span>
                {#if c.field}<span class="tag">{required ? "required" : "optional"}</span>{:else}<span class="tag skip">not imported</span>{/if}
                {#if sortBy?.colId === c.id}<svg class="ic" aria-hidden="true"><use href={sortBy.dir === 1 ? "#i-arrow-up" : "#i-arrow-down"} /></svg>{/if}
              </button>
            {/if}
            <button class="hmenu" onclick={(e) => openColMenu(e, c)} aria-label="Column options for {c.header}"><svg class="ic" aria-hidden="true"><use href="#i-chevron-down" /></svg></button>
          </div>
        {/each}
      </div>

      <div style="height:{view.length * ROW_H}px; width:{totalWidth}px; position:relative">
        <div style="transform: translateY({startIdx * ROW_H}px)">
          {#each windowRows as row (row.id)}
            {@const errs = errorMap.get(row.id)}
            <div class="r" class:bad={errs} class:picked={checked.has(row.id)} style="height:{ROW_H}px" role="row" aria-rowindex={rowNumber.get(row.id) + 1}>
              <div class="gutter cell" style="width:{GUTTER}px">
                <input class="cb" type="checkbox" checked={checked.has(row.id)} onchange={() => toggleRow(row.id)} aria-label="Select row {rowNumber.get(row.id)}" />
                <span class="num" title={errs ? Object.values(errs).join("; ") : ""}>{#if errs}<svg class="ic warn" aria-hidden="true"><use href="#i-alert" /></svg>{:else}{rowNumber.get(row.id)}{/if}</span>
                <span class="mv"><button tabindex="-1" aria-label="Move row up" onclick={() => moveRow(row.id, -1)}><svg class="ic" aria-hidden="true"><use href="#i-arrow-up" /></svg></button><button tabindex="-1" aria-label="Move row down" onclick={() => moveRow(row.id, 1)}><svg class="ic" aria-hidden="true"><use href="#i-arrow-down" /></svg></button></span>
              </div>
              {#each columns as c (c.id)}
                {@const isSel = sel && sel.rowId === row.id && sel.colId === c.id}
                {@const fieldErr = c.field && errs ? errs[c.field] : null}
                <!-- svelte-ignore a11y_interactive_supports_focus, a11y_click_events_have_key_events -->
                <div class="cell" class:sel={isSel} class:err={fieldErr} style="width:{c.width}px" role="gridcell" aria-selected={isSel} aria-invalid={!!fieldErr} title={fieldErr || undefined}
                  onmousedown={() => { if (!(editing && editing.rowId === row.id && editing.colId === c.id)) { if (editing) finishEdit(true); sel = { rowId: row.id, colId: c.id }; } }}
                  ondblclick={() => beginEdit(row.id, c.id)}
                  onclick={() => { if (isSel && matchMedia("(pointer: coarse)").matches && !editing) beginEdit(row.id, c.id); }}>
                  {#if editing && editing.rowId === row.id && editing.colId === c.id}
                    <input class="ed" bind:value={editing.value} use:focusOnMount onkeydown={onEditKey} onblur={() => finishEdit(true)} />
                  {:else}
                    <span class="v">{row.c[c.id]}</span>
                  {/if}
                </div>
              {/each}
            </div>
          {/each}
        </div>
        {#if !view.length}
          <div class="none">{errorsOnly || search ? "No rows match your filter." : "No rows yet. Add one or paste from a spreadsheet."}</div>
        {/if}
      </div>
    </div>

    {#if colMenu}
      {@const mc = columns.find((c) => c.id === colMenu.colId)}
      {#if mc}
        <div class="cmenu" style="left:{colMenu.x}px; top:{colMenu.y}px" role="menu" tabindex="-1" onclick={(e) => e.stopPropagation()} onkeydown={(e) => e.stopPropagation()}>
          <label class="label" for="cm-map">Import this column as</label>
          <select id="cm-map" class="select sel-sm" value={mc.field || ""} onchange={(e) => { mapColumn(mc.id, e.currentTarget.value); colMenu = null; }}>
            <option value="">Not imported</option>
            {#each schema.fields as f (f.key)}<option value={f.key}>{f.label}{f.required ? " (required)" : ""}</option>{/each}
          </select>
          <hr class="divider" />
          <button role="menuitem" onclick={() => sortColumn(mc.id, 1)}><svg class="ic" aria-hidden="true"><use href="#i-arrow-up" /></svg>Sort A → Z</button>
          <button role="menuitem" onclick={() => sortColumn(mc.id, -1)}><svg class="ic" aria-hidden="true"><use href="#i-arrow-down" /></svg>Sort Z → A</button>
          <button role="menuitem" onclick={() => { renaming = mc.id; colMenu = null; }}><svg class="ic" aria-hidden="true"><use href="#i-edit" /></svg>Rename</button>
          <button role="menuitem" onclick={() => moveColumn(mc.id, -1)} disabled={colIndex(mc.id) === 0}><svg class="ic" aria-hidden="true"><use href="#i-chevron-left" /></svg>Move left</button>
          <button role="menuitem" onclick={() => moveColumn(mc.id, 1)} disabled={colIndex(mc.id) === columns.length - 1}><svg class="ic" aria-hidden="true"><use href="#i-chevron-right" /></svg>Move right</button>
          <button role="menuitem" class="danger" onclick={() => deleteColumn(mc.id)} disabled={columns.length <= 1}><svg class="ic" aria-hidden="true"><use href="#i-trash" /></svg>Delete column</button>
        </div>
      {/if}
    {/if}

    <div class="foot">
      <div class="summary" aria-live="polite">
        <b>{records.length.toLocaleString()}</b> {noun}{records.length === 1 ? "" : "s"}
        · <span class:ok={errorCount === 0 && records.length > 0}>{errorCount === 0 ? "all valid" : `${errorCount.toLocaleString()} need attention`}</span>
        {#if validating}<span class="faint"> · checking…</span>{/if}
      </div>
      <span class="sp"></span>
      {#if kind === "candidates"}<label class="check"><input class="cb" type="checkbox" bind:checked={createMissing} />Create missing positions</label>{/if}
      {#if errorCount > 0}<label class="check"><input class="cb" type="checkbox" bind:checked={skipInvalid} />Skip rows with errors</label>{/if}
      <button class="btn btn-primary" onclick={doImport} disabled={!canImport} class:is-loading={busy}>
        {importCount ? `Import ${importCount.toLocaleString()} ${noun}${importCount === 1 ? "" : "s"}` : "Nothing to import"}</button>
    </div>

  {:else if stage === "done"}
    <div class="done">
      <div class="okmark"><svg class="ic" aria-hidden="true"><use href="#i-check" /></svg></div>
      <h2>{result.message}</h2>
      {#if result.new_positions}<p class="muted">{result.new_positions} new position{result.new_positions === 1 ? "" : "s"} created.</p>{/if}
      {#if result.skipped}
        <div class="notice notice-warn skipnote"><svg class="ic" aria-hidden="true"><use href="#i-alert" /></svg><div><b>{result.skipped}</b> row{result.skipped === 1 ? " was" : "s were"} skipped because of errors.</div></div>
        <div class="row">
          <button class="btn" onclick={() => download(`rejected-${csvName()}`, rejectedCsv())}><svg class="ic" aria-hidden="true"><use href="#i-download" /></svg>Download skipped rows</button>
          <button class="btn" onclick={fixRejected}><svg class="ic" aria-hidden="true"><use href="#i-edit" /></svg>Fix them now</button>
        </div>
      {/if}
      <button class="btn btn-primary btn-lg" onclick={finish}>Done</button>
    </div>
  {/if}

  {#if dragging}<div class="dropveil"><svg class="ic ic-lg" aria-hidden="true"><use href="#i-upload" /></svg>Drop to load this file</div>{/if}
</div>

<style>
  .ce { position: relative; display: flex; flex-direction: column; flex: 1; min-height: 0; }
  .start { max-width: 640px; width: 100%; margin: 0 auto; padding: 28px 20px; display: grid; gap: 14px; overflow: auto; }
  .drop { display: grid; justify-items: center; gap: 6px; text-align: center; padding: 34px 20px; border: 1.5px dashed var(--border-strong); border-radius: 14px; cursor: pointer; background: var(--surface-2); color: var(--text-2); transition: border-color .15s, background .15s; }
  .drop:hover, .drag .drop { border-color: var(--accent); background: var(--accent-weak); }
  .drop b { color: var(--text); font-size: 15px; }
  .or { text-align: center; color: var(--text-3); font-size: 12px; text-transform: uppercase; letter-spacing: .08em; }
  .paste .row, .done .row { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 10px; }
  .bar { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; padding: 10px 16px; border-bottom: 1px solid var(--border); }
  .grow-s { flex: 0 1 260px; min-width: 150px; } .sp { flex: 1; }
  .bar .chip .n { margin-left: 2px; } .dot { width: 6px; height: 6px; border-radius: 50%; background: var(--danger); }
  .mapnote { margin: 10px 16px 0; } .maprow { display: inline-flex; align-items: center; gap: 8px; margin-right: 16px; }
  .sel-sm { height: 30px; font-size: 13px; min-width: 160px; width: auto; }
  .vp { flex: 1; min-height: 0; overflow: auto; position: relative; outline: none; margin-top: 10px; border-top: 1px solid var(--border); background: var(--bg-sunken); overscroll-behavior: contain; }
  .vp:focus-visible { box-shadow: inset 0 0 0 2px var(--accent-weak); }
  .head { position: sticky; top: 0; z-index: 3; display: flex; height: 38px; background: var(--surface-2); border-bottom: 1px solid var(--border-strong); }
  .hcell { position: relative; flex: none; display: flex; align-items: center; border-right: 1px solid var(--border); padding: 0 4px 0 12px; font-weight: 550; font-size: 12.5px; }
  .hcell.unmapped { background: color-mix(in srgb, var(--warn) 7%, var(--surface-2)); }
  .gutter { position: sticky; left: 0; z-index: 2; background: var(--surface-2); padding: 0 8px; display: flex; align-items: center; gap: 8px; }
  .hname { display: flex; align-items: center; gap: 8px; min-width: 0; flex: 1; background: none; border: 0; padding: 0; height: 100%; text-align: left; font-weight: 550; font-size: 12.5px; }
  .hname .t { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .tag { font-size: 10.5px; font-weight: 500; padding: 1px 6px; border-radius: 99px; background: var(--accent-weak); color: var(--accent); flex: none; }
  .tag.skip { background: var(--surface-3); color: var(--text-3); }
  .hmenu { width: 26px; height: 26px; display: grid; place-content: center; background: none; border: 0; border-radius: 6px; color: var(--text-3); }
  .hmenu:hover { background: var(--hover); color: var(--text); }
  .hedit { width: 100%; height: 26px; background: var(--bg); border: 1px solid var(--accent); border-radius: 5px; padding: 0 6px; outline: none; }
  .r { display: flex; border-bottom: 1px solid var(--grid-line); background: var(--surface); }
  .r:hover .cell, .r:hover .gutter { background: color-mix(in srgb, var(--surface) 92%, var(--text)); }
  .r.picked .cell, .r.picked .gutter { background: var(--accent-weak); }
  .r .gutter { background: var(--surface); border-right: 1px solid var(--border); }
  .num { font-size: 12px; color: var(--text-3); font-variant-numeric: tabular-nums; min-width: 28px; display: inline-flex; }
  .num .warn { color: var(--danger); }
  .mv { display: none; margin-left: auto; } .r:hover .mv { display: flex; } .r:hover .num { display: none; }
  .mv button { width: 20px; height: 22px; padding: 0; background: none; border: 0; color: var(--text-3); border-radius: 4px; display: grid; place-content: center; }
  .mv button:hover { background: var(--hover); color: var(--text); }
  .cell { position: relative; flex: none; display: flex; align-items: center; padding: 0 12px; border-right: 1px solid var(--grid-line); overflow: hidden; cursor: cell; }
  .cell .v { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .cell.err { background: var(--danger-weak); box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--danger) 55%, transparent); color: var(--text); }
  .cell.sel { box-shadow: inset 0 0 0 2px var(--accent); background: var(--accent-weak); z-index: 1; }
  .cell.err.sel { box-shadow: inset 0 0 0 2px var(--danger); }
  .ed { position: absolute; inset: 0; width: 100%; height: 100%; border: 2px solid var(--accent); outline: none; padding: 0 10px; background: var(--bg); color: var(--text); font: inherit; font-size: 14px; }
  .none { position: absolute; inset: 40px 0 auto; text-align: center; color: var(--text-3); padding: 24px; }
  .foot { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; padding: 12px 16px calc(12px + env(safe-area-inset-bottom, 0px)); border-top: 1px solid var(--border); background: var(--surface-2); }
  .summary { font-size: 13px; color: var(--text-2); } .summary b { color: var(--text); } .summary .ok { color: var(--success); }
  .cmenu { position: fixed; z-index: 200; width: 232px; padding: 12px; border-radius: 12px; background: var(--surface-2); box-shadow: var(--shadow-pop); display: grid; gap: 2px; }
  .cmenu .sel-sm { width: 100%; margin-top: 6px; }
  .cmenu button { display: flex; align-items: center; gap: 10px; height: 32px; padding: 0 8px; border: 0; border-radius: 6px; background: none; text-align: left; font-size: 13px; color: var(--text); }
  .cmenu button:hover:not(:disabled) { background: var(--hover); } .cmenu button:disabled { opacity: .4; } .cmenu .danger { color: var(--danger); }
  .cmenu .divider { margin: 8px 0; }
  .done { margin: auto; text-align: center; display: grid; gap: 14px; justify-items: center; padding: 40px 20px; max-width: 460px; }
  .okmark { width: 56px; height: 56px; border-radius: 50%; display: grid; place-content: center; background: var(--success-weak); color: var(--success); }
  .okmark .ic { width: 28px; height: 28px; stroke-width: 2.4; }
  .skipnote { text-align: left; }
  .dropveil { position: absolute; inset: 0; z-index: 50; display: grid; place-content: center; justify-items: center; gap: 10px; background: color-mix(in srgb, var(--bg) 82%, transparent); border: 2px dashed var(--accent); border-radius: 12px; font-weight: 600; pointer-events: none; }
  @media (max-width: 720px) {
    .bar { padding: 8px 10px; } .foot { padding-left: 10px; padding-right: 10px; } .foot .btn-primary { width: 100%; order: 9; }
    .grow-s { flex-basis: 100%; }
  }
</style>
