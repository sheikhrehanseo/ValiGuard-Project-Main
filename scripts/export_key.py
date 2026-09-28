
import subprocess
import time

def export_key():
    backends = ["test", "os", "file"]
    for backend in backends:
        print(f"Attempting export with backend: {backend}")
        cmd = f"wsl bash -c \"~/.qie/qied keys export validator --home ~/.qieMainnetNode --keyring-backend {backend}\""
        
        process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            shell=True
        )

        try:
            # Send password 'Shin@123' multiple times blindly
            time.sleep(1)
            process.stdin.write("Shin@123\n") 
            process.stdin.flush()
            
            time.sleep(1)
            process.stdin.write("Shin@123\n")
            process.stdin.flush()
            
            time.sleep(1)
            process.stdin.write("Shin@123\n")
            process.stdin.flush()

            stdout, stderr = process.communicate(timeout=10)
            output = stdout + stderr

            if "BEGIN TENDERMINT PRIVATE KEY" in output:
                print(f"KEY_FOUND_ARMOR_BACKEND_{backend}")
                print(output)
                return # Success
            else:
                print(f"Failed with backend {backend}: {output[:200]}...") # Print snippet
                
        except Exception as e:
            print(f"Error with backend {backend}: {e}")

if __name__ == "__main__":
    export_key()
