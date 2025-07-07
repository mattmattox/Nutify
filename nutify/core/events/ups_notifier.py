#!/usr/bin/env python3
"""
UPS Notifier Script

This script is designed to be called directly by upsmon.conf via the NOTIFYCMD directive.
It replaces the previous notifier.sh + socket communication approach with direct integration.

Usage:
  Called by upsmon with the UPS name and event type:
  /app/nutify/core/events/ups_notifier.py ups@hostname ONBATT
  - or -
  /app/nutify/core/events/ups_notifier.py "UPS ups@localhost on battery"

The script will:
1. Parse the input to determine UPS name and event type
2. Check database for enabled notifications for this event type
3. Send email notifications using the appropriate templates
4. Store the event in the database
5. Update the UI via event recording
"""

# Apply eventlet monkey patching at the very beginning
try:
    import eventlet
    eventlet.monkey_patch()
    print("Eventlet monkey patching applied")
except ImportError:
    print("Warning: Eventlet not available, monkey patching skipped")

import os
import sys
import re
import logging
import datetime
import traceback
from pathlib import Path
import platform
import pytz
import sqlite3
import jinja2
from sqlalchemy import text, inspect
import json

# Add the application directory to sys.path to allow imports
APP_DIR = str(Path(__file__).resolve().parent.parent.parent)
if APP_DIR not in sys.path:
    sys.path.append(APP_DIR)

# Get SECRET_KEY from environment before any imports
SECRET_KEY = os.environ.get('SECRET_KEY')
# Ensure it's set in os.environ to make it available for all modules
if SECRET_KEY:
    os.environ['SECRET_KEY'] = SECRET_KEY

# Configure logging paths 
LOG_FILE = "/var/log/nut/notifier.log"
DEBUG_LOG = "/var/log/nut-debug.log"

# Create log directory if it doesn't exist
if not os.path.exists(os.path.dirname(LOG_FILE)):
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

# Setup basic logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# Setup file handlers
file_handler = logging.FileHandler(LOG_FILE)
debug_handler = logging.FileHandler(DEBUG_LOG)

# Create logger
logger = logging.getLogger("ups_notifier")
logger.addHandler(file_handler)
logger.addHandler(debug_handler)

# Now validate the SECRET_KEY after logger is set up
if not SECRET_KEY:
    logger.error("ERROR: SECRET_KEY not found in environment. This is required for encryption.")
    sys.exit(1)
else:
    logger.info(f"Using SECRET_KEY from environment (first 5 chars: {SECRET_KEY[:5]}...)")

# Database path
DB_PATH = os.path.join(APP_DIR, "instance", "nutify.db.sqlite")

# Import app modules after logging is set up
try:
    # Import the main app module to get CACHE_TIMEZONE
    from app import CACHE_TIMEZONE

    # Import the existing email system
    from core import create_app
    from core.mail.mail import EmailNotifier
    from core.db.ups import db, UPSEvent
    from core.logger import mail_logger as logger, database_logger

    # Import ntfy notification system
    try:
        from core.extranotifs.ntfy import NtfyNotifier
        from core.extranotifs.ntfy.db import get_ntfy_model, get_default_config
        HAS_NTFY = True
    except ImportError:
        logger.warning("Ntfy notification module not available")
        HAS_NTFY = False

    # Import webhook notification system
    try:
        from core.extranotifs.webhook import WebhookNotifier
        from core.extranotifs.webhook.webhook import send_event_notification as send_webhook_notification
        HAS_WEBHOOK = True
    except ImportError:
        logger.warning("Webhook notification module not available")
        HAS_WEBHOOK = False

    from core.db.ups.models import get_ups_model, get_static_model
    from core.db.orm.orm_ups_events import init_model as init_event_model
    from core.db.orm.orm_ups_opt_notification import init_model as init_notification_model
    from core.db.ups.utils import ups_config
    from core.db.model_classes import init_model_classes, register_models_for_global_access
    from core.mail import get_mail_config_model, get_notification_settings_model

    # Initialize Flask app
    app = create_app()

    # Set SECRET_KEY directly in app.config
    app.config['SECRET_KEY'] = SECRET_KEY
    logger.info(f"Set SECRET_KEY in app.config from environment (first 5 chars: {SECRET_KEY[:5]}...)")

    # Set global CACHE_TIMEZONE from app module
    app.CACHE_TIMEZONE = CACHE_TIMEZONE
    logger.info(f"Set app.CACHE_TIMEZONE from global module: {CACHE_TIMEZONE.zone}")

    # Initialize the report manager with the custom timezone to prevent errors
    from core.report.report import report_manager
    with app.app_context():
        # Manually set the timezone on report_manager
        report_manager.tz = CACHE_TIMEZONE
        logger.info(f"Manually initialized report_manager.tz with timezone: {CACHE_TIMEZONE.zone}")

    # Set template path for this script
    app.template_folder = os.path.join(APP_DIR, 'templates')
except Exception as e:
    logger.critical(f"Failed to initialize application modules: {str(e)}")
    logger.critical(traceback.format_exc())
    sys.exit(1)

def log_message(message, is_debug=False):
    """Log a message to both log files"""
    if is_debug:
        logger.debug(message)
    else:
        logger.info(message)
    
    # Ensure it's written to disk immediately
    for handler in logger.handlers:
        handler.flush()
    
    # Also write to a separate dedicated notifier log file for better debugging
    try:
        with open("/var/log/nut/notifier.log", "a") as f:
            # Use timezone from cache for timestamp
            timestamp = datetime.datetime.now(app.CACHE_TIMEZONE).strftime("%Y-%m-%d %H:%M:%S")
            f.write(f"[{timestamp}] {message}\n")
            f.flush()
    except Exception as e:
        # Don't fail if we can't write to this file
        pass

# Initialize models in app context
with app.app_context():
    # Check if models are already initialized to prevent duplicate registrations
    if hasattr(db, 'ModelClasses'):
        log_message("📚 Models already initialized, using existing models", True)
        model_classes = db.ModelClasses
    else:
        # Initialize model classes only if they haven't been initialized yet
        log_message("📚 Initializing models for the first time", True)
        model_classes = init_model_classes(db, lambda: app.CACHE_TIMEZONE)
        db.ModelClasses = model_classes
        
        # Register models for global access
        register_models_for_global_access(model_classes, db)
    
    # Use existing models from ModelClasses
    UPSEventModel = model_classes.UPSEvent
    NotificationSettingsModel = model_classes.NotificationSettings
    NtfyConfigModel = model_classes.NtfyConfig if hasattr(model_classes, 'NtfyConfig') else None
    
    # Get mail models
    MailConfigModel = model_classes.MailConfig
    
    # Initialize UPS configuration if needed
    if not ups_config.is_initialized():
        # Load from configuration files
        from core.db.nut_parser import get_ups_connection_params
        params = get_ups_connection_params()
        if params and 'host' in params and 'name' in params:
            ups_config.configure(
                host=params['host'],
                name=params['name'],
                command='upsc',
                timeout=10
            )
            log_message(f"UPS configuration loaded from configuration files: {params['host']}:{params['name']}")

