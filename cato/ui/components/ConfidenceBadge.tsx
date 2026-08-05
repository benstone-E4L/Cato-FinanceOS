/**
 * ConfidenceBadge.tsx — Displays a confidence score with color-coded badge.
 *
 * Color tiers (per spec):
 *   Green  (high)   ≥ 0.90
 *   Yellow (medium) 0.70 – 0.89
 *   Orange (low)    < 0.70
 */

import React from "react";

export type ConfidenceLevel = "high" | "medium" | "low";

export interface ConfidenceBadgeProps {
  /** Confidence score 0.0 – 1.0 */
  confidence: number;
  /** Optional: pre-computed level (overrides automatic calculation) */
  level?: ConfidenceLevel;
  /** Optional additional CSS class */
  className?: string;
}

/**
 * Compute the tier label from a raw confidence float.
 */
export function getConfidenceLevel(confidence: number): ConfidenceLevel {
  if (confidence >= 0.90) return "high";
  if (confidence >= 0.70) return "medium";
  return "low";
}

/**
 * Return Tailwind CSS class names for each tier.
 */
function tierClasses(level: ConfidenceLevel): string {
  switch (level) {
    case "high":
      return "bg-green-900/30 text-green-300 border border-green-900";
    case "medium":
      return "bg-yellow-900/30 text-yellow-300 border border-yellow-900";
    case "low":
      return "bg-orange-900/30 text-orange-300 border border-orange-800";
    default:
      return "bg-gray-900/30 text-gray-400 border border-gray-700";
  }
}

/**
 * Return a symbol character for the tier.
 */
function tierSymbol(level: ConfidenceLevel): string {
  switch (level) {
    case "high":   return "●";
    case "medium": return "◐";
    case "low":    return "○";
    default:       return "○";
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
      className={`confidence-badge ${computedLevel} inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-bold ${tierClasses(computedLevel)} ${className}`}
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
