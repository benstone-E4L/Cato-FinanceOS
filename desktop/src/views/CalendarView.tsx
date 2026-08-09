/**
 * CalendarView — one of the master spec's §10 9-item nav slots.
 *
 * Per §10: "Today/next meetings, prep briefs (Phase E) — New (Calendar
 * read-only)." Calendar integration is a separate, out-of-scope Phase E
 * workstream. This view exists so the nav item is real and never
 * 404s/dead-ends, and states its own status honestly.
 */
import React from "react";

export const CalendarView: React.FC = () => (
  <div className="page-view">
    <div className="page-header"><h1 className="page-title">Calendar</h1></div>
    <div className="coming-soon-panel">
      <strong>Not yet available</strong>
      <p>
        This nav item is reserved for read-only calendar visibility (today/next meetings, prep
        briefs) — a Phase E build that doesn't exist in this repo yet. Nothing is faked here.
      </p>
    </div>
  </div>
);

export default CalendarView;
