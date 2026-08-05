/**
 * ConfidenceBadge.tsx — Displays a confidence score with color-coded badge.
 *
 * Color tiers (per spec):
 *   Blue   (high)   >= 0.90
 *   Yellow (medium) 0.70 - 0.89
 *   Orange (low)    < 0.70
 */

import React from "react";

export type ConfidenceLevel = "high" | "medium" | "low";

export interface ConfidenceBadgeProps {
  confidence: number;
  level?: ConfidenceLevel;
  className?: string;
}

// eslint-disable-next-line react-refresh/only-export-components
export function getConfidenceLevel(confidence: number): ConfidenceLevel {
  if (confidence >= 0.90) return "high";
  if (confidence >= 0.70) return "medium";
  return "low";
}

function tierSymbol(level: ConfidenceLevel): string {
  switch (level) {
    case "high":   return "\u25CF";
    case "medium": return "\u25D0";
    case "low":    return "\u25CB";
  }
}

export const ConfidenceBadge: React.FC<ConfidenceBadgeProps> = ({
  confidence,
  level,
  className = "",
}) => {
  const computedLevel = level ?? getConfidenceLevel(confidence);
  const pct = Math.round(confidence * 100);

  return (
    <span
      className={`confidence-badge ${computedLevel} ${className}`}
      title={`Confidence: ${pct}%`}
      aria-label={`Confidence ${pct}% (${computedLevel})`}
      data-testid="confidence-badge"
      data-level={computedLevel}
    >
      <span aria-hidden="true">{tierSymbol(computedLevel)}</span>
      {pct}%
    </span>
  );
};

export default ConfidenceBadge;
