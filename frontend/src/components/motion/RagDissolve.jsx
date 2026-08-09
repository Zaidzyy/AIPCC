import "./motion.css";

// RAG report generation: a document dissolves into a light stream that
// reassembles into a structured report panel. Loops.
export default function RagDissolve({ className = "" }) {
  return (
    <div className={`fm fm-rag ${className}`} role="img" aria-label="Report being generated from source data">
      <div className="doc"><span/><span/><span/><span/><span/></div>
      <div className="stream" />
      <div className="panel">
        <b style={{ "--h": "60%" }} />
        <b style={{ "--h": "85%" }} />
        <b style={{ "--h": "45%" }} />
        <b style={{ "--h": "70%" }} />
      </div>
    </div>
  );
}
