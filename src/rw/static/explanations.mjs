import { el, icon, button } from "./dom.mjs";

// Explain the authored shop fixture without inferring missing metadata or compatibility.
export const formatText = format => ({
  "cart/v1": "Single-list cart · cart/v1",
  "cart/v2": "Basket cart · cart/v2",
  UNKNOWN: "Unknown format",
})[format] || format || "Unknown format";

export const flagText = (service, name, enabled) =>
  `${service === "cart" && name === "basket_v2" ? "Basket feature" : name}: ${enabled ? "On" : "Off"}`;

const explanations = {
  basket: {
    title: "Basket feature: an on/off setting",
    paragraphs: [
      "A feature flag switches a feature on or off without changing the installed software version. Here, basket_v2 controls whether Cart groups items into named baskets.",
      "In Cart 1.5, On saves new carts in the basket format (cart/v2). Off restores the single-list format (cart/v1) for new saves. Existing saved carts are not converted or deleted.",
      "The Cart 1.5 reader accepts both formats. Keeping it with the feature Off can preserve access to existing carts; the actual reader checks still have to pass.",
    ],
  },
  flags: {
    title: "Feature settings",
    paragraphs: ["Feature flags are on/off settings within a software version. They let a proposal change selected behavior without installing an older build. Their effect comes from the release's source evidence; changing a flag does not itself prove compatibility with saved data."],
  },
  versions: {
    title: "Services and software versions",
    paragraphs: [
      "Cart and Checkout are separate parts of this demo shop. Cart saves shopping carts; Checkout reads them for pricing and produces receipts. Numbers such as 1.5 and 2.1 identify their software versions.",
      "A fleet is the set of service versions and settings used together. In a proposal, an arrow shows the installed version followed by the proposed version. Keep means that service's configuration stays unchanged, not that its checks can be skipped.",
    ],
  },
  format: {
    title: "What is a data format?",
    paragraphs: [
      "A data format is the structure used to store a saved cart. cart/v1 stores a single list of items. cart/v2 adds named baskets. A reader is the code in a software version that opens that stored structure.",
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
    title: "Why this proposal is blocked",
    paragraphs: ["At least one required reader failed on a saved record it could encounter. Other passing reads, or a successful startup, do not cancel that failure. This candidate cannot be approved for simulation."],
  },
  NEEDS_EVIDENCE: {
    title: "Why more evidence is needed",
    paragraphs: ["No applicable read failure was established, but required information is missing or unresolved. For example, the inventory may be partial or a record's original writer may be unknown. This is not a pass, even if the observed reads succeeded."],
  },
  BOUNDED_PASS: {
    title: "What a bounded pass means",
    paragraphs: ["Every required check of a software reader against a saved record has a matching passing result, with no required evidence gaps. This establishes readability of the checked records only. It does not establish production safety, correct receipt totals, or other untested behavior. Human approval permits a local simulation only."],
  },
  mode: {
    title: "Live model or saved replay",
    paragraphs: ["Live asks the configured model to interpret the request and propose service versions. Replay reuses a recorded response. In both modes, confirming a proposal runs the actual reader checks. Live does not mean a connection to production: this interface uses generated demo data."],
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
    explainButton(actions, service === "cart" && name === "basket_v2" ? "basket" : "flags"));
}

export function explanationContent(term) {
  const explanation = explanations[term];
  return { title: explanation?.title || "Explanation", body: el("div", { class: "explanation-copy" },
    (explanation?.paragraphs || ["No explanation is available for this term."]).map(text => el("p", {}, text))) };
}
