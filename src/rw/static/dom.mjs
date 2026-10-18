export function el(tag, attrs, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") node.className = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else if (key === "value") node.value = value;
    else if (key === "checked") node.checked = value;
    else node.setAttribute(key, value === true ? "" : String(value));
  }
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}
const paths = {
  back: ["M19 12H5m6-6-6 6 6 6"],
  arrow: ["M7 17 17 7M7 7h10v10"], chevron: ["m9 5 7 7-7 7"], down: ["m6 9 6 6 6-6"],
  close: ["m6 6 12 12M6 18 18 6"], plus: ["M12 5v14M5 12h14"],
  review: ["M9 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V9", "m9 13 3 3L22 6", "M9 3v5h5"],
  layers: ["m12 3 10 5-10 5L2 8l10-5Z", "m2 12 10 5 10-5M2 16l10 5 10-5"],
  graph: ["M8 7h8M7 8v8m1 1h8m1-9v8"], clock: ["M12 8v4l3 2"], check: ["m5 12 4 4L19 6"],
  alert: ["m12 3 10 18H2L12 3Z", "M12 9v4m0 4h.01"],
  shield: ["m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6l8-3Z", "m8 12 3 3 5-6"],
  sliders: ["M4 6h8m4 0h4M4 12h2m4 0h10M4 18h10m4 0h2", "M12 3v6M6 9v6m8 0v6"],
  info: ["M12 11v6m0-10h.01"], rollback: ["M3 10h11a6 6 0 0 1 0 12", "m7 6-4 4 4 4"],
  code: ["m8 7-5 5 5 5m8-10 5 5-5 5m-3-14-2 18"],
  database: ["M4 6v12c0 4 16 4 16 0V6M4 12c0 4 16 4 16 0"],
  file: ["M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6Z", "M14 2v6h6M8 13h8m-8 4h5"],
  play: ["m8 5 11 7-11 7V5Z"], search: ["m16 16 5 5"], menu: ["M4 6h16M4 12h16M4 18h16"],
};
const brandIcons = new Map([
  ["layers", "release"], ["release", "release"], ["code", "reader"], ["reader", "reader"],
  ["file", "record"], ["record", "record"], ["database", "store"], ["store", "store"],
  ["graph", "evidence-path"], ["evidence-path", "evidence-path"], ["review", "receipt"],
  ["receipt", "receipt"], ["probe", "probe"], ["snapshot", "snapshot"],
  ["shield", "approval"], ["approval", "approval"], ["rollback", "rollback"],
]);
export function icon(name, className = "") {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  Object.entries({ viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", "stroke-width": "1.65",
    "stroke-linecap": "round", "stroke-linejoin": "round", class: `icon ${className}`, "aria-hidden": "true" })
    .forEach(([key, value]) => svg.setAttribute(key, value));
  if (brandIcons.has(name)) {
    const use = document.createElementNS(svg.namespaceURI, "use");
    use.setAttribute("href", `/static/brand/icons.svg#${brandIcons.get(name)}`);
    svg.append(use);
    return svg;
  }
  for (const d of paths[name] || paths.file) {
    const path = document.createElementNS(svg.namespaceURI, "path"); path.setAttribute("d", d); svg.append(path);
  }
  if (["clock", "info", "search"].includes(name)) {
    const circle = document.createElementNS(svg.namespaceURI, "circle");
    circle.setAttribute("cx", name === "search" ? "10.5" : "12"); circle.setAttribute("cy", name === "search" ? "10.5" : "12");
    circle.setAttribute("r", name === "search" ? "6.5" : "9"); svg.prepend(circle);
  }
  if (name === "graph") for (const [cx, cy] of [[6, 6], [18, 6], [6, 18], [18, 18]]) {
    const circle = document.createElementNS(svg.namespaceURI, "circle");
    for (const [k, v] of Object.entries({ cx, cy, r: 2.5, fill: "var(--surface)" })) circle.setAttribute(k, v);
    svg.append(circle);
  }
  if (name === "database") {
    const oval = document.createElementNS(svg.namespaceURI, "ellipse");
    for (const [k, v] of Object.entries({ cx: 12, cy: 6, rx: 8, ry: 3 })) oval.setAttribute(k, v);
    svg.prepend(oval);
  }
  return svg;
}
export function button(text, onClick, options = {}) {
  const { variant = "primary", symbol, ...attrs } = options;
  return el("button", { type: "button", class: `button ${variant}`, onclick: onClick, ...attrs }, symbol ? icon(symbol) : null, text);
}
export function hash(value) {
  if (!value) return el("span", { class: "muted" }, "Unknown");
  let expanded = false;
  const node = button(String(value).replace(/^sha256:/, "").slice(0, 8) + "…", () => {
    expanded = !expanded; node.textContent = expanded ? value : String(value).replace(/^sha256:/, "").slice(0, 8) + "…";
    node.setAttribute("aria-expanded", String(expanded));
  }, { variant: "hash", title: "Expand full identity", "aria-expanded": "false" });
  return node;
}
export function panel(title, subtitle, content, action = null, className = "") {
  const symbol = panelSymbols.get(title);
  return el("section", { class: `panel ${className}` }, el("div", { class: "panel-heading" },
    el("div", {}, el("h2", { class: "panel-title" }, symbol ? icon(symbol) : null, title), subtitle ? el("p", {}, subtitle) : null), action), content);
}
const panelSymbols = new Map([
  ["Running services", "release"], ["What should the rollback do?", "rollback"],
  ["Proposed changes", "release"], ["Saved-data compatibility", "reader"],
  ["Evidence still needed", "evidence-path"], ["Why this is blocked — FalkorDB path", "evidence-path"],
  ["Local simulation", "approval"], ["Ready to simulate", "approval"], ["Simulation complete", "receipt"],
  ["Next step", "rollback"], ["Compare candidates", "release"],
]);
export function details(title, ...content) {
  return el("details", { class: "disclosure" }, el("summary", {}, title, icon("down")), ...content);
}
