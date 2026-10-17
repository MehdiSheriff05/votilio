import { describe, it, expect } from "vitest";
import { isValidEmail, normalizeHeader, validateRows } from "./validate.js";
import { buildSheet, parseText, toRecords, toCsv } from "./csv.js";

describe("headers", () => {
  it("maps aliases", () => {
    expect(normalizeHeader("E-mail")).toBe("email");
    expect(normalizeHeader(" Full Name ")).toBe("name");
    expect(normalizeHeader("Photo URL")).toBe("photo_url");
    expect(normalizeHeader("shoe size")).toBeNull();
  });
});

describe("email", () => {
  it("accepts and rejects", () => {
    expect(isValidEmail("a.b+c@example.co.uk")).toBe(true);
    for (const bad of ["", "plain", "a@b", "a b@example.com", "a@@example.com", "a@example..com"]) expect(isValidEmail(bad)).toBe(false);
  });
});

describe("voters", () => {
  it("flags missing, invalid and duplicate emails (case-insensitive)", () => {
    const errs = validateRows("voters", [
      { email: "a@example.com" },
      { email: "A@example.com" },
      { email: "" },
      { email: "nope" },
      { name: "x", email: "ok@example.com" },
    ]);
    expect(errs.map((e) => Object.keys(e).length)).toEqual([0, 1, 1, 1, 0]);
    expect(errs[1].email).toContain("Duplicate of row 1");
  });
});

describe("candidates", () => {
  it("requires position and name, validates urls, flags duplicates", () => {
    const rows = [
      { position: "President", name: "Amina" },
      { position: "president", name: "AMINA" },
      { position: "", name: "X" },
      { position: "President", name: "" },
      { position: "President", name: "Z", photo_url: "javascript:alert(1)" },
    ];
    const errs = validateRows("candidates", rows, { createMissing: true });
    expect(errs.map((e) => Object.keys(e)[0])).toEqual([undefined, "name", "position", "name", "photo_url"]);
  });
  it("rejects unknown positions unless creating them", () => {
    const rows = [{ position: "Treasurer", name: "P" }];
    expect(validateRows("candidates", rows, { positions: ["President"] })[0].position).toContain("Unknown");
    expect(validateRows("candidates", rows, { positions: ["President"], createMissing: true })[0]).toEqual({});
  });
});

describe("csv parsing", () => {
  it("handles BOM, quoted commas and semicolon delimiters", () => {
    const m = parseText('\ufeffname;email\n"Doe, Jane";jane@example.com\n');
    expect(m).toEqual([["name", "email"], ["Doe, Jane", "jane@example.com"]]);
  });
  it("builds a sheet with auto-mapped headers, in any column order", () => {
    const { columns, rows, hadHeader } = buildSheet("voters", parseText("Email Address,Notes,Full Name\na@example.com,x,Ann\n"));
    expect(hadHeader).toBe(true);
    expect(columns.map((c) => c.field)).toEqual(["email", null, "name"]);
    expect(toRecords("voters", columns, rows)[0].data).toEqual({ name: "Ann", email: "a@example.com" });
  });
  it("treats a headerless list as data and maps by content", () => {
    const { columns, rows, hadHeader } = buildSheet("voters", parseText("Ann,ann@example.com\nBob,bob@example.com\n"));
    expect(hadHeader).toBe(false);
    expect(columns.map((c) => c.field)).toEqual(["name", "email"]);
    expect(rows).toHaveLength(2);
  });
  it("drops blank rows and escapes formulas on export", () => {
    const { columns, rows } = buildSheet("voters", [["name", "email"], ["", ""], ["=EVIL()", "a@example.com"]]);
    expect(toRecords("voters", columns, rows)).toHaveLength(1);
    expect(toCsv(columns, rows)).toContain("'=EVIL()");
  });
});
