#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mcp_client.py — 麦当劳 MCP Server (Streamable HTTP) 的零依赖客户端。

只用 Python 标准库实现，不需要 pip install 任何东西。
支持：initialize / tools/list / tools/call，自动处理 SSE 响应与 mcp-session-id。

用法：
    export MCD_MCP_TOKEN=xxxxx

    # 列出所有工具
    python3 scripts/mcp_client.py list-tools

    # 调用某个工具（--args 传 JSON 字符串，或从文件读）
    python3 scripts/mcp_client.py call now-time-info
    python3 scripts/mcp_client.py call query-my-coupons --args '{}'
    python3 scripts/mcp_client.py call calculate-price --args @payload.json

    # 打开原始调试输出
    python3 scripts/mcp_client.py list-tools --debug
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any

ENDPOINT = os.environ.get("MCD_MCP_ENDPOINT", "https://mcp.mcd.cn")
PROTOCOL_VERSION = "2025-06-18"
DEFAULT_TIMEOUT = 30


class McpError(RuntimeError):
    """MCP 服务端返回的错误，或协议层面的错误。"""

    def __init__(self, message: str, code: int | None = None, data: Any = None):
        super().__init__(message)
        self.code = code
        self.data = data


class McpClient:
    """Streamable HTTP 上的最小 MCP 客户端。"""

    def __init__(self, token: str, endpoint: str = ENDPOINT, debug: bool = False):
        if not token:
            raise McpError(
                "缺少 MCP Token。请先到 https://open.mcd.cn/mcp 申请，"
                "然后 export MCD_MCP_TOKEN=你的token"
            )
        self.token = token
        self.endpoint = endpoint
        self.debug = debug
        self.session_id: str | None = None
        self._id = 0

    # ---------- 底层传输 ----------

    def _next_id(self) -> int:
        self._id += 1
        return self._id

    def _headers(self) -> dict[str, str]:
        h = {
            "Content-Type": "application/json",
            # 同时接受普通 JSON 与 SSE 流式响应，两种都合法
            "Accept": "application/json, text/event-stream",
            "Authorization": f"Bearer {self.token}",
            "User-Agent": "mcd-value-engine/1.0",
        }
        if self.session_id:
            h["Mcp-Session-Id"] = self.session_id
        return h

    def _post(self, payload: dict | list) -> dict | None:
        """发起一次 POST，返回解析后的 JSON-RPC 响应；通知类请求返回 None。"""
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            self.endpoint, data=body, headers=self._headers(), method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=DEFAULT_TIMEOUT) as resp:
                new_session = resp.headers.get("Mcp-Session-Id")
                if new_session:
                    self.session_id = new_session
                raw = resp.read().decode("utf-8", errors="replace")
                ctype = (resp.headers.get("Content-Type") or "").lower()
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", errors="replace")
            if e.code == 401:
                raise McpError(
                    "401：Token 无效、已过期或未提供。到 https://open.mcd.cn/mcp 重新获取。",
                    code=e.code,
                )
            if e.code == 429:
                raise McpError(
                    "429：触发限流（每 Token 600 次/分钟）。降低调用频率后重试。",
                    code=e.code,
                )
            raise McpError(f"HTTP {e.code}：{raw[:500]}", code=e.code)
        except urllib.error.URLError as e:
            raise McpError(f"网络错误：{e.reason}")

        if self.debug:
            print(f"[debug] <- {raw[:2000]}", file=sys.stderr)

        if not raw.strip():
            return None
        if "text/event-stream" in ctype or raw.lstrip().startswith("event:") or raw.lstrip().startswith("data:"):
            return self._parse_sse(raw)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return self._parse_sse(raw)

    @staticmethod
    def _parse_sse(raw: str) -> dict | None:
        """从 SSE 流里抽出最后一个 data: 块作为 JSON-RPC 响应。"""
        last: dict | None = None
        for line in raw.splitlines():
            line = line.strip()
            if not line.startswith("data:"):
                continue
            chunk = line[len("data:"):].strip()
            if not chunk:
                continue
            try:
                last = json.loads(chunk)
            except json.JSONDecodeError:
                continue
        return last

    def _request(self, method: str, params: dict | None = None) -> dict:
        msg: dict[str, Any] = {"jsonrpc": "2.0", "id": self._next_id(), "method": method}
        if params is not None:
            msg["params"] = params
        resp = self._post(msg)
        if resp is None:
            raise McpError(f"{method} 没有收到响应")
        if "error" in resp:
            err = resp["error"]
            raise McpError(
                f"{method} 失败 [{err.get('code')}]：{err.get('message')}",
                code=err.get("code"),
                data=err.get("data"),
            )
        return resp.get("result", {})

    def _notify(self, method: str, params: dict | None = None) -> None:
        msg: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        try:
            self._post(msg)
        except McpError:
            # initialized 通知通常返回 202 空体，失败不影响后续调用
            pass

    # ---------- 对外 API ----------

    def initialize(self) -> dict:
        result = self._request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "mcd-value-engine", "version": "1.0.0"},
            },
        )
        self._notify("notifications/initialized")
        return result

    def list_tools(self) -> list[dict]:
        self.initialize()
        result = self._request("tools/list")
        return result.get("tools", [])

    def call_tool(self, name: str, arguments: dict | None = None) -> Any:
        """
        调用工具。返回结构化结果：
        - 若工具返回结构化 JSON（structuredContent），原样返回 dict
        - 否则把 content 里的 text 尝试解析成 JSON，解析不了就返回原始文本
        """
        self.initialize()
        result = self._request("tools/call", {"name": name, "arguments": arguments or {}})
        if result.get("structuredContent"):
            return result["structuredContent"]
        if result.get("isError"):
            raise McpError(f"工具 {name} 返回错误：{self._flatten_content(result)}")

        texts = []
        for item in result.get("content", []):
            if item.get("type") == "text":
                texts.append(item.get("text", ""))
        joined = "\n".join(t for t in texts if t)
        if not joined:
            return result
        try:
            return json.loads(joined)
        except json.JSONDecodeError:
            return joined

    @staticmethod
    def _flatten_content(result: dict) -> str:
        out = []
        for item in result.get("content", []):
            if item.get("type") == "text":
                out.append(item.get("text", ""))
        return "\n".join(out)


