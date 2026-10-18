import Papa from "papaparse";
import { SCHEMAS, normalizeHeader } from "./validate.js";

export const MAX_BYTES = 8 * 1024 * 1024;
export const MAX_ROWS = 20000;
const BOM = "\ufeff";

let uid = 0;
export const nextId = () => ++uid;

const colLetter = (n) => {
  let s = "";
  for (n += 1; n > 0; n = Math.floor((n - 1) / 26)) s = String.fromCharCode(65 + ((n - 1) % 26)) + s;
  return s;
};

export function widthFor(kind, field) {
  const f = SCHEMAS[kind].fields.find((x) => x.key === field);
  return f ? f.width : 200;
}

export function defaultColumns(kind) {
  return SCHEMAS[kind].fields.map((f) => ({ id: nextId(), header: f.label, field: f.key, width: f.width }));
}

export function emptyRow(columns) {
  return { id: nextId(), c: Object.fromEntries(columns.map((c) => [c.id, ""])) };
}

function detectBare(kind, data) {
  const width = Math.max(...data.map((r) => r.length));
  const out = new Array(width).fill(null);
  if (kind === "voters") {
    const idx = Array.from({ length: width }, (_, i) => i);
    const emailCol = idx.find((i) => data.slice(0, 5).some((r) => String(r[i] ?? "").includes("@")));
    if (emailCol != null) {
      out[emailCol] = "email";
      const nameCol = idx.find((i) => i !== emailCol);
      if (nameCol != null) out[nameCol] = "name";
    }
  } else {
    ["position", "name", "bio", "photo_url"].forEach((f, i) => { if (i < width) out[i] = f; });
  }
  return out;
}

/** Turns a parsed matrix into {columns, rows}. Detects a header row and auto-maps columns to schema fields. */
export function buildSheet(kind, matrix) {
  const fields = SCHEMAS[kind].fields;
  const data = matrix.filter((r) => r.some((c) => String(c ?? "").trim() !== ""));
  if (!data.length) return { columns: defaultColumns(kind), rows: [], hadHeader: false };
  const first = data[0];
  const mapped = first.map(normalizeHeader);
  const hasHeader = mapped.some(Boolean);
  const width = Math.max(...data.map((r) => r.length));
  const used = new Set();
  const columns = [];
  for (let i = 0; i < width; i++) {
    const guess = hasHeader ? mapped[i] : null;
    const field = guess && !used.has(guess) && fields.some((f) => f.key === guess) ? guess : null;
    if (field) used.add(field);
    columns.push({
      id: nextId(),
      header: hasHeader ? String(first[i] ?? "").trim() || colLetter(i) : colLetter(i),
      field,
      width: widthFor(kind, field),
    });
  }
  if (!hasHeader) {
    const detected = detectBare(kind, data);
    columns.forEach((c, i) => {
      const f = detected[i];
      if (f) {
        c.field = f;
        c.header = fields.find((x) => x.key === f).label;
        c.width = widthFor(kind, f);
      }
    });
  }
  const body = hasHeader ? data.slice(1) : data;
  const rows = body.map((r) => ({ id: nextId(), c: Object.fromEntries(columns.map((col, i) => [col.id, String(r[i] ?? "")])) }));
  return { columns, rows, hadHeader: hasHeader };
}

export function parseText(text) {
  const clean = text.charCodeAt(0) === 0xfeff ? text.slice(1) : text;
  return Papa.parse(clean, { skipEmptyLines: "greedy", delimitersToGuess: [",", ";", "\t", "|"] }).data;
}

export function parseFile(file) {
  return new Promise((resolve, reject) => {
    if (file.size > MAX_BYTES) return reject(new Error("That file is larger than 8 MB."));
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("Couldn't read that file."));
    reader.onload = () => {
      try { resolve(parseText(String(reader.result))); } catch (e) { reject(new Error("That doesn't look like a CSV file.")); }
    };
    reader.readAsText(file);
  });
}

/** Maps sheet rows to schema dicts, dropping fully blank rows. Returns [{id, data}] */
export function toRecords(kind, columns, rows) {
  const map = {};
  for (const c of columns) if (c.field && !(c.field in map)) map[c.field] = c.id;
  const out = [];
  for (const row of rows) {
    const data = {};
    for (const f of SCHEMAS[kind].fields) data[f.key] = map[f.key] ? String(row.c[map[f.key]] ?? "") : "";
    if (Object.values(data).some((v) => v.trim() !== "")) out.push({ id: row.id, data });
  }
  return out;
}

export function toCsv(columns, rows) {
  const fields = columns.map((c) => c.header);
  const data = rows.map((r) => columns.map((c) => r.c[c.id] ?? ""));
  return Papa.unparse({ fields, data }, { escapeFormulae: true });
}

export function download(filename, text) {
  const blob = new Blob([BOM + text], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
