#!/usr/bin/env python3
"""测试 LLM API 的 RPM 限制：并发发送 n 个短推理请求，统计成功/失败情况。

用法：
    python scripts/test_api_rpm.py --url https://api.example.com --token sk-xxx --n 20
    python scripts/test_api_rpm.py --url https://api.example.com --token sk-xxx --n 20 --model gpt-4o
"""
from __future__ import annotations

import argparse
import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class RequestResult:
    index: int
    success: bool
    status_code: Optional[int] = None
    latency: float = 0.0
    error: str = ""


async def send_one(
    session,
    index: int,
    url: str,
    token: str,
    model: str,
    print_lock: asyncio.Lock = None,
) -> RequestResult:
    import aiohttp

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "1+1=?"}],
        "max_tokens": 16,
    }
    start = time.monotonic()
    result: RequestResult
    try:
        async with session.post(
            f"{url.rstrip('/')}/chat/completions",
            headers=headers,
            json=payload,
            timeout=aiohttp.ClientTimeout(total=30),
        ) as resp:
            latency = time.monotonic() - start
            body = await resp.text()
            if resp.status == 200:
                result = RequestResult(index=index, success=True, status_code=200, latency=latency)
            else:
                try:
                    err_msg = json.loads(body).get("error", {})
                    if isinstance(err_msg, dict):
                        err_msg = err_msg.get("message", body[:200])
                except Exception:
                    err_msg = body[:200]
                result = RequestResult(
                    index=index,
                    success=False,
                    status_code=resp.status,
                    latency=latency,
                    error=str(err_msg),
                )
    except Exception as e:
        latency = time.monotonic() - start
        result = RequestResult(index=index, success=False, latency=latency, error=str(e))

    async with print_lock:
        if result.success:
            print(f"  [#{index:>3}] ✓  {result.latency:.2f}s")
        else:
            status = f"HTTP {result.status_code}" if result.status_code else "ERR"
            print(f"  [#{index:>3}] ✗  {status}  {result.error[:80]}")

    return result


async def run(url: str, token: str, model: str, n: int, ssl_verify: bool = True) -> None:
    try:
        import aiohttp
    except ImportError:
        print("缺少依赖，请先安装：pip install aiohttp")
        return

    print(f"并发发送 {n} 个请求 → {url}  model={model}")
    if not ssl_verify:
        print("⚠️  SSL 验证已禁用")
    print("-" * 60)

    connector = aiohttp.TCPConnector(ssl=False) if not ssl_verify else None
    print_lock = asyncio.Lock()
    start_all = time.monotonic()
    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = [send_one(session, i, url, token, model, print_lock) for i in range(n)]
        results = await asyncio.gather(*tasks)
    elapsed = time.monotonic() - start_all
    print("-" * 60)

    succeeded = [r for r in results if r.success]
    failed = [r for r in results if not r.success]

    # 按状态码分组失败原因
    fail_groups: dict[str, list[RequestResult]] = {}
    for r in failed:
        key = f"HTTP {r.status_code}" if r.status_code else "连接错误"
        fail_groups.setdefault(key, []).append(r)

    print(f"总请求数：{n}")
    print(f"成功：{len(succeeded)}  失败：{len(failed)}")
    print(f"总耗时：{elapsed:.2f}s")

    if succeeded:
        lats = [r.latency for r in succeeded]
        print(f"成功请求延迟：min={min(lats):.2f}s  max={max(lats):.2f}s  avg={sum(lats)/len(lats):.2f}s")

    if fail_groups:
        print("\n失败明细：")
        for status, group in fail_groups.items():
            print(f"  [{status}] × {len(group)}")
            sample = group[0].error
            if sample:
                print(f"    示例错误：{sample[:200]}")


def main() -> None:
    parser = argparse.ArgumentParser(description="测试 LLM API RPM 限制")
    parser.add_argument("--url",   required=True, help="API 基础地址，例如 https://api.openai.com")
    parser.add_argument("--token", required=True, help="API Token / Key")
    parser.add_argument("--n",     type=int, default=20, help="并发请求数量（默认 20）")
    parser.add_argument("--model", default="gpt-4o-mini", help="模型名称（默认 gpt-4o-mini）")
    parser.add_argument("--no-ssl", action="store_true", help="跳过 SSL 证书验证")
    args = parser.parse_args()

    asyncio.run(run(args.url, args.token, args.model, args.n, ssl_verify=not args.no_ssl))


if __name__ == "__main__":
    main()
