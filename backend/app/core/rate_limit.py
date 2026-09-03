import time
from fastapi import HTTPException, status, Request
from app.websocket.manager import get_redis

async def rate_limit(request: Request):
    """
    Sliding window rate limiter using Redis.
    Limits to 5 requests per second per IP address.
    """
    redis = get_redis()
    client_ip = request.client.host if request.client else "unknown"
    # Scope to the specific route
    route_path = request.url.path
    key = f"rate_limit:{client_ip}:{route_path}"
    
    current_time = time.time()
    window_start = current_time - 1.0 # 1 second window
    
    # Redis transaction (pipeline)
    pipe = redis.pipeline()
    # Remove old requests
    pipe.zremrangebyscore(key, 0, window_start)
    # Count current requests in the window
    pipe.zcard(key)
    # Add new request
    pipe.zadd(key, {str(current_time): current_time})
    # Set expiration so we don't leak memory
    pipe.expire(key, 2)
    
    results = await pipe.execute()
    request_count = results[1]
    
    if request_count >= 5:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests. Please slow down."
        )
