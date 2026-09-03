import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { v4 as uuidv4 } from "@/lib/uuid";
import { api, ApiError } from "@/services/api";
import { useAuctionSocket } from "@/hooks/useAuctionSocket";
import { useCountdown } from "@/hooks/useCountdown";
import { useAuth } from "@/context/AuthContext";
import { StatusBadge } from "@/components/StatusBadge";
import type { Auction, Bid } from "@/types";

export function AuctionDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { user } = useAuth();

  const [auction, setAuction] = useState<Auction | null>(null);
  const [bids, setBids] = useState<Bid[]>([]);
  const [bidAmount, setBidAmount] = useState<string>("");
  const [placing, setPlacing] = useState(false);
  const [bidError, setBidError] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [winnerBanner, setWinnerBanner] = useState<string | null>(null);

  const { lastEvent, connected } = useAuctionSocket(id);
  const countdown = useCountdown(auction?.end_time);

  const loadAuction = useCallback(async () => {
    if (!id) return;
    try {
      const [auctionData, bidData] = await Promise.all([api.getAuction(id), api.getBidHistory(id)]);
      setAuction(auctionData);
      setBids(bidData);
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : "Failed to load auction");
    }
  }, [id]);

  useEffect(() => {
    loadAuction();
  }, [loadAuction]);

  // React to live events pushed over the WebSocket - this is what makes
  // the price/bid-feed update for every connected viewer without a
  // page refresh or polling.
  useEffect(() => {
    if (!lastEvent || !auction) return;

    if (lastEvent.type === "bid_placed" && lastEvent.payload.auction_id === auction.id) {
      const { current_price, end_time, bid } = lastEvent.payload;
      setAuction((prev) => {
        if (!prev) return prev;
        return {
          ...prev,
          current_price,
          ...(end_time && { end_time }),
        };
      });
      setBids((prev) => {
        const cleanBids = prev.filter(b => !b.id.startsWith("temp-"));
        // avoid duplicates if api request and ws event race
        if (cleanBids.some(b => b.id === bid.id)) return cleanBids;
        return [
          {
            id: bid.id,
            auction_id: auction.id,
            bidder_id: "",
            bidder_name: bid.bidder_name,
            amount: bid.amount,
            created_at: bid.created_at,
          },
          ...cleanBids,
        ];
      });
    }

    if (lastEvent.type === "auction_completed" && lastEvent.payload.auction_id === auction.id) {
      setAuction((prev) => (prev ? { ...prev, status: lastEvent.payload.status as Auction["status"] } : prev));
      setWinnerBanner(
        lastEvent.payload.winner_name
          ? `Auction ended - won by ${lastEvent.payload.winner_name} at ₹${lastEvent.payload.final_price}`
          : "Auction ended with no bids."
      );
    }

    if (lastEvent.type === "auction_active" && lastEvent.payload.auction_id === auction.id) {
      setAuction((prev) => (prev ? { ...prev, status: "active" } : prev));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lastEvent]);

  const minNextBid = useMemo(() => {
    if (!auction) return 0;
    return Number(auction.current_price) + Number(auction.min_increment);
  }, [auction]);

  const canBid =
    !!user && !!auction && auction.status === "active" && auction.seller_id !== user.id;

  const submitBid = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!id || !user || !auction) return;
    setBidError(null);
    const amount = Number(bidAmount);
    if (!Number.isFinite(amount) || amount < minNextBid) {
      setBidError(`Bid must be at least ₹${minNextBid}`);
      return;
    }
    setPlacing(true);
    
    // Optimistic UI Update
    const prevAuction = { ...auction };
    const prevBids = [...bids];
    setAuction({ ...auction, current_price: amount });
    setBids([
      {
        id: `temp-${uuidv4()}`,
        auction_id: auction.id,
        bidder_id: user.id,
        bidder_name: user.full_name + " (Pending)",
        amount: amount,
        created_at: new Date().toISOString(),
      },
      ...bids,
    ]);

    try {
      await api.placeBid(id, amount, uuidv4());
      setBidAmount("");
    } catch (err) {
      setBidError(err instanceof ApiError ? err.message : "Failed to place bid");
      setAuction(prevAuction);
      setBids(prevBids);
    } finally {
      setPlacing(false);
    }
  };

  if (loadError) return <p className="error-text">{loadError}</p>;
  if (!auction) return <p>Loading...</p>;

  return (
    <div className="detail-layout">
      <div className="card detail-card">
        <div className="detail-head">
          <div><div className="eyebrow">Auction detail</div><h1>{auction.title}</h1></div>
          <StatusBadge status={auction.status} />
        </div>
        <p className="detail-description">{auction.description || "No description provided."}</p>

        <div className="price-panel">
          <div className="price-label">Current price</div>
          <div className="price">₹{Number(auction.current_price).toLocaleString()}</div>
        </div>

        <div className="detail-stats">
          <div className="detail-stat"><span className="detail-stat-label">Time remaining</span><span className="detail-stat-value">{countdown}</span></div>
          <div className="detail-stat"><span className="detail-stat-label">Minimum raise</span><span className="detail-stat-value">₹{Number(auction.min_increment).toLocaleString()}</span></div>
          <div className="detail-stat"><span className="detail-stat-label">Live connection</span><span className="detail-stat-value">
              <span className={`live-dot ${connected ? "on" : "off"}`} />
              {connected ? "Connected" : "Reconnecting..."}
            </span></div>
        </div>

        {winnerBanner && (
          <div className="winner-banner">{winnerBanner}</div>
        )}

        {canBid ? (
          <form onSubmit={submitBid} className="bid-panel">
            <h2>Make your move</h2>
            <p className="muted-on-dark">Enter a bid higher than the current price to join the auction.</p>
            <div className="form-field">
              <label>Your bid - minimum ₹{minNextBid.toLocaleString()}</label>
              <input
                type="number"
                step="0.01"
                min={minNextBid}
                value={bidAmount}
                onChange={(e) => setBidAmount(e.target.value)}
                placeholder={String(minNextBid)}
                required
              />
            </div>
            {bidError && <p className="error-text">{bidError}</p>}
            <button className="btn" disabled={placing}>
              {placing ? "Placing bid..." : "Place bid"}
            </button>
          </form>
        ) : (
          <p className="detail-description">
            {!user
              ? "Log in to place a bid."
              : auction.seller_id === user.id
              ? "You are the seller of this auction."
              : "This auction is not currently accepting bids."}
          </p>
        )}
      </div>

      <div className="card bids-card">
        <h2>Live bids</h2>
        <p style={{ color: "var(--muted)", fontSize: ".86rem" }}>Every bid is shown here as it happens.</p>
        {bids.length === 0 && <p style={{ color: "var(--muted)" }}>No bids yet.</p>}
        {bids.map((bid) => (
          <div key={bid.id} className="bid-row" style={{ opacity: bid.id.startsWith("temp-") ? 0.6 : 1 }}>
            <span>{bid.bidder_name ?? "Anonymous"}</span>
            <span>₹{Number(bid.amount).toLocaleString()}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
