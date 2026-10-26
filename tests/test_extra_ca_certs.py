"""`extra_ca_certs`: the per-scraper opt-in for a server that omits its
intermediate certificate.

Benalla's server sends only its leaf certificate. Browsers fetch the missing
intermediate from the leaf's AIA URL; requests does not, so the handshake
fails. The fix ships the intermediate and trusts it, on top of certifi, for
that scraper's requests only. These pin the two halves of that: the opt-in
makes such a server verifiable, and nothing else changes—a fetcher without it
still refuses the same server, and certificate checks are never switched off.

They run against a local TLS server with a throwaway CA chain, set up the way
Benalla's is: root, intermediate, and a leaf served without the intermediate.
"""

import hashlib
import os
import re
import shutil
import ssl
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import certifi
import pytest
import requests

from aus_council_scrapers.base import CERTS_DIR, DefaultFetcher, ca_bundle_with
from aus_council_scrapers.scrapers.vic.benalla import BenallaScraper

_CA_EXT = (
    "basicConstraints=critical,CA:TRUE\n"
    "keyUsage=critical,keyCertSign,cRLSign\n"
    "subjectKeyIdentifier=hash\n"
)
_INTERMEDIATE_EXT = _CA_EXT + "authorityKeyIdentifier=keyid\n"
_LEAF_EXT = (
    "basicConstraints=CA:FALSE\n"
    "keyUsage=critical,digitalSignature,keyEncipherment\n"
    "extendedKeyUsage=serverAuth\n"
    "subjectAltName=IP:127.0.0.1\n"
    "subjectKeyIdentifier=hash\n"
    "authorityKeyIdentifier=keyid\n"
)


def _openssl(*args, cwd):
    subprocess.run(["openssl", *args], cwd=cwd, check=True, capture_output=True)


def _issue(cwd, name, subject, ext, issuer=None, serial="1"):
    """Key and certificate `<name>.key`/`<name>.pem`, signed by `issuer` or self."""
    with open(os.path.join(cwd, f"{name}.ext"), "w") as f:
        f.write(ext)
    _openssl(
        "req",
        "-new",
        "-newkey",
        "rsa:2048",
        "-nodes",
        "-keyout",
        f"{name}.key",
        "-subj",
        subject,
        "-out",
        f"{name}.csr",
        cwd=cwd,
    )
    signing = (
        ["-CA", f"{issuer}.pem", "-CAkey", f"{issuer}.key", "-set_serial", serial]
        if issuer
        else ["-signkey", f"{name}.key"]
    )
    _openssl(
        "x509",
        "-req",
        "-in",
        f"{name}.csr",
        *signing,
        "-days",
        "2",
        "-sha256",
        "-extfile",
        f"{name}.ext",
        "-out",
        f"{name}.pem",
        cwd=cwd,
    )
    return os.path.join(cwd, f"{name}.pem")


@pytest.fixture(scope="module")
def chain(tmp_path_factory):
    if not shutil.which("openssl"):
        pytest.skip("needs the openssl command to build a test CA")
    cwd = str(tmp_path_factory.mktemp("ca"))
    root = _issue(cwd, "root", "/CN=Test Root", _CA_EXT)
    intermediate = _issue(
        cwd, "intermediate", "/CN=Test Intermediate", _INTERMEDIATE_EXT, "root", "2"
    )
    leaf = _issue(cwd, "leaf", "/CN=127.0.0.1", _LEAF_EXT, "intermediate", "3")
    return {"root": root, "intermediate": intermediate, "leaf": leaf, "dir": cwd}


@pytest.fixture(scope="module")
def server(chain):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = b"ok"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    httpd.daemon_threads = True
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    # The leaf alone, as Benalla serves it: no intermediate in the handshake.
    context.load_cert_chain(chain["leaf"], os.path.join(chain["dir"], "leaf.key"))
    httpd.socket = context.wrap_socket(httpd.socket, server_side=True)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"https://127.0.0.1:{httpd.server_port}/"
    httpd.shutdown()


def test_a_fetcher_without_the_opt_in_refuses_a_server_missing_its_intermediate(
    server,
):
    with pytest.raises(requests.exceptions.SSLError):
        DefaultFetcher(fetch_delay=0).fetch_with_requests(server)


def test_trusting_the_root_alone_is_not_enough(server, chain):
    fetcher = DefaultFetcher(fetch_delay=0, extra_ca_certs=(chain["root"],))
    with pytest.raises(requests.exceptions.SSLError):
        fetcher.fetch_with_requests(server)


def test_shipping_the_intermediate_makes_the_server_verifiable(server, chain):
    fetcher = DefaultFetcher(
        fetch_delay=0, extra_ca_certs=(chain["root"], chain["intermediate"])
    )
    assert fetcher.fetch_with_requests(server) == "ok"


def test_the_bundle_keeps_every_certifi_root(chain):
    with open(certifi.where(), encoding="utf-8") as f:
        roots = f.read()
    with open(ca_bundle_with((chain["intermediate"],)), encoding="utf-8") as f:
        bundle = f.read()
    assert bundle.startswith(roots)
    context = ssl.create_default_context(cafile=certifi.where())
    extended = ssl.create_default_context(
        cafile=ca_bundle_with((chain["intermediate"],))
    )
    assert (
        extended.cert_store_stats()["x509_ca"]
        == context.cert_store_stats()["x509_ca"] + 1
    )


@pytest.mark.parametrize("name", BenallaScraper.extra_ca_certs)
def test_shipped_certificates_match_the_fingerprint_in_their_header(name):
    with open(os.path.join(CERTS_DIR, name), encoding="utf-8") as f:
        text = f.read()
    stated = re.search(r"^# SHA-256:\s+([0-9A-F]{64})\s*$", text, re.MULTILINE)
    assert stated, f"{name} has no '# SHA-256:' line saying what it should be"
    pem = text[text.index("-----BEGIN CERTIFICATE-----") :]
    actual = hashlib.sha256(ssl.PEM_cert_to_DER_cert(pem)).hexdigest().upper()
    assert actual == stated[1]
