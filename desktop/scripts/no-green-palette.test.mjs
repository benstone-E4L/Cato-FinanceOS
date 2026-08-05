import assert from "node:assert/strict";
import { readFile, readdir } from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const sourceRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../src");
const sourceExtensions = new Set([".css", ".html", ".ts", ".tsx"]);
const prohibitedNames = new RegExp(`\\b${["green", "emerald", "lime", "teal", "cyan"].join("|")}\\b`, "i");

async function sourceFiles(directory) {
  const entries = await readdir(directory, { withFileTypes: true });
  const nested = await Promise.all(entries.map(async (entry) => {
    const target = path.join(directory, entry.name);
    if (entry.isDirectory()) return sourceFiles(target);
    return sourceExtensions.has(path.extname(entry.name)) ? [target] : [];
  }));
  return nested.flat();
}

function hueForRgb(red, greenChannel, blue) {
  const r = red / 255;
  const g = greenChannel / 255;
  const b = blue / 255;
  const maximum = Math.max(r, g, b);
  const minimum = Math.min(r, g, b);
  const delta = maximum - minimum;
  if (delta === 0) return { hue: 0, saturation: 0 };
  let hue;
  if (maximum === r) hue = 60 * (((g - b) / delta) % 6);
  else if (maximum === g) hue = 60 * ((b - r) / delta + 2);
  else hue = 60 * ((r - g) / delta + 4);
  if (hue < 0) hue += 360;
  return { hue, saturation: maximum === 0 ? 0 : delta / maximum };
}

function prohibitedHexes(line) {
  const matches = [];
  const hexPattern = /(?<!&)#([0-9a-f]{3,4}|[0-9a-f]{6}|[0-9a-f]{8})\b/gi;
  for (const match of line.matchAll(hexPattern)) {
    let value = match[1];
    if (value.length === 3 || value.length === 4) value = value.slice(0, 3).split("").map((digit) => digit + digit).join("");
    else value = value.slice(0, 6);
    const { hue, saturation } = hueForRgb(
      Number.parseInt(value.slice(0, 2), 16),
      Number.parseInt(value.slice(2, 4), 16),
      Number.parseInt(value.slice(4, 6), 16),
    );
    if (saturation >= 0.2 && hue >= 75 && hue <= 195) matches.push(match[0]);
  }
  return matches;
}

function prohibitedFunctionalColors(line) {
  const matches = [];
  const rgbPattern = /rgba?\(\s*(\d+(?:\.\d+)?)\s*,\s*(\d+(?:\.\d+)?)\s*,\s*(\d+(?:\.\d+)?)/gi;
  for (const match of line.matchAll(rgbPattern)) {
    const { hue, saturation } = hueForRgb(...match.slice(1, 4).map(Number));
    if (saturation >= 0.2 && hue >= 75 && hue <= 195) matches.push(match[0]);
  }
  const hslPattern = /hsla?\(\s*(-?\d+(?:\.\d+)?)(?:deg)?\b/gi;
  for (const match of line.matchAll(hslPattern)) {
    const hue = ((Number(match[1]) % 360) + 360) % 360;
    if (hue >= 75 && hue <= 195) matches.push(match[0]);
  }
  return matches;
}

test("the complete desktop source contains no prohibited palette colors or semantic names", async () => {
  const failures = [];
  for (const file of await sourceFiles(sourceRoot)) {
    const lines = (await readFile(file, "utf8")).split(/\r?\n/);
    lines.forEach((line, index) => {
      const names = prohibitedNames.test(line) ? [line.match(prohibitedNames)?.[0]] : [];
      const colors = [...prohibitedHexes(line), ...prohibitedFunctionalColors(line)];
      if (names.length || colors.length) {
        failures.push(`${path.relative(sourceRoot, file)}:${index + 1}: ${[...names, ...colors].join(", ")}`);
      }
    });
  }
  assert.deepEqual(failures, [], `Prohibited desktop colors found:\n${failures.join("\n")}`);
});
