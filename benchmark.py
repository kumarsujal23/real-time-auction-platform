import asyncio
import time
import httpx
import uuid

# Run the API first!
# uvicorn backend.app.main:app --reload
API_BASE = "http://localhost:8000"

async def benchmark_bidding(num_users=10, bids_per_user=50):
    async with httpx.AsyncClient(base_url=API_BASE) as client:
        # 1. Register users and get tokens
        tokens = []
        for i in range(num_users):
            username = f"benchuser_{uuid.uuid4().hex[:8]}@example.com"
            res = await client.post("/api/auth/register", json={
                "email": username,
                "full_name": f"Bench User {i}",
                "password": "password123",
                "role": "buyer"
            })
            if res.status_code != 201:
                print("Failed to register:", res.json())
                return
                
            tokens.append(res.json()["access_token"])
            
        print(f"Registered {num_users} users.")

        # 2. Register a seller and create an auction
        res = await client.post("/api/auth/register", json={
            "email": f"seller_{uuid.uuid4().hex[:8]}@example.com",
            "full_name": "Bench Seller",
            "password": "password123",
            "role": "seller"
        })
        seller_token = res.json()["access_token"]
        
        # start time in the past to make it ACTIVE
        from datetime import datetime, timezone, timedelta
        now = datetime.now(timezone.utc)
        start = now - timedelta(hours=1)
        end = now + timedelta(hours=1)
        
        res = await client.post("/api/auctions", json={
            "title": "Benchmark Auction",
            "description": "Load test",
            "starting_price": 10.0,
            "min_increment": 1.0,
            "start_time": start.isoformat(),
            "end_time": end.isoformat()
        }, headers={"Authorization": f"Bearer {seller_token}"})
        
        auction_id = res.json()["id"]
        print(f"Created auction {auction_id}")
        
        # 3. Hammer the API with bids concurrently
        print(f"Starting benchmark: {num_users} users placing {bids_per_user} bids each...")
        
        async def user_bidding_loop(token):
            successes = 0
            failures = 0
            for _ in range(bids_per_user):
                # We don't care about getting rejected for "Bid too low", we just care about TPS and DB locks
                res = await client.post(
                    f"/api/auctions/{auction_id}/bids", 
                    json={
                        "amount": 1000.0, # Just trying to brute force a high amount
                        "idempotency_key": uuid.uuid4().hex
                    }, 
                    headers={"Authorization": f"Bearer {token}"}
                )
                if res.status_code in [201, 422]: # 422 is Bid Too Low (race condition handled properly)
                    successes += 1
                else:
                    failures += 1
            return successes, failures

        start_time = time.time()
        results = await asyncio.gather(*[user_bidding_loop(t) for t in tokens])
        end_time = time.time()
        
        total_time = end_time - start_time
        total_requests = num_users * bids_per_user
        
        print("\n=== BENCHMARK RESULTS ===")
        print(f"Total Requests: {total_requests}")
        print(f"Time Taken: {total_time:.2f} seconds")
        print(f"Throughput: {(total_requests / total_time):.2f} req/sec")
        print("=========================")

if __name__ == "__main__":
    asyncio.run(benchmark_bidding(num_users=20, bids_per_user=50))
