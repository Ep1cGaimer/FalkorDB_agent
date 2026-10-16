// Dependency-free browser acceptance check, using an isolated headless Chromium profile.
// Start tests/ui/serve_fixture.py first. UI_BROWSER_BINARY overrides the browser executable.
// Screenshots go to the ignored artifacts/screens/ui-refactor directory.
import { spawn } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { createServer } from "node:net";
import assert from "node:assert/strict";

const base = process.env.UI_BASE_URL || "http://127.0.0.1:8002";
const binary = process.env.UI_BROWSER_BINARY || [
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
  "C:/Program Files/Google/Chrome/Application/chrome.exe",
  "/usr/bin/chromium", "/usr/bin/google-chrome",
].find(existsSync);
if (!binary) throw new Error("Set UI_BROWSER_BINARY to a Chromium browser executable.");
const output = resolve("artifacts/screens/decision-review"); mkdirSync(output, { recursive: true });
const profile = mkdtempSync(join(tmpdir(), "rw-browser-qa-"));
const port = await new Promise(resolvePort => {
  const server = createServer(); server.listen(0, "127.0.0.1", () => { const p = server.address().port; server.close(() => resolvePort(p)); });
});
const child = spawn(binary, ["--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
  "--disable-background-networking", `--remote-debugging-port=${port}`, `--user-data-dir=${profile}`, "about:blank"],
  { stdio: "ignore", windowsHide: true });
let ws, sequence = 0;
const pending = new Map(), exceptions = [], networkFailures = [];
const pause = ms => new Promise(r => setTimeout(r, ms));
async function until(fn, label, timeout = 20000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) { const value = await fn(); if (value) return value; await pause(100); }
  throw new Error(`Timed out: ${label}`);
}
function send(method, params = {}) {
  return new Promise((resolveCall, reject) => {
    const id = ++sequence;
    const timer = setTimeout(() => { pending.delete(id); reject(new Error(`CDP timeout: ${method}`)); }, 25000);
    pending.set(id, { resolve: result => { clearTimeout(timer); resolveCall(result); }, reject: error => { clearTimeout(timer); reject(error); } });
    ws.send(JSON.stringify({ id, method, params }));
  });
}
async function evaluate(expression) {
  const result = await send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
  if (result.exceptionDetails) throw new Error(result.exceptionDetails.exception?.description || result.exceptionDetails.text);
  return result.result.value;
}
const body = () => evaluate("document.body.innerText");
const waitText = text => until(async () => (await body()).includes(text), `visible text ${text}`);
const click = selector => evaluate(`(() => { const n=document.querySelector(${JSON.stringify(selector)}); if(!n)throw Error('Missing click target'); if(n.disabled)throw Error('Disabled click target'); n.click(); })()`);
const clickText = text => evaluate(`(() => { const n=[...document.querySelectorAll('button')].find(x=>x.textContent.trim()===${JSON.stringify(text)}); if(!n)throw Error('Missing button: '+${JSON.stringify(text)}); if(n.disabled)throw Error('Disabled button'); n.click(); })()`);
const fill = (selector, value) => evaluate(`(() => { const n=document.querySelector(${JSON.stringify(selector)}); if(!n)throw Error('Missing field'); n.value=${JSON.stringify(value)}; n.dispatchEvent(new Event('input',{bubbles:true})); })()`);
const select = (selector, value) => evaluate(`(() => { const n=document.querySelector(${JSON.stringify(selector)}); n.value=${JSON.stringify(value)}; n.dispatchEvent(new Event('change',{bubbles:true})); })()`);
async function travel(delta) {
  const navigation = await send("Page.getNavigationHistory");
  const target = navigation.entries[navigation.currentIndex + delta];
  assert(target, `history entry exists for ${delta > 0 ? "Forward" : "Back"}`);
  await send("Page.navigateToHistoryEntry", { entryId: target.id });
}
const idle = () => until(() => evaluate("document.querySelector('#workspace')?.getAttribute('aria-busy') === 'false'"), "navigation finished");
async function reloadView(expression, label) {
  const origin = await evaluate("performance.timeOrigin");
  await send("Page.reload");
  await until(() => evaluate(`performance.timeOrigin !== ${origin} && (${expression}) && document.querySelector('#workspace')?.getAttribute('aria-busy')==='false'`), label);
}
async function screenshot(name, full = false) {
  await send("Runtime.evaluate", { expression: "document.activeElement?.blur()" });
  const metrics = await send("Page.getLayoutMetrics");
  const params = { format: "png", captureBeyondViewport: true };
  if (full) params.clip = { x: 0, y: 0, width: metrics.cssContentSize.width, height: metrics.cssContentSize.height, scale: 1 };
  else params.clip = { x: metrics.cssVisualViewport.pageX, y: metrics.cssVisualViewport.pageY,
    width: metrics.cssVisualViewport.clientWidth, height: metrics.cssVisualViewport.clientHeight, scale: 1 };
  const capture = await send("Page.captureScreenshot", params);
  writeFileSync(join(output, `${name}.png`), Buffer.from(capture.data, "base64"));
}
async function setSnapshot(name) {
  await click("#settings-trigger"); await select("#snapshot-select", name); await clickText("Done");
}
async function confirm() {
  await until(() => evaluate("!!document.querySelector('#confirm-button')"), "fleet proposal");
  assert.equal(await evaluate("document.querySelectorAll('#operator-name, #approver-name').length"), 0);
  await click("#confirm-button");
  await until(() => evaluate("!!document.querySelector('.verdict-title')"), "verification result");
}

