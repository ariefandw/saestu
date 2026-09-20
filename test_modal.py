import subprocess
import time
import json
import urllib.request
import base64
import os
import socket

def create_ws_frame(data_str):
    data = data_str.encode('utf-8')
    length = len(data)
    frame = bytearray([0x81])
    if length <= 125:
        frame.append(0x80 | length)
    elif length <= 65535:
        frame.append(0x80 | 126)
        frame.extend(length.to_bytes(2, 'big'))
    else:
        frame.append(0x80 | 127)
        frame.extend(length.to_bytes(8, 'big'))
    mask = bytearray([0x12, 0x34, 0x56, 0x78])
    frame.extend(mask)
    for i in range(length):
        frame.append(data[i] ^ mask[i % 4])
    return frame

def parse_ws_frame(sock):
    header = sock.recv(2)
    if not header or len(header) < 2:
        return ""
    length = header[1] & 0x7F
    if length == 126:
        length = int.from_bytes(sock.recv(2), 'big')
    elif length == 127:
        length = int.from_bytes(sock.recv(8), 'big')
    data = b""
    while len(data) < length:
        chunk = sock.recv(length - len(data))
        if not chunk:
            break
        data += chunk
    return data.decode('utf-8', errors='ignore')

def capture_modal():
    proc = subprocess.Popen([
        r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
        '--headless=new',
        '--remote-debugging-port=9222',
        '--user-data-dir=C:\\dev\\saestu\\edge_profile_modal3',
        '--window-size=1280,900',
        'http://localhost:8080'
    ])
    time.sleep(2)
    try:
        tabs = json.loads(urllib.request.urlopen('http://localhost:9222/json').read().decode('utf-8'))
        page_tab = next(t for t in tabs if '8080' in t.get('url', ''))
        ws_url = page_tab['webSocketDebuggerUrl']
        host_port, path = ws_url.replace('ws://', '').split('/', 1)
        host, port = host_port.split(':')
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((host, int(port)))

        key = base64.b64encode(os.urandom(16)).decode('utf-8')
        req = f"GET /{path} HTTP/1.1\r\nHost: {host}:{port}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
        sock.sendall(req.encode('utf-8'))
        sock.recv(1024)

        def send_cdp(method, params=None, msg_id=1):
            sock.sendall(create_ws_frame(json.dumps({'id': msg_id, 'method': method, 'params': params or {}})))
            while True:
                r = parse_ws_frame(sock)
                if r:
                    try:
                        p = json.loads(r)
                        if p.get('id') == msg_id:
                            return p
                    except:
                        pass

        send_cdp('Runtime.evaluate', {'expression': "document.documentElement.className = '';"})
        time.sleep(1)

        # Trigger open modal
        res = send_cdp('Runtime.evaluate', {'expression': "openPhotoModalFromHero();"})
        print("openPhotoModal result:", res)
        time.sleep(0.5)

        # Capture screenshot
        ss = send_cdp('Page.captureScreenshot', {'format': 'png'})
        if 'result' in ss and 'data' in ss['result']:
            with open('C:/dev/saestu/screenshot_modal.png', 'wb') as f:
                f.write(base64.b64decode(ss['result']['data']))
            print("[OK] Saved screenshot_modal.png successfully")

    finally:
        proc.terminate()

if __name__ == '__main__':
    capture_modal()
