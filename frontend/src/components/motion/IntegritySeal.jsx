import "./motion.css";

// File integrity (FIM): a lock draws itself from fragments, a check turns
// green and a ring pulses out — "SEALED". Loops.
export default function IntegritySeal({ className = "" }) {
  return (
    <div className={`fm fm-seal ${className}`} role="img" aria-label="File integrity verified and sealed">
      <svg viewBox="0 0 100 100" width="96" height="96">
        <circle className="ring" cx="50" cy="50" r="34" />
        <rect className="body" x="34" y="46" width="32" height="26" rx="4" />
        <path className="shackle" d="M40 46 v-6 a10 10 0 0 1 20 0 v6" />
        <path className="check" d="M43 59 l5 5 l9 -10" />
      </svg>
    </div>
  );
}
