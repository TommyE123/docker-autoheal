#!/usr/bin/env python3
"""
Demo script for Docker Auto-Heal Service
Tests various features and demonstrates functionality
"""

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

BASE_URL = "http://localhost:3131"
API_URL = f"{BASE_URL}/api"


def print_header(text):
    """Print a formatted header"""
    print("\n" + "=" * 60)
    print(f"  {text}")
    print("=" * 60)


def check_service_health():
    """Check if the service is running and healthy"""
    print_header("Checking Service Health")
    try:
        response = requests.get(f"{BASE_URL}/health", timeout=5)
        if response.status_code == 200:
            data = response.json()
            print(f"✅ Service is healthy")
            print(f"   Status: {data['status']}")
            print(f"   Docker Connected: {data['docker_connected']}")
            print(f"   Monitoring Active: {data['monitoring_active']}")
            return True
        print(f"❌ Service returned status code: {response.status_code}")
        return False
    except Exception as e:
        print(f"❌ Cannot connect to service: {e}")
        print(f"   Make sure the service is running on {BASE_URL}")
        return False


def get_system_status():
    """Get and display system status"""
    print_header("System Status")
    try:
        response = requests.get(f"{API_URL}/status")
        data = response.json()

        print(f"Total Containers: {data['total_containers']}")
        print(f"Monitored Containers: {data['monitored_containers']}")
        print(f"Quarantined Containers: {data['quarantined_containers']}")
        print(f"Monitoring Active: {data['monitoring_active']}")
        print(f"Docker Connected: {data['docker_connected']}")

        return data
    except Exception as e:
        print(f"❌ Error getting status: {e}")
        return None


def list_containers():
    """List all containers"""
    print_header("Container List")
    try:
        response = requests.get(f"{API_URL}/containers")
        containers = response.json()

        if not containers:
            print("No containers found")
            return []

        print(f"Found {len(containers)} container(s):\n")

        for i, container in enumerate(containers, 1):
            print(f"{i}. {container['name']}")
            print(f"   ID: {container['id']}")
            print(f"   Image: {container['image']}")
            print(f"   Status: {container['status']}")
            print(f"   Monitored: {'✅' if container['monitored'] else '❌'}")
            print(f"   Quarantined: {'⚠️' if container['quarantined'] else '✅'}")

            if container.get('health'):
                print(f"   Health: {container['health'].get('status', 'N/A')}")
            print()

        return containers
    except Exception as e:
        print(f"❌ Error listing containers: {e}")
        return []


def get_current_config():
    """Get and display current configuration"""
    print_header("Current Configuration")
    try:
        response = requests.get(f"{API_URL}/config")
        config = response.json()

        print("Monitor Settings:")
        print(f"  Interval: {config['monitor']['interval_seconds']}s")
        print(f"  Label Filter: {config['monitor']['label_key']}={config['monitor']['label_value']}")
        print(f"  Include All: {config['monitor']['include_all']}")

        print("\nRestart Policy:")
        print(f"  Mode: {config['restart']['mode']}")
        print(f"  Cooldown: {config['restart']['cooldown_seconds']}s")
        print(f"  Max Restarts: {config['restart']['max_restarts']}")
        print(f"  Window: {config['restart']['max_restarts_window_seconds']}s")
        print(f"  Backoff Enabled: {config['restart']['backoff']['enabled']}")

        return config
    except Exception as e:
        print(f"❌ Error getting config: {e}")
        return None


def view_events():
    """View recent events"""
    print_header("Recent Events")
    try:
        response = requests.get(f"{API_URL}/events?limit=10")
        events = response.json()

        if not events:
            print("No events recorded yet")
            return

        print(f"Last {len(events)} event(s):\n")

        for event in reversed(events):
            timestamp = datetime.fromisoformat(event['timestamp'].replace('Z', '+00:00'))
            print(f"[{timestamp.strftime('%Y-%m-%d %H:%M:%S')}] {event['event_type'].upper()}")
            print(f"  Container: {event['container_name']}")
            print(f"  Status: {event['status']}")
            print(f"  Restart Count: {event['restart_count']}")
            print(f"  Message: {event['message']}")
            print()
    except Exception as e:
        print(f"❌ Error getting events: {e}")


def enable_autoheal_for_container(container_id):
    """Enable auto-heal for a specific container"""
    print_header(f"Enabling Auto-Heal for Container {container_id}")
    try:
        response = requests.post(
            f"{API_URL}/containers/select",
            json={
                "container_ids": [container_id],
                "enabled": True
            }
        )

        if response.status_code == 200:
            print(f"✅ Auto-heal enabled for container {container_id}")
            return True
        print(f"❌ Failed to enable auto-heal: {response.status_code}")
        return False
    except Exception as e:
        print(f"❌ Error enabling auto-heal: {e}")
        return False


