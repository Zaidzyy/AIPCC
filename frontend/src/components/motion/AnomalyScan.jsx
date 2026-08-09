import "./motion.css";

// Anomaly detection: a field of calm dots swept by a scan line; a few flare
// amber then red and settle. Loops.
const HOT = new Set([10, 13, 22, 31, 40, 49]);

export default function AnomalyScan({ className = "", count = 54 }) {
  return (
    <div className={`fm fm-anom ${className}`} role="img" aria-label="Scanning for anomalies; a few points flag as suspicious">
      <div className="grid">
        {Array.from({ length: count }, (_, i) => (
          <span
            key={i}
            className={`dot${HOT.has(i) ? " hot" : ""}`}
            style={HOT.has(i) ? { animationDelay: `${[...HOT].indexOf(i) * 0.15}s` } : undefined}
          />
        ))}
      </div>
      <div className="scan" />
    </div>
  );
}
