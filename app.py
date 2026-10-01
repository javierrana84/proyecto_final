import os
import re
import resource
import secrets
import sys
import time

from flask import Flask, jsonify, render_template, request
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
import requests

app = Flask(__name__)
FLIGHT_API_URL = os.getenv("FLIGHT_API_URL", "https://airlabs.co/api/v9/flights")
APP_START_TIME = time.monotonic()
REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ("method", "route", "status"),
)
REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds",
    ("method", "route"),
)
APP_PROCESS_MEMORY_BYTES = Gauge(
    "app_process_memory_bytes",
    "Resident memory used by the Flask app process in bytes.",
)
APP_PROCESS_CPU_SECONDS = Gauge(
    "app_process_cpu_seconds_total",
    "Total CPU time spent by the Flask app process in seconds.",
)
APP_UPTIME_SECONDS = Gauge(
    "app_uptime_seconds",
    "Time since the Flask app process started in seconds.",
)


def update_runtime_metrics():
    usage = resource.getrusage(resource.RUSAGE_SELF)
    memory_bytes = usage.ru_maxrss
    if sys.platform == "darwin":
        memory_bytes *= 1024
    elif sys.platform.startswith("linux"):
        memory_bytes *= 1024
    APP_PROCESS_MEMORY_BYTES.set(memory_bytes)
    APP_PROCESS_CPU_SECONDS.set(usage.ru_utime + usage.ru_stime)
    APP_UPTIME_SECONDS.set(time.monotonic() - APP_START_TIME)


@app.before_request
def start_request_timer():
    request.start_time = time.perf_counter()
    request.csp_nonce = secrets.token_urlsafe(16)
    update_runtime_metrics()


@app.after_request
def record_request(response):
    route = request.url_rule.rule if request.url_rule else "unmatched"
    REQUEST_COUNT.labels(request.method, route, str(response.status_code)).inc()
    REQUEST_LATENCY.labels(request.method, route).observe(
        time.perf_counter() - request.start_time
    )
    if request.path.startswith("/static/"):
        response.headers["Cache-Control"] = "public, max-age=3600"
    elif response.status_code == 404:
        response.headers["Cache-Control"] = "public, max-age=60"
    else:
        response.headers["Cache-Control"] = "private, no-cache, max-age=0, must-revalidate"
    response.headers["Content-Security-Policy"] = "; ".join((
        "default-src 'self'",
        "base-uri 'self'",
        "object-src 'none'",
        "frame-ancestors 'none'",
        "form-action 'self'",
        f"script-src 'self' 'nonce-{request.csp_nonce}'",
        "style-src 'self' https://fonts.googleapis.com",
        "font-src 'self' https://fonts.gstatic.com",
        "img-src 'self' data:",
        "connect-src 'self'",
    ))
    response.headers["Cross-Origin-Embedder-Policy"] = "credentialless"
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
    response.headers["Permissions-Policy"] = "camera=(), geolocation=(), microphone=()"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    return response


@app.get("/")
def home():
    return render_template(
        "index.html",
        version=os.getenv("APP_VERSION", "local"),
        csp_nonce=request.csp_nonce,
    )


@app.get("/health")
def health():
    return jsonify(status="ok", version=os.getenv("APP_VERSION", "local"))


@app.get("/ready")
def ready():
    if not os.getenv("AIRLABS_API_KEY"):
        return jsonify(status="not_ready", reason="flight_api_key_missing"), 503
    return jsonify(status="ready")


@app.get("/api/flights")
def flight_status():
    flight_iata = request.args.get("flight_iata", "").strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{2,3}[0-9]{1,5}[A-Z]?", flight_iata):
        return jsonify(error="Ingresa un número de vuelo válido, por ejemplo IB6842."), 400

    api_key = os.getenv("AIRLABS_API_KEY")
    if not api_key:
        return jsonify(error="La consulta de vuelos no está configurada."), 503

    try:
        response = requests.get(
            FLIGHT_API_URL,
            params={"api_key": api_key, "flight_iata": flight_iata},
            timeout=8,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError):
        return jsonify(error="No se pudo consultar el proveedor de vuelos."), 502

    if isinstance(payload, dict) and payload.get("error"):
        return jsonify(error="El proveedor de vuelos rechazó la consulta."), 502

    flights = payload.get("response", []) if isinstance(payload, dict) else payload
    if isinstance(flights, dict):
        flights = [flights]
    fields = (
        "flight_iata", "airline_iata", "dep_iata", "arr_iata", "status",
        "lat", "lng", "alt", "speed", "dir", "updated",
    )
    results = [
        {field: flight.get(field) for field in fields}
        for flight in flights
        if isinstance(flight, dict)
    ]
    return jsonify(flight_iata=flight_iata, flights=results)


@app.get("/metrics")
def metrics():
    return generate_latest(), 200, {"Content-Type": CONTENT_TYPE_LATEST}