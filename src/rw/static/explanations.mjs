import { el, icon, button } from "./dom.mjs";

// Domain identifiers come from evidence, never from a fixture-specific alias table.
export const formatText = format => !format || format === "UNKNOWN" ? "Unknown format" : format;

export const flagText = (_service, name, enabled) =>
  `${name}: ${enabled === true ? "On" : enabled === false ? "Off" : "Unknown"}`;

const explanations = {
  flags: {
    title: "Feature settings",
    paragraphs: ["Feature flags are on/off settings within a software version. They let a proposal change selected behavior without installing an older build. Their effect comes from the release's source evidence; changing a flag does not itself prove compatibility with saved data."],
  },
  versions: {
    title: "Services and software versions",
    paragraphs: [
      "Services are independently versioned parts of the selected system. The running-service list comes from its snapshot; proposed versions come from the grounded plan. Version identifiers name builds, not compatibility guarantees.",
      "The proposal is the set of service versions and settings used together. In a proposal, an arrow shows the installed version followed by the proposed version. Keep means that service's configuration stays unchanged, not that its checks can be skipped.",
    ],
  },
  format: {
    title: "What is a data format?",
    paragraphs: [
      "A data format is the structure used to store a record. Format identifiers shown here come from the selected inventory or checked evidence. An identifier alone does not describe the structure or prove that a reader supports it.",
      "An older reader may not understand a newer format, even when its application starts normally. The saved-data checks run those readers against the actual stored bytes.",
    ],
  },
  coverage: {
    title: "How much saved data is covered?",
    paragraphs: [
      "Complete means the selected demo snapshot declares its list of saved records complete for the stores being modeled. Partial means some records may be absent from that list.",
      "Passing checks on the listed records cannot establish compatibility with unlisted records. A complete list can still have other missing facts, such as an unknown writer or format.",
    ],
  },
  BLOCKED: {
    title: "Why this rollback is unsafe",
    paragraphs: ["At least one required reader failed on a saved record it could encounter. Other passing reads, or a successful startup, do not cancel that failure. This candidate cannot be approved for simulation."],
  },
  NEEDS_EVIDENCE: {
    title: "Why this cannot be confirmed",
    paragraphs: ["No applicable read failure was established, but required information is missing or unresolved. For example, the inventory may be partial or a record's original writer may be unknown. This is not a pass, even if the observed reads succeeded."],
  },
  BOUNDED_PASS: {
    title: "What safe for saved data means",
    paragraphs: ["Every required check of a software reader against a saved record has a matching passing result, with no required evidence gaps. This establishes byte/shape readability only for the modeled records checked here. It does not establish production safety, application-level correctness, or other untested behavior. Human approval permits a local simulation only."],
  },
  mode: {
    title: "Live model or saved replay",
    paragraphs: ["Live asks the configured model to interpret the request and propose service versions. Replay reuses a recorded response. In both modes, confirming a proposal runs the actual reader checks. Live describes the model call, not the data source or a production connection. Check the source label and selected snapshot separately."],
  },
};

export function explainButton(actions, term) {
  const title = explanations[term]?.title || "Explain this term";
  return button(icon("info"), () => actions.openOverlay("explanation", term), {
    variant: "term-help", "aria-label": title, title,
  });
}

export function flagChip(actions, service, name, enabled) {
  return el("span", { class: "flag feature-setting" }, flagText(service, name, enabled),
    explainButton(actions, "flags"));
}

export function explanationContent(term) {
  const explanation = explanations[term];
  return { title: explanation?.title || "Explanation", body: el("div", { class: "explanation-copy" },
    (explanation?.paragraphs || ["No explanation is available for this term."]).map(text => el("p", {}, text))) };
}
