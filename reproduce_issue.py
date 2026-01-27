import os
import shutil
import subprocess
import sys
from pathlib import Path

def setup_test_dir():
    test_dir = Path("./test_resume_issue")
    if test_dir.exists():
        shutil.rmtree(test_dir)
    test_dir.mkdir()
    
    # Create a dummy PDF
    (test_dir / "dummy.pdf").touch()
    
    return test_dir

def test_resume_on_fresh_dir():
    test_dir = setup_test_dir()
    print(f"Testing in {test_dir.absolute()}")
    
    # Construct command
    # python -m citation_snowball.cli.app run [DIR] -r --no-download --no-export
    cmd = [
        sys.executable, "-m", "citation_snowball.cli.app", 
        "run", str(test_dir), 
        "--resume", 
        "--no-download", 
        "--no-export"
    ]
    
    print(f"Running: {' '.join(cmd)}")
    
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=os.getcwd(),
        env={**os.environ, "PYTHONPATH": "src"} 
    )
    
    print("\n--- STDOUT ---")
    print(result.stdout)
    print("\n--- STDERR ---")
    print(result.stderr)
    
    print(f"\nExit code: {result.returncode}")

if __name__ == "__main__":
    test_resume_on_fresh_dir()