# ---------- CLI ----------

def load_args(spec: str | None) -> dict:
    if not spec:
        return {}
    if spec.startswith("@"):
        with open(spec[1:], "r", encoding="utf-8") as f:
            return json.load(f)
    try:
        return json.loads(spec)
    except json.JSONDecodeError:
        # 兼容 k=v k=v 的简写
        out: dict[str, Any] = {}
        for pair in spec.split():
            if "=" not in pair:
                continue
            k, v = pair.split("=", 1)
            out[k] = int(v) if v.lstrip("-").isdigit() else v
        return out


def main() -> int:
    parser = argparse.ArgumentParser(description="麦当劳 MCP Server 零依赖客户端")
    parser.add_argument("command", choices=["list-tools", "call", "ping"])
    parser.add_argument("tool", nargs="?", help="call 时的工具名")
    parser.add_argument("--args", default="", help="JSON 字符串，或 @file.json")
    parser.add_argument("--token", default=os.environ.get("MCD_MCP_TOKEN", ""))
    parser.add_argument("--endpoint", default=ENDPOINT)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    if not args.token:
        print(
            "错误：没有找到 MCP Token。\n"
            "  1. 打开 https://open.mcd.cn/mcp ，用手机号登录\n"
            "  2. 进入「控制台」→「激活」→ 同意服务协议，复制 Token\n"
            "  3. export MCD_MCP_TOKEN=你的token\n"
            "也可以用 --token 直接传入（不推荐，会留在 shell history 里）。",
            file=sys.stderr,
        )
        return 1

    try:
        client = McpClient(args.token, args.endpoint, args.debug)
    except McpError as e:
        print(f"错误：{e}", file=sys.stderr)
        return 1

    try:
        if args.command == "list-tools":
            tools = client.list_tools()
            print(json.dumps(tools, ensure_ascii=False, indent=2))
        elif args.command == "ping":
            info = client.initialize()
            print(json.dumps(info, ensure_ascii=False, indent=2))
        else:
            if not args.tool:
                parser.error("call 需要指定工具名")
            result = client.call_tool(args.tool, load_args(args.args))
            if isinstance(result, (dict, list)):
                print(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                print(result)
    except McpError as e:
        print(f"错误：{e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
