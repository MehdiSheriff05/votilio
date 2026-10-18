// Mirrors app/imports.py. The server re-validates everything; this gives instant feedback.

export const SCHEMAS = {
  voters: {
    fields: [
      { key: "name", label: "Name", required: false, width: 220 },
      { key: "email", label: "Email", required: true, width: 280 },
    ],
  },
  candidates: {
    fields: [
      { key: "position", label: "Position", required: true, width: 180 },
      { key: "name", label: "Name", required: true, width: 200 },
      { key: "bio", label: "Bio", required: false, width: 320 },
      { key: "photo_url", label: "Photo URL", required: false, width: 280 },
    ],
  },
};

const ALIASES = {
  name: ["name", "full name", "fullname", "voter", "voter name", "candidate", "candidate name", "member"],
  email: ["email", "e-mail", "email address", "mail", "e mail"],
  position: ["position", "role", "office", "post", "seat", "title"],
  bio: ["bio", "description", "about", "manifesto", "summary", "statement"],
  photo_url: ["photo_url", "photo", "image", "image_url", "photo url", "picture", "avatar", "headshot"],
};

export const MAX_LEN = { name: 128, email: 255, position: 128, bio: 2000, photo_url: 255 };

const EMAIL_RE = /^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)+$/;
const URL_RE = /^https?:\/\/[^\s/$.?#][^\s]*$/i;
const CONTROL_CHARS = /[\u0000-\u0008\u000b\u000c\u000e-\u001f]/g;

export function normalizeHeader(raw) {
  const key = String(raw ?? "").trim().toLowerCase().replace(/[\s_-]+/g, " ");
  for (const [field, aliases] of Object.entries(ALIASES)) {
    if (aliases.includes(key) || key.replace(/ /g, "_") === field) return field;
  }
  return null;
}

export function isValidEmail(value) {
  return !!value && value.length <= MAX_LEN.email && EMAIL_RE.test(value);
}

export const clean = (v) => String(v ?? "").replace(CONTROL_CHARS, "").trim();

/** rows: array of {field: value}. Returns array of {field: message} (empty object when valid). */
export function validateRows(kind, rows, ctx = {}) {
  const positions = new Set((ctx.positions || []).map((p) => p.toLowerCase()));
  const strictPositions = kind === "candidates" && !ctx.createMissing;
  const seenEmail = new Map();
  const seenCand = new Map();
  return rows.map((raw, i) => {
    const row = {};
    for (const f of SCHEMAS[kind].fields) row[f.key] = clean(raw[f.key]);
    const errors = {};
    if (kind === "voters") {
      const email = row.email;
      if (!email) errors.email = "Email is required";
      else if (!isValidEmail(email)) errors.email = "Not a valid email address";
      else if (seenEmail.has(email.toLowerCase())) errors.email = `Duplicate of row ${seenEmail.get(email.toLowerCase()) + 1}`;
      else seenEmail.set(email.toLowerCase(), i);
    } else {
      if (!row.position) errors.position = "Position is required";
      else if (strictPositions && !positions.has(row.position.toLowerCase())) errors.position = "Unknown position (turn on 'create missing positions' or fix the name)";
      if (!row.name) errors.name = "Name is required";
      if (row.photo_url && !URL_RE.test(row.photo_url)) errors.photo_url = "Must be a full http(s) link";
      if (!errors.position && !errors.name) {
        const k = row.position.toLowerCase() + " " + row.name.toLowerCase();
        if (seenCand.has(k)) errors.name = `Duplicate of row ${seenCand.get(k) + 1}`;
        else seenCand.set(k, i);
      }
    }
    for (const [field, limit] of Object.entries(MAX_LEN)) {
      if (row[field] && row[field].length > limit && !errors[field]) errors[field] = `Too long (max ${limit})`;
    }
    return errors;
  });
}
