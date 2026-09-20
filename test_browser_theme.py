import subprocess
import time
import json
import urllib.request
import base64
import os

# We will connect to CDP websocket using standard library or simple socket
import socket
import ssl
import hashlib

def create_ws_frame(data_str):
    data = data_str.encode('utf-8')
    length = len(data)
    frame = bytearray([0x81]) # text frame, FIN=1
    if length <= 125:
        frame.append(0x80 | length) # mask=1
    elif length <= 65535:
        frame.append(0x80 | 126)
        frame.extend(length.to_bytes(2, 'big'))
    else:
        frame.append(0x80 | 127)
        frame.extend(length.to_bytes(8, 'big'))
    
    # 4 bytes mask
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

def run_test():
    proc = subprocess.Popen([
        r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
        '--headless=new',
        '--remote-debugging-port=9222',
        '--user-data-dir=C:\\dev\\saestu\\edge_profile',
        '--window-size=1280,1200',
        'http://localhost:8080'
    ])
    time.sleep(2)
    try:
        tabs_data = urllib.request.urlopen('http://localhost:9222/json').read()
        tabs = json.loads(tabs_data.decode('utf-8'))
        page_tab = next(t for t in tabs if t.get('type') == 'page' and '8080' in t.get('url', ''))
        ws_url = page_tab['webSocketDebuggerUrl']
        
        # Connect to WS
        host_port, path = ws_url.replace('ws://', '').split('/', 1)
        host, port = host_port.split(':')
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((host, int(port)))
        
        # Handshake
        key = base64.b64encode(os.urandom(16)).decode('utf-8')
        req = (
            f"GET /{path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        sock.sendall(req.encode('utf-8'))
        resp = sock.recv(1024)
        print("[*] WebSocket Connected to Edge CDP")

        def send_cdp(method, params=None, msg_id=1):
            msg = {"id": msg_id, "method": method, "params": params or {}}
            sock.sendall(create_ws_frame(json.dumps(msg)))
            while True:
                r = parse_ws_frame(sock)
                if r:
                    try:
                        parsed = json.loads(r)
                        if parsed.get('id') == msg_id:
                            return parsed
                    except:
                        pass

        # Reset localStorage to test clean state
        send_cdp("Runtime.evaluate", {"expression": "localStorage.clear(); document.documentElement.classList.remove('dark');"}, 8)
        time.sleep(0.5)

        # 1. Check computed bg color in Light Mode
        cls1 = send_cdp("Runtime.evaluate", {"expression": "document.documentElement.className"}, 9)
        print("[Light Mode] html class:", cls1.get('result', {}).get('result', {}).get('value'))
        bcls = send_cdp("Runtime.evaluate", {"expression": "document.body.className"}, 91)
        print("[Body class]:", bcls.get('result', {}).get('result', {}).get('value'))
        
        # Check matching rules on body
        tw = send_cdp("Runtime.evaluate", {"expression": "(() => { return [...document.querySelectorAll('style')].map(s => s.textContent).join('\\n'); })()"}, 92)
        css_text = tw.get('result', {}).get('result', {}).get('value', '')
        dark_lines = [l for l in css_text.splitlines() if 'dark' in l]
        print("[Tailwind dark rules count]:", len(dark_lines))
        print("[Sample dark rules]:", dark_lines[:5])

        res1 = send_cdp("Runtime.evaluate", {"expression": "getComputedStyle(document.body).backgroundColor"}, 10)
        print("[Light Mode] Body background:", res1.get('result', {}).get('result', {}).get('value'))

        # 2. Capture Light Mode screenshot
        ss1 = send_cdp("Page.captureScreenshot", {"format": "png"}, 11)
        if 'data' in ss1.get('result', {}):
            with open("C:/dev/saestu/screenshot_light.png", "wb") as f:
                f.write(base64.b64decode(ss1['result']['data']))
            print("[OK] Saved screenshot_light.png")

        # 3. Toggle to Dark Mode
        send_cdp("Runtime.evaluate", {"expression": "toggleTheme()"}, 20)
        time.sleep(0.5)

        # 4. Check computed bg color in Dark Mode
        cls2 = send_cdp("Runtime.evaluate", {"expression": "document.documentElement.className"}, 201)
        print("[Dark Mode] html class:", cls2.get('result', {}).get('result', {}).get('value'))
        res2 = send_cdp("Runtime.evaluate", {"expression": "getComputedStyle(document.body).backgroundColor"}, 21)
        print("[Dark Mode] Body background:", res2.get('result', {}).get('result', {}).get('value'))

        # 5. Capture Dark Mode screenshot
        ss2 = send_cdp("Page.captureScreenshot", {"format": "png"}, 22)
        if 'data' in ss2.get('result', {}):
            with open("C:/dev/saestu/screenshot_dark.png", "wb") as f:
                f.write(base64.b64decode(ss2['result']['data']))
            print("[OK] Saved screenshot_dark.png")

    finally:
        proc.terminate()

if __name__ == "__main__":
    run_test()
