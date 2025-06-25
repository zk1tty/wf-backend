#!/usr/bin/env python3
"""
rrweb Demo Startup Script

Simple script to launch the rrweb visual streaming demo with proper path handling.
"""

import os
import sys
import subprocess
from pathlib import Path

def main():
    """Launch the rrweb demo server"""
    
    # Get the current script directory
    script_dir = Path(__file__).parent
    backend_dir = script_dir / "backend"
    demo_backend = backend_dir / "demo_backend.py"
    
    # Check if demo_backend.py exists
    if not demo_backend.exists():
        print("❌ Error: demo_backend.py not found!")
        print(f"   Expected location: {demo_backend}")
        print("   Make sure you're running this from the rrweb_demo directory")
        sys.exit(1)
    
    # Add the parent directory to Python path for imports
    parent_dir = script_dir.parent
    if str(parent_dir) not in sys.path:
        sys.path.insert(0, str(parent_dir))
    
    print("🚀 Starting rrweb Visual Streaming Demo")
    print("=" * 50)
    print(f"📁 Demo directory: {script_dir}")
    print(f"🔧 Backend script: {demo_backend}")
    print(f"🌐 Server will start on: http://localhost:8000")
    print(f"📱 Demo viewer: http://localhost:8000")
    print("=" * 50)
    print()
    
    try:
        # Change to backend directory and run the demo
        os.chdir(backend_dir)
        
        # Set PYTHONPATH to include the parent directories
        env = os.environ.copy()
        env['PYTHONPATH'] = str(parent_dir) + os.pathsep + env.get('PYTHONPATH', '')
        
        # Run the demo backend
        subprocess.run([sys.executable, "demo_backend.py"], env=env)
        
    except KeyboardInterrupt:
        print("\n🛑 Demo stopped by user")
    except Exception as e:
        print(f"❌ Error starting demo: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main() 