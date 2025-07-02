#!/usr/bin/env python3
"""
Build script for cellar-extractor package.
Usage:
    python build.py build    # Build the package
    python build.py upload   # Upload to PyPI (requires authentication)
"""
import subprocess
import sys
import os
from pathlib import Path

def run_command(cmd, description=""):
    """Run a shell command and handle errors."""
    print(f"Running: {cmd}")
    if description:
        print(f"Description: {description}")
    
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    
    if result.returncode != 0:
        print(f"Error running command: {cmd}")
        print(f"Error output: {result.stderr}")
        sys.exit(1)
    
    print(f"Success: {result.stdout}")
    return result.stdout

def clean_build():
    """Clean previous build artifacts."""
    print("Cleaning previous build artifacts...")
    paths_to_clean = ["build", "dist", "*.egg-info"]
    for path in paths_to_clean:
        run_command(f"rm -rf {path}", f"Removing {path}")

def build_package():
    """Build the package."""
    print("Building package...")
    run_command("python -m build", "Building wheel and source distribution")

def upload_package():
    """Upload package to PyPI."""
    print("Uploading package to PyPI...")
    print("Note: This requires proper PyPI authentication (API token or credentials)")
    run_command("python -m twine upload dist/*", "Uploading to PyPI")

def main():
    if len(sys.argv) != 2:
        print("Usage: python build.py [build|upload]")
        sys.exit(1)
    
    command = sys.argv[1].lower()
    
    # Ensure we're in the project root
    project_root = Path(__file__).parent
    os.chdir(project_root)
    
    if command == "build":
        clean_build()
        build_package()
        print("\nBuild complete! Check the 'dist' directory for built packages.")
        print("To install locally, run: pip install dist/cellar_extractor-*.whl")
        
    elif command == "upload":
        if not Path("dist").exists():
            print("No dist directory found. Building first...")
            clean_build()
            build_package()
        upload_package()
        print("\nUpload complete!")
        
    else:
        print(f"Unknown command: {command}")
        print("Available commands: build, upload")
        sys.exit(1)

if __name__ == "__main__":
    main()
