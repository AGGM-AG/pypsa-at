#!/usr/bin/env python3
"""
Tiny TCP relay: exposes the PyCharm backend (127.0.0.1:5990) on 0.0.0.0:5991
inside the devcontainer, so the docker host can reach it and a native OpenSSH
`ssh -L` tunnel from Windows can replace JetBrains Gateway's sshj transport
(workaround for pypsa-at-planning issue #317).

Run inside the container:  nohup python3 relay.py > relay5991.log 2>&1 &
"""

import asyncio
import sys

LISTEN = ("0.0.0.0", 5991)
TARGET = ("127.0.0.1", 5990)


async def pipe(reader, writer):
    try:
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()
    except Exception:
        pass
    finally:
        try:
            writer.close()
        except Exception:
            pass


async def handle(client_r, client_w):
    try:
        target_r, target_w = await asyncio.open_connection(*TARGET)
    except Exception as e:
        print("backend unreachable:", e, file=sys.stderr, flush=True)
        client_w.close()
        return
    await asyncio.gather(pipe(client_r, target_w), pipe(target_r, client_w))


async def main():
    server = await asyncio.start_server(handle, *LISTEN)
    print(f"relay {LISTEN} -> {TARGET}", flush=True)
    async with server:
        await server.serve_forever()


asyncio.run(main())
