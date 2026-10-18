import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";

const [html, css, js] = await Promise.all([
  readFile("index.html", "utf8"),
  readFile("styles.css", "utf8"),
  readFile("app.js", "utf8"),
]);

test("browser shell exposes the research workflow and safety framing", () => {
  for (const marker of [
    "not for diagnosis",
    "clinical monitoring",
    'id="scenario"',
    'id="algorithm"',
    'id="run-button"',
    'id="reset-button"',
    'id="chart"',
    'id="timeline"',
    "SIMULATED BENCHMARK SNAPSHOT",
  ]) assert.match(html, new RegExp(marker.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "i"));
  assert.match(html, /<script type="module" src="app\.js"><\/script>/);
});

test("renderer consumes the domain pipeline without generating random UI metrics", () => {
  assert.match(js, /import\s+\{\s*createSimulationRun\s*\}\s+from\s+["']\.\/src\/domain\/pipeline\.js["']/);
  assert.match(js, /state\.run\s*=\s*createSimulationRun\(config\)/);
  assert.match(js, /sample\.values\[channel\]/);
  assert.match(js, /window\.AuraMedUI/);
  assert.doesNotMatch(js, /Math\.random\(/);
});

test("responsive styling includes explicit uncertainty, signal, chart, and comparison treatments", () => {
  for (const marker of [".uncertainty-box", ".signal-grid", ".chart-wrap", ".comparison-table", "@media"]) assert.match(css, new RegExp(`\\${marker}`));
});
