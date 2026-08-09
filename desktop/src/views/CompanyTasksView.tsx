/**
 * CompanyTasksView — one of the master spec's §10 9-item nav slots.
 *
 * Per §10: "Monday board read view + proposed-updates queue — New (Monday
 * API)." The Monday integration is a separate, out-of-scope workstream.
 * This view exists so the nav item is real and never 404s/dead-ends, and
 * states its own status honestly.
 */
import React from "react";

export const CompanyTasksView: React.FC = () => (
  <div className="page-view">
    <div className="page-header"><h1 className="page-title">Company Tasks</h1></div>
    <div className="coming-soon-panel">
      <strong>Not yet available</strong>
      <p>
        This nav item is reserved for a read-only Monday board view and a proposed-updates queue —
        a build that depends on the Monday API integration, which doesn't exist in this repo yet.
        Nothing is faked here.
      </p>
    </div>
  </div>
);

export default CompanyTasksView;
