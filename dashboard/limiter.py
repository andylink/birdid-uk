"""
Shared slowapi rate limiter instance.

Import this module in both app.py (to wire the middleware) and any route
module that needs to apply a rate limit decorator.  Using a single shared
instance ensures all decorators share the same in-process counter store.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

# Key function: rate-limit by the client's IP address.
# Behind a trusted reverse proxy, set the X-Forwarded-For header and use
# get_remote_address (slowapi reads it automatically when present).
limiter = Limiter(key_func=get_remote_address)