def add_http_health_check(container_id, endpoint, expected_status=200):
    """Add HTTP health check for a container"""
    print_header(f"Adding HTTP Health Check for {container_id}")
    try:
        response = requests.post(
            f"{API_URL}/healthchecks",
            json={
                "container_id": container_id,
                "check_type": "http",
                "http_endpoint": endpoint,
                "http_expected_status": expected_status,
                "interval_seconds": 30,
                "timeout_seconds": 10,
                "retries": 3
            }
        )

        if response.status_code == 200:
            print(f"✅ HTTP health check added")
            print(f"   Endpoint: {endpoint}")
            print(f"   Expected Status: {expected_status}")
            return True
        print(f"❌ Failed to add health check: {response.status_code}")
        return False
    except Exception as e:
        print(f"❌ Error adding health check: {e}")
        return False


def export_config():
    """Export configuration to file"""
    print_header("Exporting Configuration")
    try:
        response = requests.get(f"{API_URL}/config/export")

        if response.status_code == 200:
            filename = f"config-backup-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.json"
            with Path(filename).open('w') as f:
                json.dump(response.json(), f, indent=2)

            print(f"✅ Configuration exported to {filename}")
            return filename
        print(f"❌ Failed to export config: {response.status_code}")
        return None
    except Exception as e:
        print(f"❌ Error exporting config: {e}")
        return None


def run_interactive_demo():
    """Run interactive demo"""
    print("\n" + "=" * 60)
    print("  Docker Auto-Heal Service - Interactive Demo")
    print("=" * 60)

    # Check service health
    if not check_service_health():
        print("\n⚠️  Service is not accessible. Please start it first:")
        print("   docker-compose up -d")
        return

    time.sleep(1)

    # Get system status
    get_system_status()
    time.sleep(1)

    # List containers
    containers = list_containers()
    time.sleep(1)

    # Show current config
    get_current_config()
    time.sleep(1)

    # View events
    view_events()
    time.sleep(1)

    # Interactive menu
    while True:
        print("\n" + "=" * 60)
        print("  Options:")
        print("=" * 60)
        print("1. Refresh container list")
        print("2. View system status")
        print("3. View events")
        print("4. Enable auto-heal for a container")
        print("5. Add HTTP health check")
        print("6. Export configuration")
        print("7. View configuration")
        print("8. Open Web UI in browser")
        print("9. Exit")
        print()

        choice = input("Enter your choice (1-9): ").strip()

        if choice == '1':
            list_containers()
        elif choice == '2':
            get_system_status()
        elif choice == '3':
            view_events()
        elif choice == '4':
            container_id = input("Enter container ID or name: ").strip()
            if container_id:
                enable_autoheal_for_container(container_id)
        elif choice == '5':
            container_id = input("Enter container ID or name: ").strip()
            endpoint = input("Enter HTTP endpoint (e.g., http://localhost:3131/health): ").strip()
            if container_id and endpoint:
                add_http_health_check(container_id, endpoint)
        elif choice == '6':
            export_config()
        elif choice == '7':
            get_current_config()
        elif choice == '8':
            import webbrowser
            print(f"Opening {BASE_URL} in browser...")
            webbrowser.open(BASE_URL)
        elif choice == '9':
            print("\n👋 Goodbye!")
            break
        else:
            print("❌ Invalid choice. Please try again.")

        time.sleep(1)


def run_automated_demo():
    """Run automated demo without user interaction"""
    print("\n" + "=" * 60)
    print("  Docker Auto-Heal Service - Automated Demo")
    print("=" * 60)

    steps = [
        ("Checking service health", check_service_health),
        ("Getting system status", get_system_status),
        ("Listing containers", list_containers),
        ("Viewing current configuration", get_current_config),
        ("Viewing recent events", view_events),
        ("Exporting configuration", export_config),
    ]

    for step_name, step_func in steps:
        print(f"\n▶️  {step_name}...")
        time.sleep(1)
        step_func()
        time.sleep(2)

    print("\n" + "=" * 60)
    print("  Demo Complete!")
    print("=" * 60)
    print(f"\n🌐 Web UI: {BASE_URL}")
    print(f"📚 API Docs: {BASE_URL}/docs")
    print(f"📊 Metrics: http://localhost:9090/metrics")
    print("\nFor interactive mode, run: python demo.py --interactive")


if __name__ == "__main__":
    import sys

    if "--interactive" in sys.argv or "-i" in sys.argv:
        run_interactive_demo()
    else:
        run_automated_demo()

        print("\n💡 Tip: Run with --interactive for an interactive demo")

