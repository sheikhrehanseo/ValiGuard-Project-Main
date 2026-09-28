
import subprocess
import os
import sys
import threading
import time
import webbrowser

def start_backend():
    print("[*] Starting Backend (Flask)...")
    # Activate venv and run app.py
    # Assuming venv is in current directory
    if sys.platform == "win32":
        python_exe = r"venv\Scripts\python.exe"
    else:
        python_exe = "venv/bin/python"
    
    if not os.path.exists(python_exe):
        print(f"[!] Virtual environment not found at {python_exe}. Using system python.")
        python_exe = sys.executable

    cmd = [python_exe, "-m", "backend.app"]
    try:
        subprocess.run(cmd, check=True)
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"[x] Backend failed: {e}")

def start_frontend_server():
    print("[*] Starting Frontend (Next.js)...")
    # Run npm run dev in the frontend directory
    # On Windows, need shell=True for npm, or use npm.cmd
    npm_cmd = "npm.cmd" if sys.platform == "win32" else "npm"
    cmd = [npm_cmd, "run", "dev"]
    try:
        subprocess.run(cmd, cwd="frontend", check=True)
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"[x] Frontend server failed: {e}")
        print("Tip: Run 'npm install' in the frontend directory if you haven't yet.")

def start_simulator():
    print("[*] Starting Traffic Simulator (demo mode — no QIE node needed)...")
    if sys.platform == "win32":
        python_exe = r"venv\Scripts\python.exe"
    else:
        python_exe = "venv/bin/python"
    if not os.path.exists(python_exe):
        python_exe = sys.executable

    cmd = [python_exe, "scripts/generate_mock_traffic.py",
           "--rate", "20", "--scenario", "mix"]
    try:
        subprocess.run(cmd, check=True)
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"[x] Simulator failed: {e}")

def main():
    print("==================================================")
    print("ValiGuard AI - Local Launcher")
    print("==================================================")
    print("Starting services...")

    run_simulator = "--simulate" in sys.argv
    
    # Check if Nginx is requested/available, otherwise use Python HTTP server for frontend
    # User asked for Nginx config but running it on Windows requires Nginx executable.
    # We provided config, but will run Python server for immediate 'localhost' access.
    
    t_backend = threading.Thread(target=start_backend)
    t_backend.daemon = True
    t_backend.start()
    
    time.sleep(2) # Wait for backend to init
    
    t_frontend = threading.Thread(target=start_frontend_server)
    t_frontend.daemon = True
    t_frontend.start()

    if run_simulator:
        time.sleep(4)  # let the API come up before sending traffic
        t_sim = threading.Thread(target=start_simulator)
        t_sim.daemon = True
        t_sim.start()
        print("[+] Traffic simulator running (mix scenarios).")
    else:
        print("[i] Tip: run 'python start_project.py --simulate' to feed demo traffic.")
    
    print("\n[+] Services started!")
    print("   - Backend API: http://localhost:5000")
    print("   - Frontend UI: http://localhost:3001 (Next.js)")
    print("\n[!] NOTE: Nginx configs created in /nginx/ for deployment.")
    print("   Running built-in servers for local testing now.")
    print("==================================================")
    
    time.sleep(5) # Give Next.js more time to boot
    webbrowser.open("http://localhost:3001")
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[*] Stopping services...")

if __name__ == "__main__":
    main()
