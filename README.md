gpustat-web-netdb
===========

A web interface of [`gpustat`][gpustat] ---
aggregate `gpustat` across multiple nodes.

<p align="center">
  <img src="https://github.com/wookayin/gpustat-web/raw/master/screenshot.png" width="800" height="192" />
</p>

**NOTE**: This project is in alpha stage. Errors and exceptions are not well handled, and it might use much network resources. Please use at your own risk!


Installation
-----

```
python3 -m venv venv
source venv/bin/activate
pip uninstall -y gpustat-web
pip install --upgrade pip setuptools wheel
pip install --no-cache-dir --no-build-isolation .
which gpustat-web
```

Python 3.6+ is required.

Usage
-----

Launch the application as follows. A SSH connection will be established to each of the specified hosts.
Make sure `ssh <host>` works under a proper authentication scheme such as SSH authentication.
Now we can set multiple port for different host
```
gpustat-web --port 48109     --exec "10.6.8.82:/home/netdb/.local/bin/gpustat"     --exec "10.6.8.83:/home/netdb/.local/bin/gpustat"     --exec "10.6.8.81:/home/netdb/.local/bin/gpustat"     --exec "140.116.247.117:/mnt/data/home/joeysmith/.local/bin/gpustat" --exec "192.168.61.2:/home/joeysmith/.local/bin/gpustat" --exec "10.6.8.84:/home/netdb/.local/bin/gpustat" --exec "10.6.8.85:/home/netdb/.local/bin/gpustat"    10.6.8.82 10.6.8.83 10.6.8.81 10.6.8.84 10.6.8.85 joeysmith@140.116.247.117:18722 joeysmith@192.168.61.2:6022
```

**NOTE**: You should add the ssh-key of the machine that running gpustat-web to other nodes, also every nodes should install gpustat
```
ssh-copy-id -i .ssh/id_rsa.pub user@other_node_ip
```
Run in background as system service
-----
```
sudo vim /etc/systemd/system/gpustat-web.service
```
```
[Unit]
Description=GPUStat Web Server
After=network.target

[Service]
User=netdb
WorkingDirectory=/home/netdb
ExecStart=["YOUR RUNNING COMMAND"]
Restart=always
RestartSec=5
Environment="PATH=/home/netdb/.local/bin:/usr/local/bin:/usr/bin:/bin"

[Install]
WantedBy=multi-user.target
```
```
sudo systemctl daemon-reload
```
```
sudo systemctl restart gpustat-web
```
You might get "Host key is not trusted for `<host>`" errors. You'll have to accept and trust SSH keys of the host for the first time (it's stored in `~/.ssh/known_hosts`);
try `ssh <host>` in the command line, or `ssh -oStrictHostKeyChecking=accept-new <host>` to automatically accept the host key. You can also use an option `gpustat-web --no-verify-host` to bypass SSH Host key validation (although not recommended).

Note that asyncssh [does NOT obey](https://github.com/ronf/asyncssh/issues/108) the `~/.ssh/config` file
(e.g. alias, username, keyfile), so any config in `~/.ssh/config` might not be picked up.


[gpustat]: https://github.com/wookayin/gpustat/


### Endpoints

- `https://HOST:PORT/`: A webpage that updates automatically through websocket.
- `https://HOST:PORT/gpustat.html`: Result as a static HTML page.
- `https://HOST:PORT/gpustat.txt`: Result as a static plain text.
- `https://HOST:PORT/gpustat.ansi`: Result as a static text with ANSI color codes. Try `curl https://.../gpustat.ansi`

Query strings:

- `?nodes=gpu001,gpu002`: Select a subset of nodes to query and display


### Running as a HTTP (SSL/TLS) server

By default the web server will run as a HTTP server.
If you want to run a secure SSL/TLS server over the HTTPS protocol, use `--ssl-certfile` and `--ssl-keyfile` option.
You can use letsencrypt (`certbot`) to create a pair of SSL certificate and keyfile.

Troubleshoothing: Verify SSL/TLS handshaking (if TLS connections cannot be established)
```
openssl s_client -showcerts -connect YOUR_HOST.com:PORT < /dev/null
```


### More Examples

To see CPU usage as well:

```
python -m gpustat_web --exec 'gpustat --color --gpuname-width 25 && echo -en "CPU : \033[0;31m" && cpu-usage | ascii-bar 27'
```


License
-------

MIT License

Copyright (c) 2018-2023 Jongwook Choi
