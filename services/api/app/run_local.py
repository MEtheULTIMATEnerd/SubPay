"""Loopback-only launcher: python -m app.run_local."""

import uvicorn

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, proxy_headers=False)
