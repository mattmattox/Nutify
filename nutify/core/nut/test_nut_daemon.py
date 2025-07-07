#!/usr/bin/env python3
"""
Test script for the NUT daemon module.
This script tests the functionality of the NUT daemon module by starting, checking status, and stopping NUT services.

Usage:
    python3 test_nut_daemon.py
"""

import sys
import os
import time
import json

# Add parent directory to path so we can import our module
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

# Configure logging
import logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('test_nut_daemon')

def main():
    """Main test function"""
    try:
        # Import modules
        logger.info("Importing NUT daemon module...")
        from nutify.core.nut import (
            start_nut_services, 
            stop_nut_services, 
            restart_nut_services, 
            check_all_services_status,
            get_service_logs,
            NUTDaemonError
        )
        
        # Check current status
        logger.info("Checking current NUT services status...")
        status = check_all_services_status()
        logger.info(f"Current status: {json.dumps(status, indent=2)}")
        
        # If services are running, stop them first
        if any(status.values()):
            logger.info("Stopping any running NUT services...")
            stop_results = stop_nut_services()
            logger.info(f"Stop results: {json.dumps(stop_results, indent=2)}")
            time.sleep(2)  # Wait for services to stop
        
        # Start services
        logger.info("Starting NUT services...")
        try:
            start_results = start_nut_services()
            logger.info(f"Start results: {json.dumps(start_results, indent=2)}")
        except NUTDaemonError as e:
            logger.error(f"Error starting NUT services: {str(e)}")
            return 1
            
        # Check status again
        time.sleep(2)  # Wait for services to start
        logger.info("Checking updated NUT services status...")
        status = check_all_services_status()
        logger.info(f"Updated status: {json.dumps(status, indent=2)}")
        
        # Get logs
        for service in ['upsdrvctl', 'upsd', 'upsmon']:
            logger.info(f"Getting logs for {service}...")
            logs = get_service_logs(service, lines=10)
            logger.info(f"{service} logs (last 10 lines):\n{logs}")
            
        # Restart services
        logger.info("Restarting NUT services...")
        restart_results = restart_nut_services()
        logger.info(f"Restart results: {json.dumps(restart_results, indent=2)}")
        
        # Final status check
        time.sleep(2)  # Wait for services to restart
        logger.info("Checking final NUT services status...")
        status = check_all_services_status()
        logger.info(f"Final status: {json.dumps(status, indent=2)}")
        
        logger.info("Test completed successfully!")
        return 0
        
    except ImportError as e:
        logger.error(f"Failed to import required modules: {str(e)}")
        return 1
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        return 1

if __name__ == "__main__":
    sys.exit(main()) 