def parse_input_args(args):
    """
    Parse the input arguments from upsmon.
    
    Args:
        args (list): Command-line arguments
        
    Returns:
        tuple: (ups_name, event_type)
    """
    log_message(f"DEBUG: Script started with args: {args}", True)
    
    if len(args) < 1:
        log_message("ERROR: No arguments provided")
        return None, None
    
    # === NON-STANDARD FORMATS ===
    # We need to check these first to avoid incorrect matches with the standard format
    if len(args) == 1:
        message = args[0]
        log_message(f"DEBUG: Processing single argument message: {message}", True)
        
        # === COMMUNICATION EVENTS ===
        # Handle "Communications with UPS ups@host lost" format
        if "Communications with UPS" in message and "lost" in message:
            log_message(f"DEBUG: Detected communication lost format", True)
            comm_lost_match = re.search(r"Communications with UPS ([^\s]+) lost", message)
            if comm_lost_match:
                ups_name = comm_lost_match.group(1)
                event_type = "COMMBAD"
                log_message(f"DEBUG: Detected COMMBAD event for {ups_name}", True)
                return ups_name, event_type
        
        # Handle "Communications restored with UPS ups@host" format
        if "Communications restored with UPS" in message:
            log_message(f"DEBUG: Detected communication restored format", True)
            comm_restored_match = re.search(r"Communications restored with UPS ([^\s]+)", message)
            if comm_restored_match:
                ups_name = comm_restored_match.group(1)
                event_type = "COMMOK"
                log_message(f"DEBUG: Detected COMMOK event for {ups_name}", True)
                return ups_name, event_type
        
        # Handle "No communication with UPS ups@host" format
        if "No communication with UPS" in message:
            log_message(f"DEBUG: Detected no communication format", True)
            nocomm_match = re.search(r"No communication with UPS ([^\s]+)", message)
            if nocomm_match:
                ups_name = nocomm_match.group(1)
                event_type = "NOCOMM"
                log_message(f"DEBUG: Detected NOCOMM event for {ups_name}", True)
                return ups_name, event_type
        
        # Handle "Parent process died - shutting down UPS ups@host" format
        if "Parent process died" in message:
            log_message(f"DEBUG: Detected parent process died format", True)
            noparent_match = re.search(r"Parent process died.*UPS ([^\s]+)", message)
            if noparent_match:
                ups_name = noparent_match.group(1)
                event_type = "NOPARENT"
                log_message(f"DEBUG: Detected NOPARENT event for {ups_name}", True)
                return ups_name, event_type
        
        # === SHUTDOWN EVENTS ===
        # Handle "System was shutdown by UPS ups@host" format
        if "System was shutdown by UPS" in message:
            log_message(f"DEBUG: Detected system shutdown format", True)
            shutdown_match = re.search(r"System was shutdown by UPS ([^\s]+)", message)
            if shutdown_match:
                ups_name = shutdown_match.group(1)
                event_type = "SHUTDOWN"
                log_message(f"DEBUG: Detected SHUTDOWN event for {ups_name}", True)
                return ups_name, event_type
        
        # === UPS STATUS EVENTS ===
        # Format: "UPS ups@host on battery" etc.
        if message.startswith("UPS "):
            ups_match = re.search(r"^UPS\s+([^\s]+)", message)
            if ups_match:
                ups_name = ups_match.group(1)
                log_message(f"DEBUG: Extracted UPS name from message: {ups_name}", True)
                
                # Now look for specific event types
                
                # ONBATT: UPS on battery power
                if "on battery" in message:
                    event_type = "ONBATT"
                    log_message(f"DEBUG: Detected ONBATT event for {ups_name}", True)
                    return ups_name, event_type
                
                # ONLINE: UPS on line power
                if "on line power" in message or "online" in message.lower():
                    event_type = "ONLINE"
                    log_message(f"DEBUG: Detected ONLINE event for {ups_name}", True)
                    return ups_name, event_type
                
                # LOWBATT: UPS battery is low
                if "low battery" in message:
                    event_type = "LOWBATT"
                    log_message(f"DEBUG: Detected LOWBATT event for {ups_name}", True)
                    return ups_name, event_type
                
                # FSD: Forced shutdown in progress
                if "forced shutdown" in message:
                    event_type = "FSD"
                    log_message(f"DEBUG: Detected FSD event for {ups_name}", True)
                    return ups_name, event_type
                
                # COMMOK: Communication restored
                if "communication restored" in message:
                    event_type = "COMMOK"
                    log_message(f"DEBUG: Detected COMMOK event for {ups_name}", True)
                    return ups_name, event_type
                
                # COMMBAD: Communication lost
                if "communication lost" in message:
                    event_type = "COMMBAD"
                    log_message(f"DEBUG: Detected COMMBAD event for {ups_name}", True)
                    return ups_name, event_type
                
                # SHUTDOWN: System shutdown in progress
                if "shutdown in progress" in message:
                    event_type = "SHUTDOWN"
                    log_message(f"DEBUG: Detected SHUTDOWN event for {ups_name}", True)
                    return ups_name, event_type
                
                # REPLBATT: Battery needs replacement
                if "battery needs replacing" in message or "needs battery replacement" in message:
                    event_type = "REPLBATT"
                    log_message(f"DEBUG: Detected REPLBATT event for {ups_name}", True)
                    return ups_name, event_type
                
                # NOCOMM: No communication with UPS
                if "no communication" in message:
                    event_type = "NOCOMM"
                    log_message(f"DEBUG: Detected NOCOMM event for {ups_name}", True)
                    return ups_name, event_type
                
                # NOPARENT: Parent process died
                if "parent process" in message:
                    event_type = "NOPARENT"
                    log_message(f"DEBUG: Detected NOPARENT event for {ups_name}", True)
                    return ups_name, event_type
    
        # Special case for standard format in a single argument (possibly from command shell)
        if " " in message and not message.startswith("UPS ") and not "Communications" in message and not "No communication" in message and not "Parent process" in message:
            parts = message.split(" ", 1)
            if len(parts) == 2:
                ups_name = parts[0]
                event_type = parts[1]
                log_message(f"DEBUG: Detected standard split format: {ups_name} {event_type}", True)
                return ups_name, event_type
    
    # === STANDARD FORMAT HANDLING ===
    # Standard direct format: ups@hostname EVENT_TYPE (the official NUT format)
    elif len(args) == 2:
        ups_name = args[0]
        event_type = args[1]
        log_message(f"DEBUG: Detected standard format: {ups_name} {event_type}", True)
        return ups_name, event_type
    
    # If we get here, format was not recognized
    log_message(f"ERROR: Unrecognized message format: {args}")
    return None, None

def get_enabled_notifications(event_type):
    """
    Check which notifications are enabled for this event type
    
    Args:
        event_type: Type of event (ONLINE, ONBATT, etc.)
        
    Returns:
        list: List of notification objects with their type and configuration
    """
    try:
        # Use ORM model to query enabled notifications
        notifications = NotificationSettingsModel.query.filter_by(
            enabled=True,
            event_type=event_type.upper()
        ).all()
        
        # Convert notifications to list of dictionaries with type and config
        result = []
        for notification in notifications:
            if notification.id_email is not None:
                result.append({
                    'type': 'email',
                    'config_id': notification.id_email
                })
        
        if not result:
            log_message(f"DEBUG: No enabled notifications found for {event_type}", True)
            return []
            
        return result
    except Exception as e:
        log_message(f"ERROR: Failed to get enabled notifications: {str(e)}")
        return []

