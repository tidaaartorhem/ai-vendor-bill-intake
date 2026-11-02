import { useEffect, useState } from "react";
import { loadIntakeData, type IntakeData } from "./data";
import QueueView from "./views/QueueView";
import VendorsView from "./views/VendorsView";
import FindingsView from "./views/FindingsView";
import PasteView from "./views/PasteView";
import MethodView from "./views/MethodView";
import { fmtMoney } from "./views/shared";
import "./styles.css";

type Tab = "queue" | "vendors" | "findings" | "paste" | "method";

const TABS: Array<[Tab, string]> = [
  ["queue", "Intake Queue"],
  ["vendors", "Vendors"],
  ["findings", "Findings"],
  ["paste", "Paste a bill"],
  ["method", "Methodology"],
];

export default function App() {
  const [tab, setTab] = useState<Tab>("queue");
  const [data, setData] = useState<IntakeData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    loadIntakeData().then(setData).catch((e) => setError(String(e)));
  }, []);

  if (error) {
    return (
      <div className="wrap">
        <p className="note">Could not load intake data: {error}</p>
      </div>
    );
  }
  if (!data) {
    return (
      <div className="wrap">
        <p className="muted">Loading the intake desk…</p>
      </div>
    );
  }

  const held = data.bills.filter((b) =>
    ["HOLD_DUPLICATE", "REQUEST_PO", "CORRECT_TOTAL"].includes(b.action)
  ).length;
  const autoPost = data.bills.filter((b) => b.action === "AUTO_POST").length;
  const totalValue = data.bills.reduce((s, b) => s + b.total_cad, 0);

  return (
    <div className="wrap">
      <header className="hero">
        <h1>InTray</h1>
        <p className="sub">
          the vendor bill intake desk — Portside Supply Co., Toronto
        </p>
        <div className="chips">
          <span className="chip">
            <strong>{data.bills.length}</strong> bills
          </span>
          <span className="chip">
            <strong>{fmtMoney(totalValue, 0)}</strong> in queue
          </span>
          <span className="chip">
            <strong>{autoPost}</strong> auto-intake
          </span>
          <span className="chip">
            <strong>{held}</strong> held for review
          </span>
          <span className="chip">
            <strong>{data.splitClusters.length}</strong> split-dodge cluster
            {data.splitClusters.length === 1 ? "" : "s"}
          </span>
        </div>
      </header>

      <nav className="tabs">
        {TABS.map(([id, label]) => (
          <button
            key={id}
            className={tab === id ? "active" : ""}
            onClick={() => setTab(id)}
          >
            {label}
          </button>
        ))}
      </nav>

      <main>
        {tab === "queue" && <QueueView data={data} />}
        {tab === "vendors" && <VendorsView data={data} />}
        {tab === "findings" && <FindingsView data={data} />}
        {tab === "paste" && <PasteView data={data} />}
        {tab === "method" && <MethodView data={data} />}
      </main>

      <footer className="foot">
        <span className="muted">
          Deterministic rules — no model calls. Replay date Mon 2026-11-02
          08:41 EST.
        </span>
      </footer>
    </div>
  );
}
