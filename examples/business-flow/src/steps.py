def inventory(stock):
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from socketserver import TCPServer
    from urllib.request import urlopen

    class LoopbackHTTPServer(HTTPServer):
        def server_bind(self):
            # This fixture has a fixed loopback identity; reverse DNS is unnecessary.
            TCPServer.server_bind(self)
            self.server_name = "localhost"
            self.server_port = self.server_address[1]

    class InventoryHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            data = json.dumps({"available": stock > 0}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    with LoopbackHTTPServer(("127.0.0.1", 0), InventoryHandler) as server:
        thread = threading.Thread(target=server.handle_request, daemon=True)
        thread.start()
        with urlopen(f"http://127.0.0.1:{server.server_port}/inventory", timeout=3) as response:
            value = json.load(response)
        thread.join(timeout=3)
    return value


def fulfill(amount):
    return {"total": amount}


def decline(amount):
    return "Inventory unavailable"
