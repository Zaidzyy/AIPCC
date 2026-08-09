import "./motion.css";

// Talk-to-your-data chat: a soft cyan equalizer waveform. Loops.
export default function ChatWaveform({ className = "", bars = 22 }) {
  return (
    <div className={`fm fm-wave ${className}`} role="img" aria-label="Chat assistant listening">
      <div className="bars">
        {Array.from({ length: bars }, (_, i) => (
          <i key={i} style={{ animationDelay: `${i * 0.06}s`, height: `${20 + ((i * 37) % 40)}%` }} />
        ))}
      </div>
    </div>
  );
}