def get_ups_info(ups_name):
    """
    Get UPS information from database
    
    Args:
        ups_name: Name of the UPS
        
    Returns:
        dict: UPS information or default values on error
    """
    try:
        log_message(f"DEBUG: Starting get_ups_info for {ups_name}", True)
        
        # Default UPS info with safe values
        ups_info = {
            'ups_model': 'Unknown UPS',
            'device_serial': 'Unknown',
            'ups_status': 'Unknown',
            'battery_charge': '0%',
            'runtime_estimate': '0 min',
            'input_voltage': '0V',
            'battery_voltage': '0V',
            'ups_host': ups_name,
            'battery_voltage_nominal': '0V',
            'battery_type': 'Unknown',
            'ups_timer_shutdown': '0',
            'comm_duration': '0 min',
            'battery_duration': '0 min',
            'battery_age': 'Unknown',
            'battery_efficiency': '0%'
        }
        
        # Get current date and time for the event
        now = datetime.datetime.now()
        local_tz = app.CACHE_TIMEZONE
        if local_tz:
            now = now.astimezone(local_tz)
        
        # Format date and time for the template
        ups_info['event_date'] = now.strftime('%Y-%m-%d')
        ups_info['event_time'] = now.strftime('%H:%M:%S')
        
        # Use ORM with dynamic SQL approach for maximum flexibility
        with app.app_context():
            try:
                # Get data using dynamic SQL through ORM
                log_message("DEBUG: Querying UPS data using dynamic ORM query", True)
                
                # First check if tables exist
                tables = inspect(db.engine).get_table_names()
                log_message(f"DEBUG: Available tables in database: {tables}", True)
                
                if 'ups_static_data' in tables:
                    # Use pure ORM approach to get the static data
                    from core.db.ups.models import get_static_model
                    UPSStaticData = get_static_model(db)
                    
                    # Get the first record using ORM
                    static_record = UPSStaticData.query.first()
                    log_message(f"DEBUG: Got static data record: {static_record}", True)
                    
                    if static_record:
                        # Convert ORM object to dictionary
                        static_data = {column.name: getattr(static_record, column.name) 
                                      for column in static_record.__table__.columns}
                        log_message(f"DEBUG: Static data retrieved: {static_data}", True)
                        
                        # Key fields we're interested in
                        for field in ['device_model', 'device_serial', 'battery_type', 'ups_model']:
                            if field in static_data and static_data[field] is not None:
                                ups_info[field] = str(static_data[field])
                                log_message(f"DEBUG: Set static value {field} = {ups_info[field]}", True)
                
                if 'ups_dynamic_data' in tables:
                    # Use pure ORM approach to get the dynamic data
                    from core.db.ups.models import get_ups_model
                    UPSDynamicData = get_ups_model(db)
                    
                    # Get the most recent record using ORM
                    dynamic_record = UPSDynamicData.query.order_by(UPSDynamicData.timestamp_utc.desc()).first()
                    log_message(f"DEBUG: Got dynamic data record: {dynamic_record}", True)
                    
                    if dynamic_record:
                        # Convert ORM object to dictionary
                        dynamic_data = {column.name: getattr(dynamic_record, column.name) 
                                       for column in dynamic_record.__table__.columns}
                        log_message(f"DEBUG: Dynamic data retrieved: {dynamic_data}", True)
                        
                        # Handle ups_status
                        if 'ups_status' in dynamic_data and dynamic_data['ups_status'] is not None:
                            ups_info['ups_status'] = str(dynamic_data['ups_status'])
                            log_message(f"DEBUG: Set dynamic value ups_status = {ups_info['ups_status']}", True)
                        
                        # Handle battery_charge
                        if 'battery_charge' in dynamic_data and dynamic_data['battery_charge'] is not None:
                            charge = str(dynamic_data['battery_charge'])
                            if not charge.endswith('%'):
                                charge = f"{charge}%"
                            ups_info['battery_charge'] = charge
                            log_message(f"DEBUG: Set dynamic value battery_charge = {ups_info['battery_charge']}", True)
                        
                        # Handle battery_runtime
                        if 'battery_runtime' in dynamic_data and dynamic_data['battery_runtime'] is not None:
                            runtime = str(dynamic_data['battery_runtime'])
                            if runtime.isdigit():
                                runtime_min = int(runtime) // 60
                                ups_info['runtime_estimate'] = f"{runtime_min} min"
                                log_message(f"DEBUG: Set dynamic value runtime_estimate = {ups_info['runtime_estimate']}", True)
                        
                        # Handle other voltage metrics with proper units
                        for field, suffix in [
                            ('input_voltage', 'V'),
                            ('battery_voltage', 'V'),
                            ('battery_voltage_nominal', 'V')
                        ]:
                            if field in dynamic_data and dynamic_data[field] is not None:
                                value = str(dynamic_data[field])
                                if not value.endswith(suffix):
                                    value = f"{value}{suffix}"
                                ups_info[field] = value
                                log_message(f"DEBUG: Set dynamic value {field} = {ups_info[field]}", True)
                        
                        # Handle ups_timer_shutdown
                        if 'ups_timer_shutdown' in dynamic_data and dynamic_data['ups_timer_shutdown'] is not None:
                            ups_info['ups_timer_shutdown'] = str(dynamic_data['ups_timer_shutdown'])
                            log_message(f"DEBUG: Set dynamic value ups_timer_shutdown = {ups_info['ups_timer_shutdown']}", True)
            except Exception as e:
                log_message(f"WARNING: Dynamic ORM query failed: {e}", True)
                log_message(f"TRACEBACK: {traceback.format_exc()}", True)
        
        log_message(f"DEBUG: Final UPS info: {ups_info}", True)
        return ups_info
    
    except Exception as e:
        log_message(f"ERROR: Failed to get UPS info: {e}")
        log_message(f"TRACEBACK: {traceback.format_exc()}", True)
        
        # Get current date and time even for default values
        now = datetime.datetime.now()
        local_tz = app.CACHE_TIMEZONE
        if local_tz:
            now = now.astimezone(local_tz)
            
        return {
            'ups_model': 'Unknown UPS',
            'device_serial': 'Unknown',
            'ups_status': 'Unknown',
            'battery_charge': '0%',
            'runtime_estimate': '0 min',
            'input_voltage': '0V',
            'battery_voltage': '0V',
            'ups_host': ups_name,
            'battery_voltage_nominal': '0V',
            'battery_type': 'Unknown',
            'ups_timer_shutdown': '0',
            'comm_duration': '0 min',
            'battery_duration': '0 min',
            'battery_age': 'Unknown',
            'battery_efficiency': '0%',
            'event_date': now.strftime('%Y-%m-%d'),
            'event_time': now.strftime('%H:%M:%S')
        }

def get_source_ip():
    """Get the source IP address based on configuration"""
    # First try to get from UPS config singleton
    if ups_config.is_initialized():
        return ups_config.host
        
    # Fallback to getting from database directly
    try:
        with app.app_context():
            nut_config = NtfyConfigModel.query.first()
            if nut_config:
                return nut_config.ups_host
    except Exception as e:
        log_message(f"Error getting UPS host from database: {e}", True)
    
    # Default to localhost
    return "127.0.0.1"

def close_previous_events(ups_name, current_time):
    """
    Close any open events for the specified UPS by setting their end timestamp.
    
    Args:
        ups_name: Name of the UPS
        current_time: Current timestamp to use as end time
        
    Returns:
        int: Number of events closed
    """
    try:
        # Find open events (where timestamp_utc_end is NULL)
        open_events = UPSEventModel.query.filter_by(
            ups_name=ups_name,
            timestamp_utc_end=None
        ).all()
        
        count = 0
        for event in open_events:
            event.timestamp_utc_end = current_time
            count += 1
            
        if count > 0:
            db.session.commit()
            log_message(f"Closed {count} previous events for {ups_name}")
            
        return count
    except Exception as e:
        log_message(f"ERROR: Failed to close previous events: {e}")
        return 0

