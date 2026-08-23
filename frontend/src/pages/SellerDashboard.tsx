import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, ApiError } from "@/services/api";
import { StatusBadge } from "@/components/StatusBadge";
import type { AuctionListItem } from "@/types";

function toLocalInputValue(date: Date): string {
  const offset = date.getTimezoneOffset();
  const local = new Date(date.getTime() - offset * 60_000);
  return local.toISOString().slice(0, 16);
}

export function SellerDashboard() {
  const [auctions, setAuctions] = useState<AuctionListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [startingPrice, setStartingPrice] = useState("100");
  const [minIncrement, setMinIncrement] = useState("5");
  const [startTime, setStartTime] = useState(toLocalInputValue(new Date(Date.now() + 60_000)));
  const [endTime, setEndTime] = useState(toLocalInputValue(new Date(Date.now() + 3600_000)));

  const load = () => {
    setLoading(true);
    api
      .listAuctions({ mine: true })
      .then(setAuctions)
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  const onCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    setFormError(null);
    setSubmitting(true);
    try {
      await api.createAuction({
        title,
        description,
        starting_price: Number(startingPrice),
        min_increment: Number(minIncrement),
        start_time: new Date(startTime).toISOString(),
        end_time: new Date(endTime).toISOString(),
      });
      setTitle("");
      setDescription("");
      setShowForm(false);
      load();
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : "Failed to create auction");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h1>Seller Dashboard</h1>
        <button className="btn" onClick={() => setShowForm((s) => !s)}>
          {showForm ? "Cancel" : "+ New Auction"}
        </button>
      </div>

      {showForm && (
        <form onSubmit={onCreate} className="card" style={{ marginBottom: 24 }}>
          <div className="form-field">
            <label>Title</label>
            <input value={title} onChange={(e) => setTitle(e.target.value)} required />
          </div>
          <div className="form-field">
            <label>Description</label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={3}
            />
          </div>
          <div style={{ display: "flex", gap: 16 }}>
            <div className="form-field" style={{ flex: 1 }}>
              <label>Starting price (₹)</label>
              <input
                type="number"
                min={0.01}
                step="0.01"
                value={startingPrice}
                onChange={(e) => setStartingPrice(e.target.value)}
                required
              />
            </div>
            <div className="form-field" style={{ flex: 1 }}>
              <label>Minimum increment (₹)</label>
              <input
                type="number"
                min={0.01}
                step="0.01"
                value={minIncrement}
                onChange={(e) => setMinIncrement(e.target.value)}
                required
              />
            </div>
          </div>
          <div style={{ display: "flex", gap: 16 }}>
            <div className="form-field" style={{ flex: 1 }}>
              <label>Start time</label>
              <input
                type="datetime-local"
                value={startTime}
                onChange={(e) => setStartTime(e.target.value)}
                required
              />
            </div>
            <div className="form-field" style={{ flex: 1 }}>
              <label>End time</label>
              <input
                type="datetime-local"
                value={endTime}
                onChange={(e) => setEndTime(e.target.value)}
                required
              />
            </div>
          </div>
          {formError && <p className="error-text">{formError}</p>}
          <button className="btn" disabled={submitting}>
            {submitting ? "Creating..." : "Create auction"}
          </button>
        </form>
      )}

      {loading ? (
        <p>Loading...</p>
      ) : auctions.length === 0 ? (
        <p style={{ color: "var(--muted)" }}>You haven't created any auctions yet.</p>
      ) : (
        <div className="grid">
          {auctions.map((auction) => (
            <Link to={`/auctions/${auction.id}`} key={auction.id} className="card" style={{ color: "inherit" }}>
              <div style={{ display: "flex", justifyContent: "space-between" }}>
                <h3 style={{ margin: "0 0 8px" }}>{auction.title}</h3>
                <StatusBadge status={auction.status} />
              </div>
              <div className="price">₹{Number(auction.current_price).toLocaleString()}</div>
              <div style={{ fontSize: "0.8rem", color: "var(--muted)", marginTop: 6 }}>
                {auction.bid_count} bid{auction.bid_count === 1 ? "" : "s"}
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
