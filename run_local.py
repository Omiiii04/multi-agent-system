"""Local multi-process orchestrator for course-creation-agent.

Starts all 4 microservice agents and the web frontend app,
manages their lifecycles, and cleanly terminates them upon Ctrl+C.
"""

import os
import sys
import time
import subprocess
import signal
from pathlib import Path

ROOT_DIR = Path(__file__).parent.resolve()

def load_env_file(env_path: Path):
    """Load key-value pairs from .env into os.environ if not already set."""
    if not env_path.exists():
        return
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = val

def main():
    load_env_file(ROOT_DIR / ".env")

    # Set default environment variables for local operation
    os.environ.setdefault("RESEARCHER_AGENT_CARD_URL", "http://localhost:8001/a2a/agent/.well-known/agent-card.json")
    os.environ.setdefault("JUDGE_AGENT_CARD_URL", "http://localhost:8002/a2a/agent/.well-known/agent-card.json")
    os.environ.setdefault("CONTENT_BUILDER_AGENT_CARD_URL", "http://localhost:8003/a2a/agent/.well-known/agent-card.json")
    os.environ.setdefault("AGENT_SERVER_URL", "http://localhost:8004")
    default_model = os.environ.get("MODEL", "gemini-2.5-flash")
    os.environ.setdefault("MODEL", default_model)
    os.environ.setdefault("RESEARCHER_MODEL", default_model)
    os.environ.setdefault("JUDGE_MODEL", default_model)
    os.environ.setdefault("CONTENT_BUILDER_MODEL", default_model)
    os.environ.setdefault("MODEL_ROUTING", "{}")

    # Create local_run directories
    for name in ["researcher", "judge", "content_builder", "orchestrator"]:
        (ROOT_DIR / "local_run" / name).mkdir(parents=True, exist_ok=True)

    py_exe = sys.executable
    processes = []

    def cleanup(signum=None, frame=None):
        print("\nStopping all services...")
        for p in processes:
            try:
                p.terminate()
            except Exception:
                pass
        for p in processes:
            try:
                p.wait(timeout=3)
            except Exception:
                p.kill()
        print("All services stopped.")
        sys.exit(0)

    signal.signal(signal.SIGINT, cleanup)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, cleanup)

    services = [
        ("Researcher (8001)", ROOT_DIR / "agents" / "researcher", [py_exe, "adk_app.py", "--host", "0.0.0.0", "--port", "8001", "--a2a", "../../local_run/researcher"]),
        ("Judge (8002)", ROOT_DIR / "agents" / "judge", [py_exe, "adk_app.py", "--host", "0.0.0.0", "--port", "8002", "--a2a", "../../local_run/judge"]),
        ("Content Builder (8003)", ROOT_DIR / "agents" / "content_builder", [py_exe, "adk_app.py", "--host", "0.0.0.0", "--port", "8003", "--a2a", "../../local_run/content_builder"]),
        ("Orchestrator (8004)", ROOT_DIR / "agents" / "orchestrator", [py_exe, "adk_app.py", "--host", "0.0.0.0", "--port", "8004", "../../local_run/orchestrator"]),
    ]

    print("=========================================================")
    print("  Starting Multi-Agent Course Creation System (Local)    ")
    print("=========================================================")

    for name, cwd, cmd in services:
        print(f"Starting {name}...")
        p = subprocess.Popen(cmd, cwd=str(cwd), env=os.environ.copy())
        processes.append(p)

    print("Waiting 4s for agents to initialize...")
    time.sleep(4)

    # Re-create agent folders to satisfy ADK AgentLoader check
    for name in ["researcher", "judge", "content_builder", "orchestrator"]:
        (ROOT_DIR / "local_run" / name / "agent").mkdir(parents=True, exist_ok=True)
    time.sleep(2)

    # Start Frontend App
    frontend_port = os.environ.get("FRONTEND_PORT", "8080")
    print(f"Starting Web App Frontend on port {frontend_port}...")
    frontend_cmd = [py_exe, "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", str(frontend_port)]
    p_front = subprocess.Popen(frontend_cmd, cwd=str(ROOT_DIR / "app"), env=os.environ.copy())
    processes.append(p_front)

    print("\n---------------------------------------------------------")
    print("All services are running:")
    print(" - Researcher Agent:     http://localhost:8001")
    print(" - Judge Agent:          http://localhost:8002")
    print(" - Content Builder:      http://localhost:8003")
    print(" - Orchestrator Agent:   http://localhost:8004")
    print(f" - Web App UI:           http://localhost:{frontend_port}")
    print("---------------------------------------------------------")
    print("Open http://localhost:8080 in your browser.")
    print("Press Ctrl+C to terminate all services.\n")

    try:
        while True:
            for p in processes:
                code = p.poll()
                if code is not None:
                    print(f"Process exited with code {code}.")
                    cleanup()
            time.sleep(1)
    except KeyboardInterrupt:
        cleanup()

if __name__ == "__main__":
    main()
