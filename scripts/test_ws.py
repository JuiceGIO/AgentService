"""WebSocket 验证脚本：连接 /ws/chat，发一条消息，确认收到流式 token 与 done。"""

import asyncio
import json
import sys

import websockets


async def main():
    uri = sys.argv[1] if len(sys.argv) > 1 else "ws://127.0.0.1:8010/ws/chat?session_id=deploytest"
    async with websockets.connect(uri) as ws:
        await ws.send(json.dumps({"type": "user", "message": "我的订单到哪了？"}, ensure_ascii=False))
        tokens = 0
        steps = 0
        reply = ""
        while True:
            msg = json.loads(await ws.recv())
            t = msg.get("type")
            if t == "token":
                tokens += 1
                reply += msg.get("content", "")
            elif t == "steps":
                steps = len(msg.get("steps", []))
            elif t == "done":
                print(f"WS OK: steps={steps} tokens={tokens} reply_len={len(msg.get('reply', ''))}")
                return
            elif t == "error":
                print("WS ERROR:", msg.get("message"))
                sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
