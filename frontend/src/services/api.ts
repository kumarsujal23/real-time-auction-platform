import type { Auction, AuctionListItem, AuthResponse, Bid, UserRole } from "@/types";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

function getToken(): string | null {
  return localStorage.getItem("auction_token");
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string> | undefined),
  };
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }

  const res = await fetch(`${API_BASE_URL}${path}`, { ...options, headers });

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch {
      // response had no JSON body
    }
    throw new ApiError(res.status, detail);
  }

  if (res.status === 204) {
    return undefined as T;
  }
  return res.json() as Promise<T>;
}

export const api = {
  async register(email: string, password: string, fullName: string, role: UserRole) {
    return request<AuthResponse>("/api/auth/register", {
      method: "POST",
      body: JSON.stringify({ email, password, full_name: fullName, role }),
    });
  },

  async login(email: string, password: string) {
    return request<AuthResponse>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    });
  },

  async me() {
    return request<AuthResponse["user"]>("/api/users/me");
  },

  async getServerTime() {
    return request<{ server_time_ms: number }>("/api/auctions/time");
  },

  async listAuctions(params: { status?: string; mine?: boolean } = {}) {
    const query = new URLSearchParams();
    if (params.status) query.set("status", params.status);
    if (params.mine) query.set("mine", "true");
    const qs = query.toString();
    return request<AuctionListItem[]>(`/api/auctions${qs ? `?${qs}` : ""}`);
  },

  async getAuction(id: string) {
    return request<Auction>(`/api/auctions/${id}`);
  },

  async getBidHistory(id: string) {
    return request<Bid[]>(`/api/auctions/${id}/bids`);
  },

  async createAuction(payload: {
    title: string;
    description: string;
    starting_price: number;
    min_increment: number;
    start_time: string;
    end_time: string;
  }) {
    return request<Auction>("/api/auctions", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  async placeBid(auctionId: string, amount: number, idempotencyKey: string) {
    return request<Bid>(`/api/auctions/${auctionId}/bids`, {
      method: "POST",
      body: JSON.stringify({ amount, idempotency_key: idempotencyKey }),
    });
  },
};

export function wsUrlForAuction(auctionId: string): string {
  const base = import.meta.env.VITE_WS_BASE_URL ?? "ws://localhost:8000";
  return `${base}/api/auctions/${auctionId}/ws`;
}

export { getToken };
