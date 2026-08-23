export type UserRole = "buyer" | "seller" | "both";

export interface User {
  id: string;
  email: string;
  full_name: string;
  role: UserRole;
}

export interface AuthResponse {
  access_token: string;
  token_type: string;
  user: User;
}

export type AuctionStatus = "created" | "scheduled" | "active" | "ended" | "completed";

export interface Auction {
  id: string;
  seller_id: string;
  title: string;
  description: string;
  starting_price: number;
  current_price: number;
  min_increment: number;
  start_time: string;
  end_time: string;
  status: AuctionStatus;
  winner_id: string | null;
  created_at: string;
}

export interface AuctionListItem extends Auction {
  bid_count: number;
}

export interface Bid {
  id: string;
  auction_id: string;
  bidder_id: string;
  bidder_name: string | null;
  amount: number;
  created_at: string;
}

// --- WebSocket event payloads (must match notification_service.py) ---

export interface BidPlacedEvent {
  type: "bid_placed";
  payload: {
    auction_id: string;
    current_price: number;
    bid: {
      id: string;
      amount: number;
      bidder_name: string;
      created_at: string;
    };
  };
}

export interface AuctionActiveEvent {
  type: "auction_active";
  payload: { auction_id: string; status: AuctionStatus };
}

export interface AuctionCompletedEvent {
  type: "auction_completed";
  payload: {
    auction_id: string;
    status: AuctionStatus;
    winner_id: string | null;
    winner_name: string | null;
    final_price: number;
  };
}

export interface ErrorEvent {
  type: "error";
  payload: { detail: string };
}

export type AuctionSocketEvent =
  | BidPlacedEvent
  | AuctionActiveEvent
  | AuctionCompletedEvent
  | ErrorEvent;
