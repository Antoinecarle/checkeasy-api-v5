#!/usr/bin/env python3
"""
Test script for VERSION environment variable detection
Tests the mapping of VERSION (live/test) to environment (production/staging)
"""

import os
import sys

def test_version_detection():
    """Test the VERSION variable detection"""
    
    test_cases = [
        ("live", "production"),
        ("test", "staging"),
        ("", "staging"),  # Default fallback
    ]
    
    print("=" * 80)
    print("Testing VERSION environment variable detection")
    print("=" * 80)
    print()
    
    for version_value, expected_env in test_cases:
        # Set the VERSION variable
        os.environ['VERSION'] = version_value
        
        # Import after setting the variable
        # Note: In real usage, this is set before the app starts
        from make_request import detect_environment, get_webhook_url, get_bubble_debug_endpoint
        
        # Test detection
        detected_env = detect_environment()
        webhook_url = get_webhook_url(detected_env)
        debug_endpoint = get_bubble_debug_endpoint(detected_env)
        
        # Verify
        status = "✅ PASS" if detected_env == expected_env else "❌ FAIL"
        
        print(f"{status} | VERSION='{version_value}'")
        print(f"       Expected: {expected_env}, Got: {detected_env}")
        print(f"       Webhook URL: {webhook_url}")
        print(f"       Debug endpoint: {debug_endpoint}")
        print()
        
        # Reload the module for next test
        if 'make_request' in sys.modules:
            del sys.modules['make_request']

if __name__ == "__main__":
    test_version_detection()