def store_event_in_database(ups_name, event_type):
    """
    Store the event in the database
    
    Args:
        ups_name: Name of the UPS
        event_type: Type of event
        
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # Use UTC time for storing in database
        now = datetime.datetime.utcnow().replace(microsecond=0).replace(tzinfo=datetime.timezone.utc)
        
        # Close any previous events for this UPS
        close_previous_events(ups_name, now)
        
        # Get source IP
        source_ip = get_source_ip()
        
        # Create new event using ORM model
        event = UPSEventModel(
            timestamp_utc=now,
            timestamp_utc_begin=now,
            ups_name=ups_name,
            event_type=event_type,
            event_message=f"UPS {ups_name} event: {event_type}",
            source_ip=source_ip,
            acknowledged=False
        )
        
        db.session.add(event)
        db.session.commit()
        
        log_message(f"Stored {event_type} event for {ups_name} in database (UTC: {now.isoformat()})")
        return True
    
    except Exception as e:
        log_message(f"ERROR: Failed to store event in database: {e}")
        return False

def verify_email_config():
    """Verify that email configuration exists and is valid"""
    try:
        # Get the mail config model
        MailConfigModel = get_mail_config_model()
        if not MailConfigModel:
            logger.error("MailConfig model not available")
            return False
            
        # Check if we have any enabled email configurations
        config = MailConfigModel.query.filter_by(enabled=True).first()
        if not config:
            logger.info("No enabled email configuration found")
            return False
            
        logger.info(f"Email configuration verified: {config.provider} ({config.smtp_server})")
        return True
    except Exception as e:
        logger.error(f"Failed to verify email configuration: {str(e)}")
        return False

def send_email_notification(ups_name, event_type, notification):
    """
    Send an email notification
    
    Args:
        ups_name: Name of the UPS
        event_type: Type of event
        notification: Notification object with type and config_id
    """
    try:
        # Import get_timezone function as a lambda to get app.CACHE_TIMEZONE
        timezone_getter = lambda: app.CACHE_TIMEZONE
        
        log_message("📧 Preparing to send email notification", True)
        
        # Import get_encryption_key directly - we already set SECRET_KEY properly
        from core.mail.mail import get_encryption_key
        
        # Get UPS information
        ups_info = get_ups_info(ups_name)
        
        # Generate email subject based on event type
        event_subjects = {
            'ONLINE': f"✅ Power Restored - {ups_name}",
            'ONBATT': f"⚡ On Battery Power - {ups_name}",
            'LOWBATT': f"⚠️ CRITICAL: Low Battery - {ups_name}",
            'COMMBAD': f"❌ Communication Lost - {ups_name}",
            'COMMOK': f"✅ Communication Restored - {ups_name}",
            'SHUTDOWN': f"⚠️ CRITICAL: System Shutdown - {ups_name}",
            'REPLBATT': f"🔋 Battery Replacement Required - {ups_name}",
            'NOCOMM': f"❌ No Communication - {ups_name}",
            'NOPARENT': f"⚙️ Process Error - {ups_name}",
            'FSD': f"⚠️ CRITICAL: Forced Shutdown - {ups_name}"
        }
        
        subject = event_subjects.get(event_type, f"UPS Event: {event_type} - {ups_name}")
        
        # Initialize the email notifier
        log_message("DEBUG: Initializing EmailNotifier", True)
        notifier = EmailNotifier()
        
        # Get current date and time for the event
        now = datetime.datetime.now()
        local_tz = app.CACHE_TIMEZONE
        if local_tz:
            now = now.astimezone(local_tz)
        
        # Format date and time for the template
        event_date = now.strftime('%Y-%m-%d')
        event_time = now.strftime('%H:%M:%S')
        
        # Make sure battery charge has % symbol
        battery_charge = ups_info.get('battery_charge', '0')
        if not battery_charge.endswith('%'):
            battery_charge = f"{battery_charge}%"
            
        # Make sure voltage values have V suffix
        input_voltage = ups_info.get('input_voltage', '0')
        if not input_voltage.endswith('V'):
            input_voltage = f"{input_voltage}V"
            
        battery_voltage = ups_info.get('battery_voltage', '0')
        if not battery_voltage.endswith('V'):
            battery_voltage = f"{battery_voltage}V"
        
        # Make sure runtime has min suffix
        runtime_estimate = ups_info.get('runtime_estimate', '0')
        if not runtime_estimate.endswith('min'):
            runtime_estimate = f"{runtime_estimate} min"
        
        # Set battery_duration (for ONLINE notifications) - how long it was on battery
        battery_duration = ups_info.get('battery_duration', '0 min')
        if not battery_duration.endswith('min'):
            battery_duration = f"{battery_duration} min"
            
        # Set comm_duration (for COMMOK notifications) - how long it was without communication
        comm_duration = ups_info.get('comm_duration', '0 min')
        if not comm_duration.endswith('min'):
            comm_duration = f"{comm_duration} min"
            
        # Get the server_name ONLY from the database with no fallbacks
        server_name = None
        try:
            # Import required modules for direct ORM access
            from core.db.orm.orm_ups_initial_setup import init_model
            
            # Initialize the model with real logger, not timezone getter
            # Use existing logger instead of creating a new one
            InitialSetupModel = init_model(db.Model, logger)
            
            # Get server name directly from the model
            server_name = InitialSetupModel.get_server_name()
            log_message(f"DEBUG: Retrieved server name: {server_name} from database", True)
        except Exception as e:
            log_message(f"ERROR: Failed to get server name from database: {str(e)}", True)
            # Don't raise the exception, continue without server name
            server_name = "Unknown Server"
        
        # Prepare event data with properly formatted values
        event_data = {
            'ups_name': ups_name,
            'event_type': event_type,
            'subject': subject,
            'id_email': notification['config_id'],
            'event_date': event_date,
            'event_time': event_time,
            'battery_charge': battery_charge,
            'input_voltage': input_voltage, 
            'battery_voltage': battery_voltage,
            'runtime_estimate': runtime_estimate,
            'ups_model': ups_info.get('ups_model') or ups_info.get('device_model') or 'UPS Device',
            'ups_status': ups_info.get('ups_status', 'Unknown'),
            'device_serial': ups_info.get('device_serial', 'Unknown'),
            'battery_duration': battery_duration,
            'comm_duration': comm_duration,
            'battery_type': ups_info.get('battery_type', 'Unknown'),
            'ups_mfr': ups_info.get('ups_mfr', ''),
            'battery_voltage_nominal': ups_info.get('battery_voltage_nominal', '0V'),
            'device_location': ups_info.get('device_location', ''),
            'ups_firmware': ups_info.get('ups_firmware', ''),
            'ups_host': ups_name,
            'server_name': server_name
        }
        
        # Calculate additional fields if needed for specific event types
        if event_type == 'ONLINE':
            try:
                # Check if we have an open event that we can use to calculate duration
                with app.app_context():
                    # Look for open ONBATT events
                    open_event = UPSEventModel.query.filter_by(
                        ups_name=ups_name,
                        event_type='ONBATT',
                        timestamp_utc_end=None
                    ).order_by(UPSEventModel.timestamp_utc.desc()).first()
                    
                    if open_event and open_event.timestamp_utc:
                        # Calculate duration in minutes
                        duration_seconds = (now - open_event.timestamp_utc).total_seconds()
                        duration_minutes = int(duration_seconds / 60)
                        event_data['battery_duration'] = f"{duration_minutes} min"
                        log_message(f"DEBUG: Calculated battery_duration from open event: {event_data['battery_duration']}", True)
                    else:
                        # If there's no open event, find the most recent ONBATT event with an end time
                        closed_events = UPSEventModel.query.filter_by(
                            ups_name=ups_name,
                            event_type='ONBATT'
                        ).filter(UPSEventModel.timestamp_utc_end != None).order_by(UPSEventModel.timestamp_utc.desc()).limit(5).all()
                        
                        log_message(f"DEBUG: Found {len(closed_events)} closed ONBATT events", True)
                        
                        if closed_events:
                            # Find the most recent one that's likely to be related to this ONLINE event
                            for event in closed_events:
                                # Check if the event ended within the last hour
                                if event.timestamp_utc_end and (now - event.timestamp_utc_end).total_seconds() < 3600:
                                    if event.timestamp_utc:
                                        duration_seconds = (event.timestamp_utc_end - event.timestamp_utc).total_seconds()
                                        duration_minutes = int(duration_seconds / 60)
                                        event_data['battery_duration'] = f"{duration_minutes} min"
                                        log_message(f"DEBUG: Calculated battery_duration from closed event: {event_data['battery_duration']}", True)
                                        break
                        
                        # If we still don't have a duration, look at UPS statistics
                        if 'battery_duration' not in event_data or event_data['battery_duration'] == '0 min':
                            # Try to get it from known runtime stats
                            if 'device_uptime' in event_data and event_data['device_uptime'].isdigit():
                                # Use device uptime as a fallback (likely restart after power off)
                                uptime_min = int(event_data['device_uptime']) // 60
                                if uptime_min < 60:  # If uptime is less than 60 minutes, it's likely from a restart
                                    event_data['battery_duration'] = f"{uptime_min} min"
                                    log_message(f"DEBUG: Estimated battery_duration from device_uptime: {event_data['battery_duration']}", True)
            except Exception as e:
                log_message(f"WARNING: Could not calculate battery_duration: {e}", True)
                log_message(f"TRACEBACK: {traceback.format_exc()}", True)
        
        # Calculate communication outage duration for COMMOK events
        elif event_type == 'COMMOK':
            try:
                # For COMMOK events, try to estimate how long communication was lost
                # Check if we have an open event that we can use to calculate duration
                with app.app_context():
                    open_event = UPSEventModel.query.filter_by(
                        ups_name=ups_name,
                        event_type='COMMBAD',
                        timestamp_utc_end=None
                    ).order_by(UPSEventModel.timestamp_utc.desc()).first()
                    
                    if open_event and open_event.timestamp_utc:
                        # Calculate duration in minutes
                        duration_seconds = (now - open_event.timestamp_utc).total_seconds()
                        duration_minutes = int(duration_seconds / 60)
                        event_data['comm_duration'] = f"{duration_minutes} min"
                        log_message(f"DEBUG: Calculated comm_duration = {event_data['comm_duration']}", True)
            except Exception as e:
                log_message(f"WARNING: Could not calculate comm_duration: {e}", True)
                log_message(f"TRACEBACK: {traceback.format_exc()}", True)
        
        # Log the prepared event data
        log_message(f"DEBUG: Prepared event data for template: {event_data}", True)
        
        # Send notification using the existing email system
        log_message("DEBUG: Calling notifier.send_notification()", True)
        try:
            success, message = notifier.send_notification(event_type, event_data)
            
            log_message(f"DEBUG: Send notification result: success={success}, message={message}", True)
            
            if success:
                log_message(f"Sent {event_type} notification for {ups_name} using email config {notification['config_id']}")
            else:
                log_message(f"ERROR: Failed to send notification: {message}")
        except Exception as send_err:
            log_message(f"ERROR: Exception in notifier.send_notification(): {str(send_err)}", True)
            log_message(f"TRACEBACK: {traceback.format_exc()}", True)
            
    except Exception as e:
        log_message(f"ERROR: Failed to send notification: {str(e)}")
        log_message(f"TRACEBACK: {traceback.format_exc()}", True)

def get_enabled_ntfy_configs(event_type):
    """
    Check which Ntfy configurations are enabled for this event type
    
    Args:
        event_type (str): Type of event (ONLINE, ONBATT, etc.)
        
    Returns:
        list: List of Ntfy configurations
    """
    if not HAS_NTFY or not NtfyConfigModel:
        log_message("Ntfy module not available, skipping ntfy notifications", True)
        return []
        
    try:
        # Get the field name based on event type
        field_name = f"notify_{event_type.lower()}"
        
        # Query for configs that have this notification enabled
        with app.app_context():
            configs = NtfyConfigModel.query.filter(
                getattr(NtfyConfigModel, field_name) == True
            ).all()
            
            if configs:
                # Log details of each configuration
                log_message(f"Found {len(configs)} Ntfy configs for {event_type}:", True)
                for config in configs:
                    log_message(f"  - Config ID: {config.id}, Server: {config.server}, Topic: {config.topic}, Default: {config.is_default}", True)
                
                # Convert to dictionaries for use in send_ntfy_notification
                config_dicts = [config.to_dict() for config in configs]
                return config_dicts
            else:
                log_message(f"No enabled Ntfy configs found for {event_type}", True)
                return []
                
    except Exception as e:
        log_message(f"ERROR: Failed to get enabled Ntfy configs: {str(e)}")
        log_message(f"TRACEBACK: {traceback.format_exc()}", True)
        return []

def send_ntfy_notification(ups_name, event_type, config):
    """
    Send a notification via Ntfy with comprehensive UPS information
    
    Args:
        ups_name (str): Name of the UPS
        event_type (str): Type of event
        config (dict): Ntfy configuration
    """
    if not HAS_NTFY:
        log_message("Ntfy not available, skipping notification", True)
        return
        
    try:
        # Log which configuration is being used
        log_message(f"DEBUG: Sending Ntfy notification for {event_type} using config ID {config.get('id')} (server: {config.get('server')})", True)
        
        # Get UPS information for message content - more detailed retrieval
        ups_info = get_detailed_ups_info(ups_name)
        log_message(f"DEBUG: Ntfy received UPS info: {ups_info}", True)
        
        # Get current date and time
        now = datetime.datetime.now(app.CACHE_TIMEZONE)
        
        # Add event date and time for all notifications
        ups_info['event_date'] = now.strftime('%Y-%m-%d')
        ups_info['event_time'] = now.strftime('%H:%M:%S')
        
        # For ONLINE events, try to calculate how long the UPS was on battery
        if event_type == 'ONLINE':
            try:
                # Check if we have an open event that we can use to calculate duration
                with app.app_context():
                    # Look for open ONBATT events
                    open_event = UPSEventModel.query.filter_by(
                        ups_name=ups_name,
                        event_type='ONBATT',
                        timestamp_utc_end=None
                    ).order_by(UPSEventModel.timestamp_utc.desc()).first()
                    
                    if open_event and open_event.timestamp_utc:
                        # Calculate duration in minutes
                        duration_seconds = (now - open_event.timestamp_utc).total_seconds()
                        duration_minutes = int(duration_seconds / 60)
                        ups_info['battery_duration'] = f"{duration_minutes} min"
                        log_message(f"DEBUG: Calculated battery_duration from open event: {ups_info['battery_duration']}", True)
                    else:
                        # If there's no open event, find the most recent ONBATT event with an end time
                        closed_events = UPSEventModel.query.filter_by(
                            ups_name=ups_name,
                            event_type='ONBATT'
                        ).filter(UPSEventModel.timestamp_utc_end != None).order_by(UPSEventModel.timestamp_utc.desc()).limit(5).all()
                        
                        log_message(f"DEBUG: Found {len(closed_events)} closed ONBATT events", True)
                        
                        if closed_events:
                            # Find the most recent one that's likely to be related to this ONLINE event
                            for event in closed_events:
                                # Check if the event ended within the last hour
                                if event.timestamp_utc_end and (now - event.timestamp_utc_end).total_seconds() < 3600:
                                    if event.timestamp_utc:
                                        duration_seconds = (event.timestamp_utc_end - event.timestamp_utc).total_seconds()
                                        duration_minutes = int(duration_seconds / 60)
                                        ups_info['battery_duration'] = f"{duration_minutes} min"
                                        log_message(f"DEBUG: Calculated battery_duration from closed event: {ups_info['battery_duration']}", True)
                                        break
                        
                        # If we still don't have a duration, look at UPS statistics
                        if 'battery_duration' not in ups_info or ups_info['battery_duration'] == '0 min':
                            # Try to get it from known runtime stats
                            if 'device_uptime' in ups_info and ups_info['device_uptime'].isdigit():
                                # Use device uptime as a fallback (likely restart after power off)
                                uptime_min = int(ups_info['device_uptime']) // 60
                                if uptime_min < 60:  # If uptime is less than 60 minutes, it's likely from a restart
                                    ups_info['battery_duration'] = f"{uptime_min} min"
                                    log_message(f"DEBUG: Estimated battery_duration from device_uptime: {ups_info['battery_duration']}", True)
            except Exception as e:
                log_message(f"WARNING: Could not calculate battery_duration: {e}", True)
                log_message(f"TRACEBACK: {traceback.format_exc()}", True)
        
        # For COMMOK events, try to calculate how long communication was lost
        elif event_type == 'COMMOK':
            try:
                # Check if we have an open event that we can use to calculate duration
                with app.app_context():
                    open_event = UPSEventModel.query.filter_by(
                        ups_name=ups_name,
                        event_type='COMMBAD',
                        timestamp_utc_end=None
                    ).order_by(UPSEventModel.timestamp_utc.desc()).first()
                    
                    if open_event and open_event.timestamp_utc:
                        # Calculate duration in minutes
                        duration_seconds = (now - open_event.timestamp_utc).total_seconds()
                        duration_minutes = int(duration_seconds / 60)
                        ups_info['comm_duration'] = f"{duration_minutes} min"
                        log_message(f"DEBUG: Calculated comm_duration = {ups_info['comm_duration']}", True)
            except Exception as e:
                log_message(f"WARNING: Could not calculate comm_duration: {e}", True)
                log_message(f"TRACEBACK: {traceback.format_exc()}", True)
        
        # Ensure data is properly formatted for notification
        # Make sure battery charge has % symbol
        battery_charge = ups_info.get('battery_charge', '0')
        if not battery_charge.endswith('%'):
            battery_charge = f"{battery_charge}%"
            
        # Make sure voltage values have V suffix
        input_voltage = ups_info.get('input_voltage', '0')
        if not input_voltage.endswith('V'):
            input_voltage = f"{input_voltage}V"
            
        battery_voltage = ups_info.get('battery_voltage', '0') 
        if not battery_voltage.endswith('V'):
            battery_voltage = f"{battery_voltage}V"
        
        # Make sure runtime has min suffix and is converted from seconds if needed
        if 'battery_runtime' in ups_info and ups_info['battery_runtime'].isdigit():
            runtime_min = int(ups_info['battery_runtime']) // 60
            ups_info['runtime_estimate'] = f"{runtime_min} min"
            log_message(f"DEBUG: Calculated runtime_estimate from battery_runtime: {ups_info['runtime_estimate']}", True)
        elif 'runtime_estimate' in ups_info and not ups_info['runtime_estimate'].endswith('min'):
            ups_info['runtime_estimate'] = f"{ups_info['runtime_estimate']} min"
            
        # Make sure we always have some value for runtime_estimate
        if 'runtime_estimate' not in ups_info or ups_info['runtime_estimate'] == '0 min':
            # Try to get it from battery_runtime_low
            if 'battery_runtime_low' in ups_info and ups_info['battery_runtime_low'].isdigit():
                runtime_min = int(ups_info['battery_runtime_low']) // 60
                ups_info['runtime_estimate'] = f"{runtime_min} min"
                log_message(f"DEBUG: Used battery_runtime_low as fallback for runtime_estimate: {ups_info['runtime_estimate']}", True)
            # If still not available, try battery_charge and a simple estimation
            elif 'battery_charge' in ups_info:
                charge = ups_info['battery_charge']
                if charge.endswith('%'):
                    charge = charge[:-1]
                if charge.isdigit():
                    # Simple estimation: 1% charge = 1 minute runtime (very rough approximation)
                    charge_value = int(charge)
                    ups_info['runtime_estimate'] = f"{charge_value} min" 
                    log_message(f"DEBUG: Estimated runtime from battery charge: {ups_info['runtime_estimate']}", True)
        
        # Make sure comm_duration has min suffix
        comm_duration = ups_info.get('comm_duration', '0 min')
        if not comm_duration.endswith('min'):
            comm_duration = f"{comm_duration} min"
        
        # Update UPS info with formatted values
        ups_info['battery_charge'] = battery_charge
        ups_info['input_voltage'] = input_voltage
        ups_info['battery_voltage'] = battery_voltage
        ups_info['runtime_estimate'] = ups_info['runtime_estimate']
        ups_info['comm_duration'] = comm_duration
        ups_info['ups_model'] = ups_info.get('ups_model') or ups_info.get('device_model') or 'UPS Device'
        ups_info['ups_host'] = ups_name
        
        log_message(f"DEBUG: Ntfy formatted UPS info: {ups_info}", True)
        
        # Generate event title based on event type (ASCII only, no emoji to avoid encoding issues)
        event_titles = {
            "ONLINE": f"UPS Online - {ups_name}",
            "ONBATT": f"UPS On Battery - {ups_name}",
            "LOWBATT": f"UPS Low Battery - {ups_name}",
            "COMMOK": f"UPS Communication Restored - {ups_name}",
            "COMMBAD": f"UPS Communication Lost - {ups_name}",
            "SHUTDOWN": f"System Shutdown Imminent - {ups_name}",
            "REPLBATT": f"UPS Battery Needs Replacement - {ups_name}",
            "NOCOMM": f"UPS Not Reachable - {ups_name}",
            "NOPARENT": f"Parent Process Lost - {ups_name}",
            "FSD": f"UPS Forced Shutdown - {ups_name}"
        }
        
        title = event_titles.get(event_type, f"UPS Event: {event_type} - {ups_name}")
        
        # Create detailed, formatted message based on the event type
        details = format_ups_details(ups_info)
        
        # Create event message based on the type
        event_messages = {
            "ONLINE": f"🔌 Power has been restored! UPS {ups_name} is now running on line power.\n\n{details}",
            "ONBATT": f"⚠️ POWER FAILURE DETECTED! UPS {ups_name} is now running on battery power.\n\n{details}",
            "LOWBATT": f"🚨 CRITICAL ALERT! UPS {ups_name} has critically low battery level. Shutdown imminent!\n\n{details}",
            "COMMOK": f"✅ Communication with UPS {ups_name} has been restored.\n\n{details}",
            "COMMBAD": f"❌ WARNING! Communication with UPS {ups_name} has been lost.\n\n{details}",
            "SHUTDOWN": f"🚨 CRITICAL! System on UPS {ups_name} is shutting down due to power issues.\n\n{details}",
            "REPLBATT": f"🔋 The battery of UPS {ups_name} needs to be replaced.\n\n{details}",
            "NOCOMM": f"❌ WARNING! No communication with UPS {ups_name} for an extended period.\n\n{details}",
            "NOPARENT": f"⚠️ The parent process monitoring UPS {ups_name} has died.\n\n{details}",
            "FSD": f"🚨 EMERGENCY! UPS {ups_name} is performing a forced shutdown.\n\n{details}"
        }
        
        message = event_messages.get(event_type, f"UPS {ups_name} reports status: {event_type}\n\n{details}")
        
        # Get tag for the event type
        tag_map = {
            "ONLINE": "white_check_mark",
            "ONBATT": "battery",
            "LOWBATT": "warning,battery",
            "COMMOK": "signal_strength",
            "COMMBAD": "no_mobile_phones",
            "SHUTDOWN": "sos,warning",
            "REPLBATT": "wrench,battery",
            "NOCOMM": "no_entry,warning",
            "NOPARENT": "ghost",
            "FSD": "sos,warning"
        }
        
        tags = tag_map.get(event_type, "")
        
        # Set priority based on event type
        priority_map = {
            "LOWBATT": 5,  # Emergency
            "SHUTDOWN": 5, # Emergency
            "FSD": 5,      # Emergency
            "ONBATT": 4,   # High
            "COMMBAD": 4,  # High
            "NOCOMM": 4,   # High
            "REPLBATT": 3, # Normal
            "NOPARENT": 3, # Normal
            "ONLINE": 3,   # Normal
            "COMMOK": 2    # Low
        }
        
        priority = priority_map.get(event_type, config.get('priority', 3))
        
        # Create a NtfyNotifier instance using the config and send the notification
        from core.extranotifs.ntfy.ntfy import NtfyNotifier
        # Log more detailed info about the notification being sent
        server = config.get('server', 'https://ntfy.sh')
        topic = config.get('topic', '')
        log_message(f"Sending ntfy notification to {server}/{topic} with tags: {tags}", True)
        notifier = NtfyNotifier(config)
        result = notifier.send_notification(title, message, event_type, priority)
        
        if result.get('success'):
            log_message(f"Sent {event_type} notification for {ups_name} via Ntfy to {topic}")
        else:
            log_message(f"ERROR: {result.get('message')}")
            
        return result
    except Exception as e:
        log_message(f"ERROR: Failed to send Ntfy notification: {str(e)}")
        log_message(f"TRACEBACK: {traceback.format_exc()}", True)
        return {"success": False, "message": str(e)}

def get_detailed_ups_info(ups_name):
    """
    Get comprehensive UPS information from database using ORM
    
    Args:
        ups_name: Name of the UPS
        
    Returns:
        dict: Detailed UPS information
    """
    try:
        # Add detailed logging
        log_message(f"DEBUG: Starting get_detailed_ups_info for {ups_name}", True)
        
        # Default UPS info with safe values
        ups_info = {
            'ups_model': 'Unknown',
            'device_serial': 'Unknown',
            'ups_status': 'Unknown',
            'battery_charge': '0',
            'runtime_estimate': '0',
            'input_voltage': '0',
            'battery_voltage': '0',
            'ups_host': ups_name,
            'battery_voltage_nominal': '0',
            'battery_type': 'Unknown',
            'ups_timer_shutdown': '0',
            'ups_firmware': 'Unknown',
            'ups_mfr': 'Unknown',
            'device_location': 'Unknown',
            'last_update': datetime.datetime.now(app.CACHE_TIMEZONE).strftime('%Y-%m-%d %H:%M:%S')
        }
        
        # Get current date and time for the event
        now = datetime.datetime.now(app.CACHE_TIMEZONE)
        
        # Format date and time for the template
        ups_info['event_date'] = now.strftime('%Y-%m-%d')
        ups_info['event_time'] = now.strftime('%H:%M:%S')
        
        # Use ORM but with dynamic/flexible approach
        with app.app_context():
            try:
                # Get static data using dynamic SQL through ORM
                log_message("DEBUG: Querying static data using dynamic ORM query", True)
                
                # First check if tables exist
                tables = inspect(db.engine).get_table_names()
                log_message(f"DEBUG: Available tables in database: {tables}", True)
                
                if 'ups_static_data' in tables:
                    # Use pure ORM approach to get the static data
                    from core.db.ups.models import get_static_model
                    UPSStaticData = get_static_model(db)
                    
                    # Get the first record using ORM
                    static_record = UPSStaticData.query.first()
                    log_message(f"DEBUG: Got static data record: {static_record}", True)
                    
                    if static_record:
                        # Convert ORM object to dictionary
                        static_data = {column.name: getattr(static_record, column.name) 
                                      for column in static_record.__table__.columns}
                        log_message(f"DEBUG: Static data retrieved: {static_data}", True)
                        
                        # Key fields we're interested in
                        for field in ['device_model', 'device_serial', 'battery_type', 'ups_model']:
                            if field in static_data and static_data[field] is not None:
                                ups_info[field] = str(static_data[field])
                                log_message(f"DEBUG: Set static value {field} = {ups_info[field]}", True)
                
                if 'ups_dynamic_data' in tables:
                    # Use pure ORM approach to get the dynamic data
                    from core.db.ups.models import get_ups_model
                    UPSDynamicData = get_ups_model(db)
                    
                    # Get the most recent record using ORM
                    dynamic_record = UPSDynamicData.query.order_by(UPSDynamicData.timestamp_utc.desc()).first()
                    log_message(f"DEBUG: Got dynamic data record: {dynamic_record}", True)
                    
                    if dynamic_record:
                        # Convert ORM object to dictionary
                        dynamic_data = {column.name: getattr(dynamic_record, column.name) 
                                       for column in dynamic_record.__table__.columns}
                        log_message(f"DEBUG: Dynamic data retrieved: {dynamic_data}", True)
                        
                        # Update ups_info with all available dynamic data
                        for key, value in dynamic_data.items():
                            if key not in ['id', 'timestamp_utc'] and value is not None:
                                ups_info[key] = str(value)
                                log_message(f"DEBUG: Set dynamic value {key} = {value}", True)
                        
                        # Store the timestamp with timezone conversion
                        if 'timestamp_utc' in dynamic_data and dynamic_data['timestamp_utc'] is not None:
                            # Convert UTC timestamp to local timezone
                            timestamp_utc = dynamic_data['timestamp_utc']
                            if isinstance(timestamp_utc, str):
                                try:
                                    # Try to parse ISO format string
                                    timestamp_utc = datetime.datetime.fromisoformat(timestamp_utc.replace('Z', '+00:00'))
                                except ValueError:
                                    # If it's not an ISO format, try a basic datetime parse
                                    try:
                                        timestamp_utc = datetime.datetime.strptime(timestamp_utc, '%Y-%m-%d %H:%M:%S.%f')
                                    except ValueError:
                                        # If all parsing fails, use current time
                                        timestamp_utc = datetime.datetime.utcnow()
                            
                            # Ensure timestamp is timezone aware (UTC)
                            if timestamp_utc.tzinfo is None:
                                timestamp_utc = timestamp_utc.replace(tzinfo=pytz.UTC)
                                
                            # Convert to local timezone
                            local_timestamp = timestamp_utc.astimezone(app.CACHE_TIMEZONE)
                            ups_info['last_update'] = local_timestamp.strftime('%Y-%m-%d %H:%M:%S')
                            log_message(f"DEBUG: Set last_update = {ups_info['last_update']} (converted from UTC)", True)
                        else:
                            log_message("DEBUG: No timestamp_utc found in data, using current time", True)
            except Exception as e:
                log_message(f"WARNING: Dynamic ORM query failed: {e}", True)
                log_message(f"TRACEBACK: {traceback.format_exc()}", True)
        
        # Ensure proper formatting of all values
        # Make sure battery charge has % symbol
        if 'battery_charge' in ups_info and not ups_info['battery_charge'].endswith('%'):
            ups_info['battery_charge'] = f"{ups_info['battery_charge']}%"
            
        # Make sure voltage values have V suffix
        for key in list(ups_info.keys()):
            if 'voltage' in key and not ups_info[key].endswith('V'):
                ups_info[key] = f"{ups_info[key]}V"
        
        # Make sure runtime has min suffix and is converted from seconds if needed
        if 'battery_runtime' in ups_info and ups_info['battery_runtime'].isdigit():
            runtime_min = int(ups_info['battery_runtime']) // 60
            ups_info['runtime_estimate'] = f"{runtime_min} min"
            log_message(f"DEBUG: Calculated runtime_estimate from battery_runtime: {ups_info['runtime_estimate']}", True)
        elif 'runtime_estimate' in ups_info and not ups_info['runtime_estimate'].endswith('min'):
            ups_info['runtime_estimate'] = f"{ups_info['runtime_estimate']} min"
            
        # Make sure we always have some value for runtime_estimate
        if 'runtime_estimate' not in ups_info or ups_info['runtime_estimate'] == '0 min':
            # Try to get it from battery_runtime_low
            if 'battery_runtime_low' in ups_info and ups_info['battery_runtime_low'].isdigit():
                runtime_min = int(ups_info['battery_runtime_low']) // 60
                ups_info['runtime_estimate'] = f"{runtime_min} min"
                log_message(f"DEBUG: Used battery_runtime_low as fallback for runtime_estimate: {ups_info['runtime_estimate']}", True)
            # If still not available, try battery_charge and a simple estimation
            elif 'battery_charge' in ups_info:
                charge = ups_info['battery_charge']
                if charge.endswith('%'):
                    charge = charge[:-1]
                if charge.isdigit():
                    # Simple estimation: 1% charge = 1 minute runtime (very rough approximation)
                    charge_value = int(charge)
                    ups_info['runtime_estimate'] = f"{charge_value} min" 
                    log_message(f"DEBUG: Estimated runtime from battery charge: {ups_info['runtime_estimate']}", True)
        
        # Improve battery duration if it's 0 min
        if 'battery_duration' in ups_info and ups_info['battery_duration'] == '0 min':
            if 'device_uptime' in ups_info and ups_info['device_uptime'].isdigit():
                # Use device uptime as a fallback (likely restart after power off)
                uptime_min = int(ups_info['device_uptime']) // 60
                if uptime_min > 0 and uptime_min < 60:  # If uptime is less than 60 minutes, it's likely from a restart
                    ups_info['battery_duration'] = f"{uptime_min} min"
                    log_message(f"DEBUG: Estimated battery_duration from device_uptime in get_detailed_ups_info: {ups_info['battery_duration']}", True)
        
        # Log final UPS info
        log_message(f"DEBUG: Final UPS info: {ups_info}", True)
        
        return ups_info
        
    except Exception as e:
        log_message(f"ERROR: Failed to get detailed UPS info: {e}")
        log_message(f"TRACEBACK: {traceback.format_exc()}", True)
        return {
            'ups_model': 'Unknown',
            'device_serial': 'Unknown',
            'ups_status': 'Unknown',
            'battery_charge': '0',
            'runtime_estimate': '0 min',
            'input_voltage': '0V',
            'battery_voltage': '0V',
            'ups_host': ups_name,
            'last_update': datetime.datetime.now(app.CACHE_TIMEZONE).strftime('%Y-%m-%d %H:%M:%S'),
            'event_date': datetime.datetime.now(app.CACHE_TIMEZONE).strftime('%Y-%m-%d'),
            'event_time': datetime.datetime.now(app.CACHE_TIMEZONE).strftime('%H:%M:%S')
        }

def format_ups_details(ups_info):
    """
    Format UPS information into a readable string
    
    Args:
        ups_info: Dictionary of UPS information
        
    Returns:
        str: Formatted UPS details
    """
    log_message(f"DEBUG: Formatting UPS details from: {ups_info}", True)
    
    # Format the battery runtime from seconds to minutes if available
    runtime_min = '0'
    if 'battery_runtime' in ups_info:
        runtime_str = ups_info['battery_runtime']
        if isinstance(runtime_str, str) and runtime_str.isdigit():
            runtime_min = str(int(runtime_str) // 60)
        elif 'runtime_estimate' in ups_info:
            runtime_str = ups_info['runtime_estimate']
            if runtime_str.endswith(' min'):
                runtime_min = runtime_str.replace(' min', '')
    
    # Ensure battery charge has % symbol
    battery_charge = ups_info.get('battery_charge', '0')
    if not battery_charge.endswith('%'):
        battery_charge = f"{battery_charge}%"
    
    # Ensure voltage values have V suffix
    input_voltage = ups_info.get('input_voltage', '0')
    if not input_voltage.endswith('V'):
        input_voltage = f"{input_voltage}V"
    
    battery_voltage = ups_info.get('battery_voltage', '0')
    if not battery_voltage.endswith('V'):
        battery_voltage = f"{battery_voltage}V"
        
    output_voltage = ups_info.get('output_voltage', '0')
    if not output_voltage.endswith('V') and output_voltage != '0':
        output_voltage = f"{output_voltage}V"
        
    battery_voltage_nominal = ups_info.get('battery_voltage_nominal', '0')
    if not battery_voltage_nominal.endswith('V') and battery_voltage_nominal != '0':
        battery_voltage_nominal = f"{battery_voltage_nominal}V"
    
    # Format UPS load if available
    ups_load = ups_info.get('ups_load', '')
    if ups_load and not ups_load.endswith('%'):
        ups_load = f"{ups_load}%"
        
    # Format battery durations and make sure they're never 0 min if we can help it
    battery_duration = ups_info.get('battery_duration', '0 min')
    if not battery_duration.endswith('min'):
        battery_duration = f"{battery_duration} min"
    
    # Improve runtime estimate if it's 0 min
    runtime_estimate = ups_info.get('runtime_estimate', '0 min')
    if runtime_estimate == '0 min' and battery_charge != '0%':
        # Try to calculate from battery charge
        charge = battery_charge
        if charge.endswith('%'):
            charge = charge[:-1]
        if charge.isdigit():
            charge_value = int(charge)
            if charge_value > 0:
                # Simple estimation: 1% charge = 1 minute runtime (very rough approximation)
                runtime_estimate = f"{charge_value} min"
                log_message(f"DEBUG: Estimated runtime from battery charge in format_ups_details: {runtime_estimate}", True)
    
    # Improve battery duration if it's 0 min
    if battery_duration == '0 min' and 'device_uptime' in ups_info and ups_info['device_uptime'].isdigit():
        # Use device uptime as a fallback (likely restart after power off)
        uptime_min = int(ups_info['device_uptime']) // 60
        if uptime_min > 0 and uptime_min < 60:  # If uptime is less than 60 minutes, it's likely from a restart
            battery_duration = f"{uptime_min} min"
            log_message(f"DEBUG: Estimated battery_duration from device_uptime in format_ups_details: {battery_duration}", True)
    
    # Create a detailed status report
    details = []
    
    # Device information section
    device_model = ups_info.get('device_model') or ups_info.get('ups_model') or 'Unknown'
    device_serial = ups_info.get('device_serial') or ups_info.get('ups_serial') or 'Unknown'
    device_location = ups_info.get('device_location', '')
    
    device_section = [
        f"📱 DEVICE INFO:",
        f"  Model: {device_model}",
        f"  Serial: {device_serial}"
    ]
    
    if device_location:
        device_section.append(f"  Location: {device_location}")
    if ups_info.get('ups_firmware'):
        device_section.append(f"  Firmware: {ups_info.get('ups_firmware')}")
    if ups_info.get('ups_mfr'):
        device_section.append(f"  Manufacturer: {ups_info.get('ups_mfr')}")
        
    details.append("\n".join(device_section))
    
    # Power information section
    power_section = [
        f"⚡ POWER INFO:",
        f"  Status: {ups_info.get('ups_status', 'Unknown')}"
    ]
    
    if input_voltage != '0V':
        power_section.append(f"  Input Voltage: {input_voltage}")
    
    if output_voltage != '0V':
        power_section.append(f"  Output Voltage: {output_voltage}")
    
    if ups_load:
        power_section.append(f"  UPS Load: {ups_load}")
    
    # Battery information section
    battery_section = [
        f"🔋 BATTERY INFO:",
        f"  Charge: {battery_charge}"
    ]
    
    if runtime_estimate and runtime_estimate != '0 min':
        battery_section.append(f"  Est. Runtime: {runtime_estimate}")
    
    if battery_voltage != '0V':
        battery_section.append(f"  Battery Voltage: {battery_voltage}")
    
    if battery_voltage_nominal != '0V':
        battery_section.append(f"  Nominal Voltage: {battery_voltage_nominal}")
    
    if 'battery_temperature' in ups_info and ups_info['battery_temperature'] != '0':
        temp = ups_info['battery_temperature']
        if not temp.endswith('°C'):
            temp = f"{temp}°C"
        battery_section.append(f"  Temperature: {temp}")
        
    if battery_duration != '0 min':
        battery_section.append(f"  Battery Duration: {battery_duration}")
    
    details.append("\n".join(battery_section))
    
    # Event information section if we have date and time
    if ups_info.get('event_date') and ups_info.get('event_time'):
        event_section = [
            f"📅 EVENT INFO:",
            f"  Date: {ups_info.get('event_date')}",
            f"  Time: {ups_info.get('event_time')}"
        ]
        details.append("\n".join(event_section))
    
    # Last update timestamp
    details.append(f"\n⏰ Last update: {ups_info.get('last_update')}")
    
    formatted_details = "\n\n".join(details)
    log_message(f"DEBUG: Formatted UPS details: {formatted_details}", True)
    
    return formatted_details

def process_ups_event(ups_name, event_type):
    """Process a UPS event and send notifications"""
    try:
        # Store event in database first
        if not store_event_in_database(ups_name, event_type):
            logger.error("Failed to store event in database")
            return False
            
        # Get enabled email notifications
        notifications = get_enabled_notifications(event_type)
        
        # Get enabled ntfy configurations
        ntfy_configs = get_enabled_ntfy_configs(event_type)
            
        # Check if we have any notifications to send
        if not notifications and not ntfy_configs and not HAS_WEBHOOK:
            logger.info(f"No enabled notifications found for {event_type}")
            return True
            
        # Send email notifications if there are any enabled
        if notifications:
            # Verify email configuration before sending notifications
            if not verify_email_config():
                logger.info("Email notifications disabled - no valid email configuration")
            else:
                # Send notifications
                for notification in notifications:
                    if notification.get('type') == 'email':
                        send_email_notification(ups_name, event_type, notification)
        
        # Send ntfy notifications if there are any enabled
        if ntfy_configs and HAS_NTFY:
            logger.info(f"Processing {len(ntfy_configs)} Ntfy configurations for {event_type}")
            for i, config in enumerate(ntfy_configs):
                logger.info(f"Sending Ntfy notification {i+1}/{len(ntfy_configs)} to server: {config.get('server')} (ID: {config.get('id')})")
                result = send_ntfy_notification(ups_name, event_type, config)
                if not result.get('success', False):
                    logger.warning(f"Failed to send Ntfy notification to {config.get('server')}: {result.get('message', 'Unknown error')}")
                
        # Send webhook notifications if available
        if HAS_WEBHOOK:
            try:
                logger.info(f"Sending webhook notifications for {event_type}")
                
                # Special handling for UPS communication events to ensure notifications are sent
                if event_type in ['COMMBAD', 'COMMOK', 'NOCOMM']:
                    logger.info(f"⚠️ UPS communication event detected: {event_type} - Ensuring notification is sent")
                    # Force a more detailed log for debugging
                    try:
                        from core.extranotifs.webhook.db import get_enabled_configs_for_event
                        enabled_configs = get_enabled_configs_for_event(event_type)
                        
                        if enabled_configs:
                            logger.info(f"Found {len(enabled_configs)} webhook configurations for {event_type}")
                        else:
                            logger.warning(f"No enabled webhook configurations found for {event_type}. Check notification settings for webhook.")
                    except Exception as config_err:
                        logger.error(f"Error checking enabled webhook configs: {str(config_err)}")
                
                result = send_webhook_notification(event_type, ups_name)
                if result.get('success'):
                    logger.info(f"Webhook notifications sent: {result.get('message')}")
                else:
                    logger.warning(f"Webhook notifications failed or none configured: {result.get('message')}")
                    
                    # Additional error details for debugging
                    if 'error_type' in result:
                        logger.warning(f"Webhook error type: {result.get('error_type')}")
                    if 'response' in result:
                        logger.warning(f"Webhook response: {result.get('response')}")
            except Exception as e:
                logger.error(f"Error sending webhook notifications: {str(e)}")
                logger.error(f"Traceback for webhook error: {traceback.format_exc()}")
                
        return True
    except Exception as e:
        logger.error(f"Failed to process event: {str(e)}")
        return False

def main():
    """Main entry point for the script"""
    try:
        # Log that we're running in direct mode (no sockets)
        log_message("📝 Running UPS notifier in direct mode (no socket communication)")
        
        # Log all environment variables to help with debugging
        log_message("🔍 Environment: PYTHONPATH=" + os.environ.get("PYTHONPATH", "Not set"))
        log_message("🔍 Script running as user: " + os.environ.get("USER", "Unknown") + " (UID: " + str(os.getuid()) + ")")
        log_message("🔍 Python executable: " + sys.executable)
        log_message("🔍 Python version: " + sys.version)
        log_message("🔍 Python path: " + str(sys.path))
        
        # Remove the script name from arguments
        args = sys.argv[1:]
        
        log_message(f"📝 Called with arguments: {args}")
        
        # Parse input arguments
        ups_name, event_type = parse_input_args(args)
        
        if not ups_name or not event_type:
            log_message("ERROR: Failed to parse UPS name or event type")
            sys.exit(1)
            
        log_message(f"Parsed UPS_NAME={ups_name}, EVENT_TYPE={event_type}")
        
        # Log the event based on its type
        event_messages = {
            "ONLINE": f"UPS '{ups_name}' is ONLINE - Power has been restored",
            "ONBATT": f"UPS '{ups_name}' is ON BATTERY - Power failure detected",
            "LOWBATT": f"WARNING: UPS '{ups_name}' has LOW BATTERY - Critical power level",
            "FSD": f"CRITICAL: UPS '{ups_name}' - Forced shutdown in progress",
            "COMMOK": f"UPS '{ups_name}' - Communication restored",
            "COMMBAD": f"WARNING: UPS '{ups_name}' - Communication lost",
            "SHUTDOWN": f"CRITICAL: UPS '{ups_name}' - System shutdown in progress",
            "REPLBATT": f"WARNING: UPS '{ups_name}' - Battery needs replacing",
            "NOCOMM": f"WARNING: UPS '{ups_name}' - No communication for extended period",
            "NOPARENT": f"WARNING: UPS '{ups_name}' - Parent process died",
            "CAL": f"UPS '{ups_name}' - Calibration in progress",
            "TRIM": f"UPS '{ups_name}' - Trimming incoming voltage",
            "BOOST": f"UPS '{ups_name}' - Boosting incoming voltage",
            "OFF": f"UPS '{ups_name}' - UPS is switched off",
            "OVERLOAD": f"WARNING: UPS '{ups_name}' - UPS is overloaded",
            "BYPASS": f"UPS '{ups_name}' - UPS is in bypass mode",
            "NOBATT": f"WARNING: UPS '{ups_name}' - UPS has no battery",
            "DATAOLD": f"WARNING: UPS '{ups_name}' - UPS data is too old"
        }
        
        log_message(event_messages.get(event_type, f"UPS '{ups_name}' status: {event_type}"))
        
        # Process the event within app context
        with app.app_context():
            if process_ups_event(ups_name, event_type):
                log_message("Notification processing complete")
                sys.exit(0)
            else:
                log_message("ERROR: Failed to process notification")
                sys.exit(1)
            
    except Exception as e:
        log_message(f"CRITICAL ERROR: {str(e)}")
        traceback.print_exc(file=open(DEBUG_LOG, 'a'))
        sys.exit(1)

if __name__ == "__main__":
    main() 