try {
  const version = await until(async () => {
    try { return await (await fetch(`http://127.0.0.1:${port}/json/version`)).json(); } catch { return false; }
  }, "isolated browser startup");
  const target = await (await fetch(`http://127.0.0.1:${port}/json/new?about:blank`, { method: "PUT" })).json();
  ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolveOpen, reject) => { ws.addEventListener("open", resolveOpen, { once: true }); ws.addEventListener("error", reject, { once: true }); });
  ws.addEventListener("message", event => {
    const message = JSON.parse(event.data);
    if (message.id && pending.has(message.id)) {
      const call = pending.get(message.id); pending.delete(message.id);
      if (message.error) call.reject(new Error(message.error.message)); else call.resolve(message.result);
    } else if (message.method === "Runtime.exceptionThrown") exceptions.push(message.params.exceptionDetails);
    else if (message.method === "Network.loadingFailed" && !message.params.canceled) networkFailures.push(message.params);
  });
  await send("Page.enable"); await send("Runtime.enable"); await send("Network.enable");
  await send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false });
  await send("Page.navigate", { url: base });
  await waitText("Review a rollback");
  await until(() => evaluate("!!document.querySelector('#start-button') && document.body.innerText.includes('saved-cart-2002')"), "initial inventory");
  assert.equal(await evaluate("document.querySelectorAll('[role=tab], #history-search, .summary-stats, .how-it-works, .workspace-label, .avatar').length"), 0);
  assert.equal(await evaluate("document.querySelector('#sidebar').innerText.split(/\\s+/).includes('null')"), false);
  for (const removed of ["From request to decision", "Check summary", "Run context", "Investigation history", "About this demo", "Prefill guided demo inputs"]) {
    assert(!(await body()).includes(removed), `${removed} was removed`);
  }
  await screenshot("01-workspace");
  assert((await body()).includes("Basket feature: On"));
  assert((await body()).includes("Single-list cart · cart/v1"));
  const beforeHelp = await (await fetch(`${base}/api/investigations`)).json();
  await click("button[aria-label='Basket feature: an on/off setting']");
  await waitText("Existing saved carts are not converted or deleted.");
  await screenshot("08-feature-help");
  await reloadView("document.querySelector('#dialog-title')?.textContent==='Basket feature: an on/off setting'", "reload restores contextual explanation");
  await travel(-1); await until(() => evaluate("!document.querySelector('dialog')"), "Back closes explanation");
  await travel(1); await waitText("Existing saved carts are not converted or deleted.");
  await clickText("Done");
  await until(() => evaluate("!document.querySelector('dialog')"), "feature explanation closes");
  await send("Page.bringToFront");
  await evaluate("document.querySelector('button[aria-label=\"How much saved data is covered?\"]').focus()");
  assert.equal(await evaluate("document.activeElement?.getAttribute('aria-label')"), "How much saved data is covered?");
  await send("Input.dispatchKeyEvent", { type: "keyDown", key: "Enter", code: "Enter", windowsVirtualKeyCode: 13, text: "\r", unmodifiedText: "\r" });
  await send("Input.dispatchKeyEvent", { type: "keyUp", key: "Enter", code: "Enter", windowsVirtualKeyCode: 13 });
  await waitText("Partial means some records may be absent");
  await clickText("Done");
  await until(() => evaluate("!document.querySelector('dialog')"), "coverage explanation closes");
  await click("button[aria-label='What is a data format?']"); await waitText("cart/v2 adds named baskets"); await clickText("Done");
  await until(() => evaluate("!document.querySelector('dialog')"), "format explanation closes");
  const afterHelp = await (await fetch(`${base}/api/investigations`)).json();
  assert.equal(afterHelp.length, beforeHelp.length, "opening explanations never starts an investigation");
  console.log("PASS contextual help works with keyboard, Back/Forward and refresh without triggering checks");
  const draft = await evaluate("document.querySelector('#request').value + ' Keep Checkout 2.1.'");
  await fill("#request", draft);
  await click("#start-button"); await confirm();
  await waitText("This rollback is blocked");
  assert.equal(await evaluate("!!document.querySelector('#approve-button')"), false);
  assert((await body()).includes("Startup check"));
  await click("button[aria-label='Why this proposal is blocked']");
  await waitText("Other passing reads, or a successful startup, do not cancel that failure."); await clickText("Done");
  const investigationId = await evaluate("location.hash.split('/')[1]");
  const investigationsBefore = await (await fetch(`${base}/api/investigations`)).json();
  await travel(-1);
  await until(() => evaluate("!!document.querySelector('#request')"), "Back restores the request");
  assert.equal(await evaluate("document.querySelector('#request').value"), draft);
  await travel(1); await waitText("This rollback is blocked"); await idle();
  assert.equal(await evaluate("location.hash.split('/')[1]"), investigationId);
  await click("#back-button");
  await until(() => evaluate("!!document.querySelector('#request')"), "visible Back restores the request");
  assert.equal(await evaluate("document.querySelector('#request').value"), draft);
  await travel(1); await waitText("This rollback is blocked"); await idle();
  const investigationsAfter = await (await fetch(`${base}/api/investigations`)).json();
  assert.equal(investigationsAfter.length, investigationsBefore.length, "navigation creates no new investigation");
  console.log("PASS browser Back/Forward and visible Back preserve the draft and checked result");
  await screenshot("02-blocked", true);
  await click(".map-record"); await waitText("unsupported saved-cart format");
  assert((await body()).includes("Read check details"));
  await travel(-1); await until(() => evaluate("!document.querySelector('dialog')"), "browser Back closes receipt");
  assert((await body()).includes("This rollback is blocked"));
  await travel(1); await until(() => evaluate("!!document.querySelector('dialog')"), "Forward restores receipt");
  assert((await body()).includes("unsupported saved-cart format"));
  await reloadView("document.querySelector('#dialog-title')?.textContent==='Read check details'", "reload restores open receipt");
  assert((await body()).includes("unsupported saved-cart format"));
  await screenshot("03-receipt");
  await send("Input.dispatchKeyEvent", { type: "keyDown", key: "Escape", code: "Escape", windowsVirtualKeyCode: 27 });
  await send("Input.dispatchKeyEvent", { type: "keyUp", key: "Escape", code: "Escape", windowsVirtualKeyCode: 27 });
  await until(() => evaluate("!document.querySelector('dialog')"), "Escape closes inspector");
  const confirmed = await evaluate("fetch('/api/investigations/'+location.hash.split('/')[1]).then(r=>r.json())");
  assert.equal(confirmed.attempts.at(-1).report.scope_confirmation.confirmed_by, "local-ui-user");
  await clickText("Cited sources"); await waitText("Source identity"); await clickText("Done");
  await click("#alternative-button");
  await until(() => evaluate("!!document.querySelector('#confirm-button')"), "alternative proposal");
  await confirm(); await waitText("Saved-data checks passed");
  assert.equal(await evaluate("document.querySelector('.map-record strong').textContent"), "saved-cart-2002", "alternative keeps the original failing record in focus");
  await screenshot("04-alternative", true);
  assert((await body()).includes("Basket feature: Off"));
  assert.equal(await evaluate("document.querySelectorAll('.candidate-choice button').length"), 0, "candidate buttons do not contain nested help buttons");
  await click("button[aria-label='What a bounded pass means']"); await waitText("It does not establish production safety"); await clickText("Done");
  assert.equal(await evaluate("!!document.querySelector('#approver-name')"), false);
  await click("#approve-button"); await waitText("Run local simulation");
  const approved = await evaluate("fetch('/api/investigations/'+location.hash.split('/')[1]).then(r=>r.json())");
  assert.equal(approved.attempts.at(-1).approval.approved_by, "local-ui-user");
  await clickText("Run local simulation"); await waitText("Local simulation recorded. No deployment occurred.");
  assert.equal(await evaluate("!!document.querySelector('#simulate-button')"), false);
  await evaluate("document.querySelector('.next-step details summary').click()");
  await clickText("Repeat simulation"); await waitText("Already simulated. This repeat request changed nothing.");
  await click("[data-candidate='0']");
  await waitText("This rollback is blocked");
  assert.equal(await evaluate("!!document.querySelector('#approve-button')"), false);
  await travel(-1); await waitText("Saved-data checks passed");
  assert((await body()).includes("Already simulated. This repeat request changed nothing."));
  await travel(1); await waitText("This rollback is blocked");
  await reloadView("document.querySelector('.verdict-title')?.textContent.includes('blocked')", "reload restores the chosen candidate");
  assert.equal(await evaluate("document.querySelector('[data-candidate=\"0\"]').getAttribute('aria-pressed')"), "true");
  const afterReload = await evaluate("fetch('/api/investigations/'+location.hash.split('/')[1]).then(r=>r.json())");
  assert.equal(afterReload.attempts.at(-1).simulation.applied, false, "refresh did not rerun simulation");
  console.log("PASS candidate navigation and reload preserve selected candidate and simulation receipt");
  console.log("PASS blocked → receipt → alternative → bounded pass → approval → idempotent simulation");

  await clickText("New investigation");
  await click("#back-button"); await waitText("This rollback is blocked"); await idle();
  await travel(1); await until(() => evaluate("!!document.querySelector('#request')"), "Forward restores the new request");
  await setSnapshot("snap-002-partial");
  await click("#start-button"); await confirm(); await waitText("This rollback is blocked");
  await click("#alternative-button"); await confirm(); await waitText("More evidence is needed");
  assert.equal(await evaluate("!!document.querySelector('#approve-button')"), false);
  await screenshot("05-needs-evidence", true);
  console.log("PASS partial inventory remains NEEDS_EVIDENCE after passing modeled reads");

  await clickText("New investigation"); await setSnapshot("snap-003-orphan");
  await click("#start-button"); await confirm(); await waitText("This rollback is blocked");
  await click("#alternative-button"); await confirm(); await waitText("More evidence is needed");
  assert((await body()).includes("Writer unknown"));
  console.log("PASS orphan provenance remains an evidence gap");

  await clickText("New investigation"); await setSnapshot("snap-001");
  await fill("#request", "Clarify which Checkout behavior to retain before changing Cart.");
  await click("#start-button"); await waitText("One detail needs your decision");
  await fill("#clarification-answer", "Keep Checkout 2.1 and change Cart only.");
  await click("#answer-button"); await confirm(); await waitText("This rollback is blocked");
  await evaluate("document.querySelector('.request-summary details summary').click()");
  assert((await body()).includes("Keep Checkout 2.1 and change Cart only."));
  console.log("PASS clarification answer controls the proposed scope");

  await clickText("New investigation");
  await click("#settings-trigger"); await click("#mode-replay");
  const saved = await evaluate("[...document.querySelector('#replay')?.options || []].find(o=>o.textContent.startsWith('Fleet proposal'))?.value");
  if (saved) {
    await select("#replay", saved); await clickText("Done"); await click("#start-button"); await confirm();
    assert((await body()).includes("Replay · not live"));
    console.log("PASS saved replay uses actual reader checks and retains its replay label");
  } else { await clickText("Done"); console.log("SKIP saved replay: no recorded proposal available locally"); }

  await clickText("New investigation"); await click("#settings-trigger");
  const question = await evaluate("[...document.querySelector('#replay')?.options || []].find(o=>o.textContent.startsWith('Clarification'))?.value");
  if (question) {
    await select("#replay", question); await clickText("Done"); await click("#start-button");
    await waitText("One detail needs your decision");
    assert.equal(await evaluate("!!document.querySelector('#guided-inputs')"), false);
    const hasAnswer = await evaluate("!!document.querySelector('#answerReplay')");
    if (hasAnswer) {
      await click("#answer-button"); await confirm();
      assert((await body()).includes("Replay · not live"));
      console.log("PASS recorded clarification selects an exact bound answer without guided inputs");
    } else console.log("SKIP replay clarification: no recorded answer available");
  } else { await clickText("Done"); console.log("SKIP replay clarification: no recorded question available"); }

  await clickText("New investigation"); await click("#settings-trigger"); await click("#mode-live"); await clickText("Done");
  await send("Emulation.setDeviceMetricsOverride", { width: 390, height: 844, deviceScaleFactor: 1, mobile: false });
  await screenshot("06-mobile", true);
  assert(await evaluate("document.documentElement.scrollWidth <= window.innerWidth"), "mobile page has no horizontal overflow");
  await click(".mobile-menu");
  assert(await evaluate("document.querySelector('.sidebar').classList.contains('open')"));
  await click(".recent-list .recent");
  await waitText("Rollback investigation");
  assert.equal(await evaluate("document.querySelector('.sidebar').classList.contains('open')"), false);
  assert(await evaluate("document.documentElement.scrollWidth <= window.innerWidth"), "active mobile review has no horizontal overflow");
  await screenshot("07-mobile-review", true);
  console.log("PASS mobile navigation reopens a real investigation");

  await send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false });
  await clickText("New investigation"); await click("#settings-trigger"); await click("#mode-live"); await clickText("Done");
  await fill("#request", draft); await click("#start-button");
  await until(() => evaluate("!!document.querySelector('#confirm-button')"), "proposal before delayed check");
  await send("Network.emulateNetworkConditions", { offline: false, latency: 250, downloadThroughput: -1, uploadThroughput: -1 });
  await click("#confirm-button"); await travel(-1);
  await until(() => evaluate("!!document.querySelector('#request') && document.querySelector('#workspace').getAttribute('aria-busy')==='false'"), "Back completes after the in-flight check");
  assert.equal(await evaluate("document.querySelector('#request').value"), draft);
  await send("Network.emulateNetworkConditions", { offline: false, latency: 0, downloadThroughput: -1, uploadThroughput: -1 });
  await travel(1); await waitText("This rollback is blocked"); await idle();
  console.log("PASS Back during an in-flight check keeps both draft and completed evidence");

  const directId = await evaluate("location.hash.split('/')[1]");
  const oldOrigin = await evaluate("performance.timeOrigin");
  await send("Page.navigate", { url: `${base}?direct=1#investigation/${directId}` });
  await until(() => evaluate(`performance.timeOrigin !== ${oldOrigin} && document.querySelector('.verdict-title')?.textContent.includes('blocked') && document.querySelector('#workspace').getAttribute('aria-busy')==='false'`), "direct investigation link");
  assert.equal(await evaluate("history.state.index"), 0);
  await click("#back-button"); await until(() => evaluate("!!document.querySelector('#request')"), "direct-link Back stays in app");
  assert.equal(await evaluate("document.querySelector('#request').value"), draft);
  await travel(-1); await waitText("This rollback is blocked"); await idle();
  console.log("PASS a direct link has a safe visible Back destination");
  assert.equal(exceptions.length, 0, JSON.stringify(exceptions, null, 2));
  assert.equal(networkFailures.length, 0, JSON.stringify(networkFailures, null, 2));
  console.log(`PASS no browser exceptions or failed resource requests · ${version.Browser}`);
  console.log(`Screenshots: ${output}`);
} catch (error) {
  if (ws?.readyState === WebSocket.OPEN) {
    console.error("Visible page:", await body().catch(() => "unavailable"));
    await screenshot("failure", true).catch(() => {});
  }
  throw error;
} finally {
  if (ws?.readyState === WebSocket.OPEN) { await send("Browser.close").catch(() => {}); ws.close(); }
  if (child.exitCode === null) child.kill();
}
