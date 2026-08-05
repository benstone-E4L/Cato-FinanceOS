/**
 * PlaceholderView — Stub page for views not yet built out.
 */
import React from "react";

interface PlaceholderViewProps {
  name: string;
  description?: string;
}

export const PlaceholderView: React.FC<PlaceholderViewProps> = ({ name, description }) => {
  return (
    <div className="placeholder-view">
      <div className="placeholder-icon">{name.charAt(0).toUpperCase()}</div>
      <h2 className="placeholder-title">{name}</h2>
      <p className="placeholder-desc">
        {description ?? "This page is coming in the next build iteration."}
      </p>
    </div>
  );
};

export default PlaceholderView;
