"""
gpustat.web


MIT License

Copyright (c) 2018-2023 Jongwook Choi (@wookayin)
"""

from typing import List, Tuple, Optional, Union
import json
import re
import os
import traceback
import urllib.parse
import ssl

import asyncio
import asyncssh
import aiohttp

from datetime import datetime
from collections import OrderedDict

from termcolor import cprint, colored
from aiohttp import web
import aiohttp_jinja2 as aiojinja2


__PATH__ = os.path.abspath(os.path.dirname(__file__))

DEFAULT_GPUSTAT_COMMAND = "gpustat --color --gpuname-width 30 --show-power"

RE_ANSI = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')

###############################################################################
# Background workers to collect information from nodes
###############################################################################

class Context(object):
    '''The global context object.'''
    def __init__(self):
        self.host_status = OrderedDict()
        self.interval = 5.0

    def host_set_message(self, hostname: str, msg: str):
        self.host_status[hostname] = colored(f"({hostname}) ", 'white') + msg + '\n'


context = Context()

async def run_client(hostname: str, exec_cmd: str, *,
                     username: str,
                     port=22, verify_host: bool = True,
                     poll_delay=5.0, timeout=30.0,
                     verbose=False):
    '''建立 SSH 連線，執行 `gpustat`，並回報狀態'''

    conn_kwargs = {'known_hosts': None} if not verify_host else {}

    async def _loop_body():
        async with asyncssh.connect(hostname, port=port, username=username, **conn_kwargs) as conn:
            cprint(f"[{hostname}] SSH connection established!", attrs=['bold'])

            while True:
                result = await asyncio.wait_for(conn.run(exec_cmd), timeout=timeout)

                if result.exit_status != 0:
                    stderr_summary = result.stderr.split('\n')[0]
                    context.host_set_message(hostname, colored(f'[Error {result.exit_status}] {stderr_summary}', 'red'))
                else:
                    if verbose:
                        cprint(f"[{hostname}] {result.stdout}", color="cyan")  # ✅ 顯示 debug 訊息
                    context.host_status[hostname] = result.stdout.strip() + "\n\n\n\n"
                    
                await asyncio.sleep(poll_delay)

    while True:
        try:
            await _loop_body()
        except Exception as e:
            cprint(f"[{hostname}] {type(e).__name__}: {e}", color='red')
            context.host_set_message(hostname, colored(f"{type(e).__name__}: {e}", 'red'))
        cprint(f"[{hostname}] Disconnected, retrying in {poll_delay} sec...", color='yellow')
        await asyncio.sleep(poll_delay)


async def spawn_clients(hosts: List[str], exec_cmds: dict, *,
                        default_port: int, verify_host: bool = True,
                        verbose=False):
    """啟動多個 SSH 連線，每個 host 執行不同的 exec_cmd"""

    def _parse_host_string(netloc: str):
        """解析 `USER@HOSTNAME[:PORT]` 格式，確保 `username`、`hostname` 和 `port`"""
        match = re.match(r'(?:(?P<user>[\w-]+)@)?(?P<host>[^:]+)(?::(?P<port>\d+))?', netloc)
        if not match or not match.group("host"):
            raise ValueError(f"Invalid host format: {netloc}")

        username = match.group("user") or "netdb"  # **如果沒有指定 user，預設使用 "netdb"**
        hostname = match.group("host")
        port = int(match.group("port")) if match.group("port") else default_port
        return username, hostname, port

    try:
        parsed_hosts = [_parse_host_string(host) for host in hosts]  # ✅ **確保不會有 None**
        host_users, host_names, host_ports = zip(*parsed_hosts)

        # 初始化回應
        for hostname in host_names:
            context.host_set_message(hostname, "Loading ...")

        # 啟動所有 SSH 連線，每台機器使用不同的 `exec_cmd`
        await asyncio.gather(*[
            run_client(
                hostname,
                exec_cmds.get(hostname, "gpustat --color --force-color"),  # ✅ **允許每台機器不同 `exec_cmd`**
                port=port,
                username=username,
                verify_host=verify_host,
                verbose=verbose
            )
            for username, hostname, port in parsed_hosts  # ✅ **這裡改成用 `parsed_hosts`，確保不會有 `NoneType`**
        ])
    except Exception as ex:
        traceback.print_exc()
        cprint(colored("Error: An exception occurred during the startup.", 'red'))

###############################################################################
# webserver handlers.
###############################################################################

# monkey-patch ansi2html scheme. TODO: better color codes
import ansi2html.style
scheme = 'solarized'
ansi2html.style.SCHEME[scheme] = list(ansi2html.style.SCHEME[scheme])
ansi2html.style.SCHEME[scheme][0] = '#555555'
ansi_conv = ansi2html.Ansi2HTMLConverter(dark_bg=True, scheme=scheme)


def render_gpustat_body(
    mode='html',   # mode: Literal['html'] | Literal['html_full'] | Literal['ansi']
    *,
    full_html: bool = False,
    nodes: Optional[List[str]] = None,
):
    body = ''
    for host, status in context.host_status.items():
        if not status:
            continue
        if nodes is not None and host not in nodes:
            continue
        body += status

    if mode == 'html':
        return ansi_conv.convert(body, full=full_html)
    elif mode == 'ansi':
        return body
    elif mode == 'plain':
        return RE_ANSI.sub('', body)
    else:
        raise ValueError(mode)


