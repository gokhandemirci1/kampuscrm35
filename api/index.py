# Vercel serverless function entry point
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Initialize database on first import
try:
    from api.database import init_db
    init_db()
except Exception as e:
    print(f"Warning: Database initialization failed: {e}")

from api.main import app

# For Vercel deployment
# The app is the ASGI application

