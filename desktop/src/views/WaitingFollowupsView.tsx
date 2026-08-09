/**
 * WaitingFollowupsView — one of the master spec's §10 9-item nav slots.
 *
 * Per §10: "Timers, owners, ages, overdue first — New (Coordination Ledger +
 * Trigger.dev waitpoints)." The Coordination Ledger is a separate,
 * out-of-scope Phase E/F workstream (this workspace's guardrails.md: "DO NOT
 * BUILD: cross-system correlated-card logic... that's Phase F's E4L
 * Coordination Ledger work"). This view exists so the nav item is real and
 * never 404s/dead-ends, and states its own status honestly rather than
 * fabricating waiting-item data that no backend produces yet.
 */
import React from "react";

export const WaitingFollowupsView: React.FC = () => (
  <div className="page-view">
    <div className="page-header"><h1 className="page-title">Waiting / Follow-ups</h1></div>
    <div className="coming-soon-panel">
      <strong>Not yet available</strong>
      <p>
        This nav item is reserved for timers, owners, and overdue follow-ups sourced from the
        Coordination Ledger and Trigger.dev waitpoints — a separate, later-phase build (Phase E/F)
        that doesn't exist in this repo yet. Nothing is faked here; there is genuinely no waiting
        item to show until that backend is built.
      </p>
    </div>
  </div>
);

export default WaitingFollowupsView;