async def handler(request):
    '''Renders the html page.'''

    data = dict(
        ansi2html_headers=ansi_conv.produce_headers().replace('\n', ' '),
        http_host=request.host,
        interval=int(context.interval * 1000)
    )
    response = aiojinja2.render_template('index.html', request, data)
    response.headers['Content-Language'] = 'en'
    return response


def _parse_querystring_list(value: Optional[str]) -> Optional[List[str]]:
    return value.strip().split(',') if value else None


def make_static_handler(content_type: str):

    async def handler(request: web.Request):
        # query string handling
        full: bool = request.query.get('full', '1').lower() in ("yes", "true", "1")
        nodes: Optional[List[str]] = _parse_querystring_list(request.query.get('nodes'))

        body = render_gpustat_body(mode=content_type,
                                   full_html=full,
                                   nodes=nodes)
        response = web.Response(body=body)
        response.headers['Content-Language'] = 'en'
        response.headers['Content-Type'] = f'text/{content_type}; charset=utf-8'
        return response

    return handler


async def websocket_handler(request):
    print("INFO: Websocket connection from {} established".format(request.remote))

    ws = web.WebSocketResponse()
    await ws.prepare(request)

    async def _handle_websocketmessage(msg):
        if msg.data == 'close':
            await ws.close()
        else:
            try:
                payload = json.loads(msg.data)
            except json.JSONDecodeError:
                cprint(f"Malformed message from {request.remote}", color='yellow')
                return

            # send the rendered HTML body as a websocket message.
            nodes: Optional[List[str]] = _parse_querystring_list(payload.get('nodes'))
            body = render_gpustat_body(mode='html', full_html=False, nodes=nodes)
            await ws.send_str(body)

    async for msg in ws:
        if msg.type == aiohttp.WSMsgType.CLOSE:
            break
        elif msg.type == aiohttp.WSMsgType.TEXT:
            await _handle_websocketmessage(msg)
        elif msg.type == aiohttp.WSMsgType.ERROR:
            cprint("Websocket connection closed with exception %s" % ws.exception(), color='red')

    print("INFO: Websocket connection from {} closed".format(request.remote))
    return ws

###############################################################################
# app factory and entrypoint.
###############################################################################

def create_app(*,
               hosts=['localhost'],
               default_port: int = 22,
               verify_host: bool = True,
               ssl_certfile: Optional[str] = None,
               ssl_keyfile: Optional[str] = None,
               exec_cmds: dict = None,  # ✅ 確保 exec_cmds 參數正確
               verbose=True):

    app = web.Application()
    app.router.add_get('/', handler)
    app.add_routes([web.get('/ws', websocket_handler)])
    app.add_routes([web.get('/gpustat.html', make_static_handler('html'))])
    app.add_routes([web.get('/gpustat.ansi', make_static_handler('ansi'))])
    app.add_routes([web.get('/gpustat.txt', make_static_handler('plain'))])

    async def start_background_tasks(app):
        clients = spawn_clients(
            hosts, exec_cmds,  # ✅ 傳遞 exec_cmds 到 `spawn_clients()`
            default_port=default_port,
            verify_host=verify_host,
            verbose=verbose
        )
        loop = app.loop if hasattr(app, 'loop') else asyncio.get_event_loop()
        app['tasks'] = loop.create_task(clients)
        await asyncio.sleep(0.1)

    app.on_startup.append(start_background_tasks)

    async def shutdown_background_tasks(app):
        cprint(f"... Terminating the application", color='yellow')
        app['tasks'].cancel()

    app.on_shutdown.append(shutdown_background_tasks)
    # jinja2 setup
    import jinja2
    aiojinja2.setup(app,
                    loader=jinja2.FileSystemLoader(
                        os.path.join(__PATH__, 'template'))
                    )

    # SSL setup
    if ssl_certfile and ssl_keyfile:
        ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        ssl_context.load_cert_chain(certfile=ssl_certfile,
                                    keyfile=ssl_keyfile)

        cprint(f"Using Secure HTTPS (SSL/TLS) server ...", color='green')
    else:
        ssl_context = None  # type: ignore
    return app, ssl_context


def main():
    import argparse
    parser = argparse.ArgumentParser(description="GPUStat Web Server")
    parser.add_argument("hosts", nargs="*", help="List of nodes. Syntax: HOSTNAME[:PORT]")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--port", type=int, default=48109, help="Web application port")
    parser.add_argument("--ssh-port", type=int, default=22, help="Default SSH port")
    parser.add_argument("--no-verify-host", action="store_true", help="Skip SSH host key verification")
    parser.add_argument("--interval", type=float, default=5.0, help="Polling interval")
    parser.add_argument("--exec", action="append",
                        help="Custom exec_cmd for specific hosts, format: 'IP:/path/to/gpustat'")

    args = parser.parse_args()

    hosts = args.hosts or ["localhost"]
    cprint(f"Hosts : {hosts}", color="green")

    # 解析 exec_cmds
    exec_cmds = {}
    if args.exec:
        for entry in args.exec:
            ip, cmd = entry.split(":", 1)
            exec_cmds[ip] = cmd + " --color --force-color"

    cprint(f"Exec Commands: {exec_cmds}", color="yellow")

    if args.interval > 0.1:
        context.interval = args.interval

    app, _ = create_app(
        hosts=hosts,
        exec_cmds=exec_cmds,  # ✅ 確保 exec_cmds 傳遞到 `create_app()`
        default_port=args.ssh_port,
        verify_host=not args.no_verify_host,
        verbose=args.verbose
    )

    web.run_app(app, host="0.0.0.0", port=args.port)

if __name__ == '__main__':
    main()
