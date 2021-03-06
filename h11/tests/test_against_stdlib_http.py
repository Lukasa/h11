import os.path
from contextlib import contextmanager
import socket
import socketserver
import threading
from http.server import SimpleHTTPRequestHandler
import json
from urllib.request import urlopen

import h11

@contextmanager
def socket_server(handler):
    httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever,
                              kwargs={"poll_interval": 0.01},
                              daemon=True)
    try:
        thread.start()
        yield httpd
    finally:
        httpd.shutdown()

test_file_path = os.path.join(os.path.dirname(__file__), "data/test-file")
with open(test_file_path, "rb") as f:
    test_file_data = f.read()

class SingleMindedRequestHandler(SimpleHTTPRequestHandler):
    def translate_path(self, path):
        return test_file_path

def test_h11_as_client():
    with socket_server(SingleMindedRequestHandler) as httpd:
        with socket.create_connection(httpd.server_address) as s:
            c = h11.Connection(h11.CLIENT)

            s.sendall(c.send(h11.Request(
                method="GET", target="/foo", headers=[("Host", "localhost")])))
            s.sendall(c.send(h11.EndOfMessage()))

            data = bytearray()
            done = False
            while not done:
                # Use a small read buffer to make things more challenging and
                # exercise more paths :-)
                for event in c.receive_data(s.recv(10)):
                    print(event)
                    if type(event) is h11.Response:
                        assert event.status_code == 200
                    if type(event) is h11.Data:
                        data += event.data
                    if type(event) is h11.EndOfMessage:
                        done = True
            assert bytes(data) == test_file_data

class H11RequestHandler(socketserver.BaseRequestHandler):
    def handle(self):
        with self.request as s:
            c = h11.Connection(h11.SERVER)
            request = None
            done = False
            while not done:
                # Use a small read buffer to make things more challenging and
                # exercise more paths :-)
                for event in c.receive_data(s.recv(10)):
                    print(event)
                    if type(event) is h11.Request:
                        request = event
                    if type(event) is h11.EndOfMessage:
                        done = True
                        break
            info = json.dumps({
                "method": request.method.decode("ascii"),
                "target": request.target.decode("ascii"),
                "headers": {
                    name.decode("ascii"): value.decode("ascii")
                    for (name, value) in request.headers
                    },
            })
            s.sendall(c.send(h11.Response(status_code=200, headers=[])))
            s.sendall(c.send(h11.Data(data=info.encode("ascii"))))
            s.sendall(c.send(h11.EndOfMessage()))

def test_h11_as_server():
    with socket_server(H11RequestHandler) as httpd:
        host, port = httpd.server_address
        with urlopen("http://{}:{}/some-path".format(host, port)) as f:
            assert f.getcode() == 200
            data = f.read()
    info = json.loads(data.decode("ascii"))
    print(info)
    assert info["method"] == "GET"
    assert info["target"] == "/some-path"
    assert "urllib" in info["headers"]["user-agent"]
