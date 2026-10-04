"""Run with python -m dashboard.server. Serves saved results; cannot run backtests."""
import argparse
import json
import mimetypes
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from dashboard.audit import AuditService
from dashboard.fda_history import FdaHistory
from dashboard.proof import ProofService
from dashboard.repository import ResearchRepository
from dashboard.tiger import TigerMonitor

STATIC = Path(__file__).parent / "static"


def handler(repository, monitor, proof, audit=None, fda=None):
    audit = audit or AuditService(repository.root)
    fda = fda or FdaHistory()

    class Handler(BaseHTTPRequestHandler):
        def respond(self, data, content_type="application/json", status=200, filename=None):
            body = data if isinstance(data, bytes) else json.dumps(data, allow_nan=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store" if content_type == "application/json" else "no-cache")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'")
            if filename:
                self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            parsed = urlsplit(self.path)
            path = unquote(parsed.path)
            params = {key: values[0] for key, values in parse_qs(parsed.query).items()}
            try:
                if path == "/api/overview":
                    return self.respond(repository.overview())
                if path == "/api/case":
                    return self.respond(repository.case_study())
                if path == "/api/research":
                    return self.respond(repository.scenario(params.get("strategy", "candidate"),
                        int(params.get("costs", 1)), params.get("vendor", "reference_mix")))
                if path == "/api/evidence":
                    return self.respond(repository.evidence(params.get("q", "")[:200], params.get("ticker", ""),
                        params.get("role", ""), max(0, int(params.get("offset", 0))),
                        min(100, max(1, int(params.get("limit", 15))))))
                if path == "/api/event":
                    return self.respond(repository.event(params.get("id", ""), params.get("ticker", "")))
                if path == "/api/proof":
                    return self.respond(proof.summary())
                if path == "/api/proof/verify":
                    return self.respond(proof.verify())
                if path == "/api/audit/variants":
                    return self.respond(audit.variants())
                if path == "/api/audit/freeze":
                    return self.respond(audit.freeze())
                if path == "/api/fda/asof":
                    return self.respond(fda.asof(params.get("date", "")))
                if path == "/api/fda/timeline":
                    return self.respond(fda.timeline(params.get("drug", "")[:300]))
                if path == "/api/live":
                    return self.respond(monitor.snapshot())
                if path == "/api/live/history":
                    return self.respond(monitor.history(params.get("ticker", "ICUI")))
                if path == "/api/health":
                    return self.respond(dict(ok=True, mode="read_only", time=datetime.now(timezone.utc).isoformat()))
                if path.startswith("/api/explain/"):
                    return self.respond(repository.explanation(path.removeprefix("/api/explain/")[:100]))
                if path.startswith("/api/download/"):
                    file = repository.download(path.removeprefix("/api/download/"),
                            int(params.get("costs", 1)), params.get("vendor", "reference_mix"))
                    return self.respond(file.read_bytes(), mimetypes.guess_type(file.name)[0] or "text/plain", filename=file.name)
                if path.startswith("/api/"):
                    raise KeyError("Endpoint not found")
                file = (STATIC / ("index.html" if path == "/" else path.lstrip("/"))).resolve()
                if not file.is_relative_to(STATIC.resolve()) or not file.is_file():
                    raise KeyError("File not found")
                return self.respond(file.read_bytes(), mimetypes.guess_type(file.name)[0] or "application/octet-stream")
            except (ValueError, KeyError):
                self.respond(dict(error="Requested record or parameter is not available"), status=404)
            except Exception:
                self.respond(dict(error="Research data could not be loaded"), status=500)

        def log_message(self, fmt, *args):
            # Do not log query strings; connection settings are never accepted over HTTP.
            print(f"dashboard: {self.command} {urlsplit(self.path).path}", flush=True)

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--data-root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    try:
        from dotenv import load_dotenv
        load_dotenv(args.data_root / ".env", override=False)
    except ImportError:
        pass
    server = ThreadingHTTPServer((args.host, args.port), handler(ResearchRepository(args.data_root), TigerMonitor(),
                                                                ProofService(args.data_root)))
    print(f"Backfill observatory · http://{args.host}:{args.port} · read-only", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
