#!/usr/bin/env python3
"""
Van Sales V3 ERP System - Run Script
"""

from app import create_app

app = create_app()

if __name__ == '__main__':
    print("=" * 55)
    print("  Van Sales V3 ERP System")
    print("  Starting on http://127.0.0.1:5000")
    print("  Default Login: admin / admin123")
    print("=" * 55)
    app.run(debug=True, host='0.0.0.0', port=5000)
