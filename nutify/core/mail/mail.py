import subprocess
from datetime import datetime
import tempfile
import os
from ..db.ups import (
    db, data_lock, get_ups_data, get_ups_model,
    UPSData as DotDict,
    create_static_model, UPSEvent
)
from cryptography.fernet import Fernet
import base64
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import os
from flask import render_template, current_app
from ..settings import (
    MSMTP_PATH,
    TLS_CERT_PATH
)
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from ..logger import mail_logger as logger
from .provider import email_providers
from sqlalchemy import text, inspect
import re
import logging
import socket
import time
import json
from core.settings.settings import get_server_name
import traceback

logger.info("📨 Initializating mail")

# Secret key - will be loaded from app.py's Flask app.config
SECRET_KEY = None

# Get secret key ONLY from Flask app config (set in app.py)
def load_encryption_key():
    """
    Load encryption key strictly from Flask app.config['SECRET_KEY'].
    
    This function will ONLY use the SECRET_KEY set in the environment.
    NO fallbacks are provided - if SECRET_KEY is not in the environment, 
    encryption features will be disabled.
    
    Returns:
        bool: True if SECRET_KEY was successfully loaded, False otherwise
    """
    global SECRET_KEY
    
    # Only check for Flask app config - this is the ONLY valid source
    try:
        if current_app and current_app.config.get('SECRET_KEY'):
            secret_key = current_app.config.get('SECRET_KEY')
            if secret_key:
                # Store original value for debugging
                key_preview = secret_key[:5] if isinstance(secret_key, str) else str(secret_key)[:5]
                
                # Ensure SECRET_KEY is stored as bytes
                SECRET_KEY = secret_key.encode() if isinstance(secret_key, str) else secret_key
                
                logger.info(f"🔑 Secret key loaded from Flask app config (first 5 chars: {key_preview}...)")
                
                # Verify the key is valid by creating a test Fernet instance
                try:
                    kdf = PBKDF2HMAC(
                        algorithm=hashes.SHA256(),
                        length=32,
                        salt=b'fixed-salt',
                        iterations=100000,
                    )
                    key = base64.urlsafe_b64encode(kdf.derive(SECRET_KEY))
                    Fernet(key)  # This will raise an exception if the key is invalid
                    logger.debug("✅ SECRET_KEY validation successful - encryption is available")
                    return True
                except Exception as key_err:
                    logger.error(f"❌ SECRET_KEY loaded but is invalid: {str(key_err)}")
                    SECRET_KEY = None
                    return False
            else:
                logger.warning("⚠️ SECRET_KEY in app config is empty")
        else:
            logger.warning("⚠️ SECRET_KEY not found in app config")
    except Exception as app_error:
        logger.warning(f"Could not get SECRET_KEY from Flask app config: {str(app_error)}")
    
    # If SECRET_KEY not found in environment - no fallback, just fail gracefully
    logger.warning("⚠️ SECRET_KEY not available - must be set in environment")
    logger.warning("Encryption will be unavailable until SECRET_KEY is properly set in environment")
    return False


def get_encryption_key():
    """
    Generates an encryption key from SECRET_KEY.
    
    Always tries to get the most current SECRET_KEY from Flask's current_app.config.
    Only falls back to the global SECRET_KEY if current_app is not available.
    
    Returns:
        Fernet: An encryption key derived from SECRET_KEY
        
    Raises:
        RuntimeError: If SECRET_KEY is not available
    """
    # Always try to get the SECRET_KEY directly from Flask's current_app first
    try:
        if current_app and current_app.config.get('SECRET_KEY'):
            secret_key = current_app.config.get('SECRET_KEY')
            if secret_key:
                secret_key_bytes = secret_key.encode() if isinstance(secret_key, str) else secret_key
                logger.debug("Using SECRET_KEY directly from Flask's current_app.config")
                
                # Use the SECRET_KEY from environment to derive the encryption key
                kdf = PBKDF2HMAC(
                    algorithm=hashes.SHA256(),
                    length=32,
                    salt=b'fixed-salt',
                    iterations=100000,
                )
                
                key = base64.urlsafe_b64encode(kdf.derive(secret_key_bytes))
                return Fernet(key)
    except Exception:
        logger.debug("Could not get SECRET_KEY from current_app, falling back to global SECRET_KEY")
    
    # Fall back to global SECRET_KEY if current_app is not available
    global SECRET_KEY
    
    # If we don't have a key, try to load it one more time
    if SECRET_KEY is None:
        load_encryption_key()
    
    # If SECRET_KEY is still not available, fail explicitly
    if SECRET_KEY is None:
        raise RuntimeError("SECRET_KEY is not available. Password encryption is disabled.")
    
    # Use the SECRET_KEY from environment to derive the encryption key
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b'fixed-salt',
        iterations=100000,
    )
    
    key = base64.urlsafe_b64encode(kdf.derive(SECRET_KEY))
    return Fernet(key)

# Load encryption key on module initialization
load_encryption_key()

# Initialize timezone variable - will be updated when app context is available
tz = None

def init_timezone():
    """Initialize timezone from app context - call this when app context is available"""
    global tz
    from flask import current_app
    if hasattr(current_app, 'CACHE_TIMEZONE'):
        tz = current_app.CACHE_TIMEZONE
        logger.info(f"🌍 Mail module using timezone: {tz.zone}")
    else:
        logger.error("❌ CACHE_TIMEZONE not available on Flask app - this is a critical error")
        logger.error("❌ The mail module requires access to the application timezone")
        # We don't provide a fallback - CACHE_TIMEZONE must be available

def get_timezone():
    """Safely get the timezone from Flask app context"""
    from flask import current_app
    if hasattr(current_app, 'CACHE_TIMEZONE'):
        return current_app.CACHE_TIMEZONE
    # No fallback - returning None to indicate missing timezone
    logger.error("❌ CACHE_TIMEZONE not available on Flask app - cannot proceed")
    return None

# Global variable to track last test notification time
_last_test_notification_time = 0
_test_notification_cooldown = 2  # seconds

# Helper functions to safely access models
def get_mail_config_model():
    """Get the MailConfig model safely"""
    if hasattr(db, 'ModelClasses') and hasattr(db.ModelClasses, 'MailConfig'):
        return db.ModelClasses.MailConfig
    logger.warning("⚠️ MailConfig model not available through db.ModelClasses")
    return None

def get_notification_settings_model():
    """Get the NotificationSettings model safely"""
    if hasattr(db, 'ModelClasses') and hasattr(db.ModelClasses, 'NotificationSettings'):
        return db.ModelClasses.NotificationSettings
    logger.warning("⚠️ NotificationSettings model not available through db.ModelClasses")
    return None

def get_msmtp_config(config_data):
    """Generate msmtp configuration based on provider and settings"""
    provider = config_data.get('provider', '')
    
    # Handle both naming conventions for SMTP settings (host/port and smtp_server/smtp_port)
    smtp_server = config_data.get('smtp_server', config_data.get('host', ''))
    smtp_port = config_data.get('smtp_port', config_data.get('port', 0))
    
    if not smtp_server or not smtp_port:
        logger.error("❌ SMTP server or port missing in config_data")
        logger.error(f"❌ Available keys: {list(config_data.keys())}")
        raise ValueError("SMTP server and port are required for SMTP configuration")
    
    logger.debug(f"🔧 Generating msmtp config for provider: {provider}")
    logger.debug(f"🔧 SMTP Settings: server={smtp_server}, port={smtp_port}")
    logger.debug(f"🔧 Username: {config_data.get('username', '')}")
    logger.debug(f"🔧 TLS: {config_data.get('tls', config_data.get('use_tls', True))}")
    logger.debug(f"🔧 STARTTLS: {config_data.get('tls_starttls', True)}")
    
    # Verify password is present and not None
    if 'password' not in config_data or config_data['password'] is None:
        logger.error("❌ Password is missing or None in config_data")
        raise ValueError("Password is required for SMTP configuration")
    
    # Use from_email if provided, otherwise fall back to username
    # Special handling for providers that require specific sender emails
    from_email = config_data.get('from_email', config_data.get('from_addr', ''))
    provider_info = email_providers.get(provider, {})
    requires_sender_email = provider_info.get('requires_sender_email', False)
    
    # Only for Amazon SES and other providers that require a verified sender email
    if requires_sender_email and not from_email:
        logger.error(f"❌ Provider {provider} requires a specific from_email but none was provided")
        raise ValueError(f"Provider {provider} requires a specific sender email address")
    
    # For regular providers (like iCloud, Gmail, etc), it's fine to use username as from_email
    if not from_email:
        from_email = config_data['username']
        logger.debug(f"🔧 Using username as from_email: {from_email}")
    else:
        logger.debug(f"🔧 Using explicitly provided from_email: {from_email}")
    
    # Base configuration
    config_content = f"""
# Configuration for msmtp
defaults
auth           on
"""

    # Always respect explicit settings if provided, regardless of provider
    # If not provided, use defaults based on the context
    if 'tls' in config_data:
        # User has explicitly set the TLS value - respect this choice
        use_tls = config_data.get('tls')
        logger.debug(f"🔧 Using user-specified TLS setting: {use_tls}")
    elif 'use_tls' in config_data:
        use_tls = config_data.get('use_tls')
        logger.debug(f"🔧 Using user-specified use_tls setting: {use_tls}")
    else:
        # Fallback to defaults based on provider or port
        if smtp_port == 465:
            # Port 465 typically uses implicit TLS
            use_tls = True
            logger.debug(f"🔧 Using default TLS=True for port 465")
        else:
            # Default to True for standard provider configurations, False otherwise
            use_tls = bool(provider)
            logger.debug(f"🔧 Using default TLS={use_tls} based on provider existence")
    
    if 'tls_starttls' in config_data:
        # User has explicitly set the STARTTLS value - respect this choice
        use_starttls = config_data.get('tls_starttls')
        logger.debug(f"🔧 Using user-specified STARTTLS setting: {use_starttls}")
    else:
        # Fallback to defaults based on port
        if smtp_port == 587:
            # Port 587 typically uses STARTTLS
            use_starttls = True
            logger.debug(f"🔧 Using default STARTTLS=True for port 587")
        else:
            # For other ports, default based on provider existence
            use_starttls = bool(provider)
            logger.debug(f"🔧 Using default STARTTLS={use_starttls} based on provider existence")
    
    # Log the determined TLS settings
    logger.debug(f"🔧 Final TLS setting: {use_tls} (explicit: {'tls' in config_data or 'use_tls' in config_data})")
    logger.debug(f"🔧 Final STARTTLS setting: {use_starttls} (explicit: {'tls_starttls' in config_data})")
    
    # Add TLS configuration based on the tls setting
    if use_tls:
        config_content += f"""tls            on
tls_trust_file {TLS_CERT_PATH}
"""
    else:
        config_content += "tls            off\n"

    config_content += f"""logfile        ~/.msmtp.log

account        default
host           {smtp_server}
port           {smtp_port}
from           {from_email}
user           {config_data['username']}
password       {config_data['password']}
"""
    logger.debug(f"📝 Base msmtp config generated with server: {smtp_server}:{smtp_port}")

    # Add STARTTLS configuration based on the tls_starttls setting
    if use_tls:
        if use_starttls:
            logger.debug(f"🔒 Adding STARTTLS configuration: starttls=on")
            config_content += """
tls_starttls   on
"""
        else:
            logger.debug(f"🔒 Adding STARTTLS configuration: starttls=off")
            config_content += """
tls_starttls   off
"""
    
    logger.debug("✅ msmtp configuration generated successfully")
    return config_content

def test_email_config(config_data):
    """Test email configuration by sending a test email"""
    try:
        # Create a sanitized copy of config_data for logging
        log_config = config_data.copy()
        # Mask sensitive data before any logging
        if 'password' in log_config:
            log_config['password'] = '********'
        if 'smtp_password' in log_config:
            log_config['smtp_password'] = '********'
            
        logger.debug(f"📧 Test Configuration:")
        logger.debug(f"📧 Raw config data: {log_config}")
        
        # Don't override from_email if it's explicitly provided
        # Only set it from username if it doesn't exist or is empty
        if 'from_email' not in config_data or not config_data['from_email']:
            config_data['from_email'] = config_data.get('username', '')
            
        config_data['from_name'] = config_data.get('username', '').split('@')[0] if '@' in config_data.get('username', '') else ''
            
        # Ensure required fields are present
        required_fields = ['smtp_server', 'smtp_port', 'username']
        for field in required_fields:
            if field not in config_data or not config_data[field]:
                return False, f"Missing required field: {field}"
        
        # Set default values for optional fields
        if 'provider' not in config_data:
            config_data['provider'] = ''
            
        # Get to_email if provided, otherwise use username as fallback
        to_email = config_data.get('to_email')
        if not to_email or to_email.strip() == '':
            to_email = config_data['username']
        logger.debug(f"📧 To Email: {to_email}")
        
        # Validate to_email format
        if '@' not in to_email:
            logger.error(f"❌ Invalid to_email format: {to_email}")
            return False, f"Invalid email format for recipient: {to_email}"
        
        # Respect user's choice for provider
        # If provider is an empty string, it means the user explicitly chose "Custom Configuration"
        # Only auto-detect if the provider is completely undefined (None)
        if 'provider' not in config_data and config_data['smtp_server']:
            # Provider was not specified at all, so try to detect it
            for provider, info in email_providers.items():
                if info['smtp_server'] in config_data['smtp_server']:
                    config_data['provider'] = provider
                    break
            logger.debug(f"📧 Provider determined from SMTP server: {config_data['provider']}")
        elif config_data.get('provider') == '':
            # User explicitly selected "Custom Configuration"
            logger.debug("📧 Using custom configuration (no provider auto-detection)")
            # Ensure provider is an empty string, not None
            config_data['provider'] = ''
        
        logger.debug(f"📧 Provider: {config_data['provider']}")
        logger.debug(f"📧 SMTP Server: {config_data['smtp_server']}")
        logger.debug(f"📧 SMTP Port: {config_data['smtp_port']}")
        logger.debug(f"📧 Username: {config_data['username']}")
        
        # If the password is not provided, use the saved one
        if 'password' not in config_data or not config_data['password']:
            try:
                # Get the existing configuration from the database
                existing_config = get_mail_config_model().query.first()
                if existing_config and existing_config.password:
                    logger.debug("🔑 Using existing password from configuration")
                    # Use the password property which automatically decrypts
                    decrypted_password = existing_config.password
                    if decrypted_password is None:
                        logger.error("❌ Stored password couldn't be decrypted. SECRET_KEY may have changed.")
                        return False, "Stored password cannot be decrypted. Please enter a new password."
                    config_data['password'] = decrypted_password
                else:
                    logger.error("❌ No existing mail configuration found or password is None")
                    return False, "No password provided and no valid password stored. Please enter a password."
            except Exception as de:
                # If it fails to decrypt the saved password, return an explicit error
                logger.error(f"❌ Failed to decrypt stored password: {str(de)}")
                return False, "Stored password cannot be decrypted with the current SECRET_KEY. Please enter a new password."
        
        # Generate msmtp configuration
        config_content = get_msmtp_config(config_data)
        
        # Create temporary configuration file
        with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
            f.write(config_content)
            config_file = f.name
            logger.debug(f"📄 Created temporary config file: {config_file}")
            
            # Log sanitized config content (mask password)
            sanitized_config = config_content
            if config_data.get('password'):
                # Check if password is None or empty
                if config_data['password'] is None:
                    logger.error("❌ Password is None in config_data")
                elif config_data['password'] == '':
                    logger.error("❌ Password is empty string in config_data")
                else:
                    logger.debug(f"✅ Password is present and not empty (length: {len(config_data['password'])})")
                sanitized_config = sanitized_config.replace(str(config_data['password']), '********')
            else:
                logger.error("❌ No password key in config_data")
            logger.debug(f"📄 Config file content:\n{sanitized_config}")

        # Create a temporary file for the email content
        with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
            # Get the UPS data from the database
            UPSStaticData = create_static_model()
            ups_static = db.session.query(UPSStaticData).first()
            
            # Get server name directly from settings function that's guaranteed to exist
            server_name = get_server_name()
            logger.debug(f"📧 Using server name for test email: {server_name}")
            
            email_body = render_template('dashboard/mail/test_template.html', 
                ups_model=getattr(ups_static, 'device_model', 'N/A') if ups_static else 'N/A',
                ups_serial=getattr(ups_static, 'device_serial', 'N/A') if ups_static else 'N/A',
                test_date=datetime.now(get_timezone()).strftime('%Y-%m-%d %H:%M:%S'),
                current_year=datetime.now(get_timezone()).year,
                server_name=server_name
            )
            
            # Get provider display name for the subject
            provider_display_name = ''
            if config_data.get('provider'):
                provider_info = email_providers.get(config_data['provider'])
                if provider_info and 'displayName' in provider_info:
                    provider_display_name = provider_info['displayName']
                else:
                    # Fallback to capitalize the provider name if displayName is not available
                    provider_display_name = config_data['provider'].capitalize()
            
            subject_prefix = f"{provider_display_name} " if provider_display_name else ""
            
            email_content = f"""Subject: {subject_prefix}Test Email from UPS Monitor
From: {config_data['from_name']} <{config_data['from_email']}>
To: {to_email}
Content-Type: text/html; charset=utf-8

{email_body}
"""
            f.write(email_content)
            email_file = f.name
            logger.debug(f"📄 Created temporary email file: {email_file}")
            logger.debug(f"📄 Email content:\n{email_content}")

        # Send the test email using msmtp
        cmd = [MSMTP_PATH, '-C', config_file, to_email]
        logger.debug(f"🚀 Running msmtp command: {' '.join(cmd)}")
        
        process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        with open(email_file, 'rb') as f:
            stdout, stderr = process.communicate(f.read())
        
        # Log msmtp output
        if stdout:
            logger.debug(f"📤 msmtp stdout:\n{stdout.decode()}")
        if stderr:
            logger.debug(f"📥 msmtp stderr:\n{stderr.decode()}")
        
        # Clean up the temporary files
        os.unlink(config_file)
        os.unlink(email_file)
        logger.debug("🧹 Cleaned up temporary files")
        
        if process.returncode == 0:
            logger.info("✅ Test email sent successfully")
            # Update the test status in the database
            config_id = config_data.get('id')
            if config_id:
                existing_config = get_mail_config_model().query.get(config_id)
                if existing_config:
                    db.session.commit()
            return True, "Test email sent successfully"
        else:
            error = stderr.decode()
            logger.error(f"❌ Failed to send test email: {error}")
            # Use the interpret_email_error function to get a user-friendly error message
            user_friendly_error = interpret_email_error(error)
            return False, user_friendly_error
            
    except Exception as e:
        logger.error(f"❌ Error testing email config: {str(e)}", exc_info=True)
        # Use the interpret_email_error function for exceptions as well
        user_friendly_error = interpret_email_error(str(e))
        return False, user_friendly_error

def save_mail_config(config_data):
    """Save email configuration to the database"""
    try:
        logger.debug("Saving mail config: %s", json.dumps({k: v if k != 'password' else '********' for k, v in config_data.items()}))
        
        # Check if we already have a mail config model
        MailConfig = get_mail_config_model()
        if not MailConfig:
            logger.error("MailConfig model not available")
            return False, "Mail configuration model not available"
        
        # Extract configuration ID if present - make sure it's an integer
        config_id = None
        if 'id' in config_data and config_data['id']:
            try:
                config_id = int(config_data['id'])
                logger.debug("Using provided config ID: %s", config_id)
            except (ValueError, TypeError):
                logger.warning("Invalid config ID format, treating as new configuration")
                config_id = None
        
        # Extract other fields
        smtp_server = config_data.get('smtp_server')
        smtp_port = config_data.get('smtp_port')
        username = config_data.get('smtp_username') or config_data.get('username')
        password = config_data.get('smtp_password') or config_data.get('password')
        provider = config_data.get('provider')
        to_email = config_data.get('to_email')
        tls = config_data.get('tls')
        tls_starttls = config_data.get('tls_starttls')
        enabled = config_data.get('enabled', True)  # Default to enabled
        
        # Get the from_email field
        from_email = config_data.get('from_email')
        
        # Minimal validation
        if not smtp_server or not smtp_port:
            logger.error("Required fields missing")
            return False, "SMTP server and port are required"
        
        if not username:
            logger.error("Username missing")
            return False, "Username is required"
        
        # Convert port to integer
        try:
            smtp_port = int(smtp_port)
        except (ValueError, TypeError):
            logger.error("Invalid port number: %s", smtp_port)
            return False, "Invalid port number"
        
        # Check if we're updating an existing config or creating a new one
        if config_id:
            # Try to find existing config first
            config = MailConfig.query.get(config_id)
            if not config:
                logger.debug("Config ID %s not found, creating a new configuration", config_id)
                # Create a new config with the same ID - requires manual session add
                config = MailConfig()
                db.session.add(config)
            else:
                logger.debug("Found config with ID %s, updating", config_id)
        else:
            # Create a new config
            config = MailConfig()
            db.session.add(config)
            logger.debug("Creating a new mail configuration")
        
        # Update the attributes
        config.smtp_server = smtp_server
        config.smtp_port = smtp_port
        config.username = username
        config.provider = provider
        config.to_email = to_email
        config.tls = tls
        config.tls_starttls = tls_starttls
        config.enabled = enabled
        
        # Update from_email if provided
        if from_email:
            config.from_email = from_email
        
        # Only update password if it's provided and not the masked value
        if password and password != '********':
            try:
                config.password = password
            except Exception as e:
                logger.error(f"❌ Failed to encrypt password: {str(e)}")
                return False, f"Error encrypting password: {str(e)}. Make sure SECRET_KEY is set correctly."
        elif not config_id and not password:
            # For new configurations, password is required
            logger.error("Password required for new configuration")
            return False, "Password is required for new configuration"
        elif config_id and not password and config.password is None:
            # For existing configuration where the saved password can't be decrypted
            logger.error("❌ Existing password can't be decrypted. SECRET_KEY may have changed.")
            return False, "Your existing password can't be decrypted. Please provide a new password."
        
        # Commit the changes
        db.session.commit()
        
        logger.info("Mail configuration saved successfully")
        return True, config.id
        
    except Exception as e:
        db.session.rollback()
        logger.error("Error saving mail config: %s", str(e), exc_info=True)
        return False, f"Error saving mail configuration: {str(e)}"

def send_email(to_addr, subject, html_content, smtp_settings, attachments=None):
    """
    Send an email using external SMTP command (msmtp)
    
    Args:
        to_addr (str): Recipient email address
        subject (str): Email subject
        html_content (str): HTML content of the email
        smtp_settings (dict): SMTP settings
        attachments (list, optional): List of attachments. Defaults to None.
        
    Returns:
        tuple: (success, message)
    """
    try:
        # Check that msmtp is available
        if not os.path.exists(MSMTP_PATH):
            return False, f"MSMTP not found at {MSMTP_PATH}"
        
        # Log smtp_settings keys to aid in debugging
        logger.debug(f"SMTP settings keys: {list(smtp_settings.keys())}")
        
        # Normalize the to_addr if it's a list
        if isinstance(to_addr, list):
            to_addr = ", ".join(to_addr)
            
        # Create a temporary file for the configuration
        temp_msmtp_config = None
        temp_email_file = None
        
        try:
            # Get email timeout from settings or use default
            timeout = smtp_settings.get('timeout', 60)  # Default 60 seconds, reports use 120
            
            content_size = len(html_content)
            if content_size > 500000:  # If content is larger than ~500KB
                logger.debug(f"Large email content detected ({content_size} bytes), using extended timeout")
                timeout = max(timeout, 180)  # Use at least 3 minutes for large emails
            
            logger.debug(f"📧 Subject: {subject}")
            
            # Generate msmtp configuration
            try:
                msmtp_config = get_msmtp_config(smtp_settings)
            except ValueError as config_error:
                logger.error(f"❌ Error generating SMTP configuration: {str(config_error)}")
                return False, f"Error generating SMTP configuration: {str(config_error)}"
            
            # Write config to temporary file
            with tempfile.NamedTemporaryFile(delete=False) as f:
                temp_msmtp_config = f.name
                f.write(msmtp_config.encode('utf-8'))
                logger.debug(f"📄 Created temporary config file: {temp_msmtp_config}")
                
            # Create email content
            email_content = f"To: {to_addr}\n"
            email_content += f"Subject: {subject}\n"
            email_content += "Content-Type: text/html; charset=UTF-8\n"
            email_content += "\n"
            email_content += html_content
            
            # Write email to temporary file
            with tempfile.NamedTemporaryFile(delete=False) as f:
                temp_email_file = f.name
                f.write(email_content.encode('utf-8'))
                logger.debug(f"📄 Created temporary email file: {temp_email_file}")
            
            # Prepare the command
            msmtp_cmd = f"{MSMTP_PATH} -C {temp_msmtp_config} {to_addr}"
            logger.debug(f"🚀 Running msmtp command: {msmtp_cmd}")
            
            # Execute msmtp and capture output/error
            import subprocess
            try:
                # Use subprocess with timeout
                process = subprocess.Popen(
                    msmtp_cmd.split(), 
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True
                )
                
                # Read the email content and send it to msmtp
                with open(temp_email_file, 'r') as f:
                    email_data = f.read()
                
                # Set a longer timeout for large emails
                stdout, stderr = process.communicate(input=email_data, timeout=timeout)
                
                # Check for errors
                if process.returncode != 0:
                    logger.error(f"❌ msmtp exited with code {process.returncode}: {stderr}")
                    return False, f"SMTP error: {stderr}"
                    
                logger.debug(f"🧹 Cleaned up temporary files")
                logger.info(f"✅ Email sent successfully to {to_addr}")
                return True, "Email sent successfully"
                
            except subprocess.TimeoutExpired:
                # Kill the process if it times out
                process.kill()
                logger.error(f"❌ msmtp timed out after {timeout} seconds")
                return False, f"SMTP timeout after {timeout} seconds"
                
        finally:
            # Clean up temporary files
            if temp_msmtp_config and os.path.exists(temp_msmtp_config):
                os.unlink(temp_msmtp_config)
            if temp_email_file and os.path.exists(temp_email_file):
                os.unlink(temp_email_file)
                
    except Exception as e:
        logger.error(f"❌ Failed to send email: {str(e)}")
        return False, str(e)

class EmailNotifier:
    TEMPLATE_MAP = {
        'ONLINE': 'mail/online_notification.html',
        'ONBATT': 'mail/onbatt_notification.html',
        'LOWBATT': 'mail/lowbatt_notification.html',
        'COMMOK': 'mail/commok_notification.html',
        'COMMBAD': 'mail/commbad_notification.html',
        'SHUTDOWN': 'mail/shutdown_notification.html',
        'REPLBATT': 'mail/replbatt_notification.html',
        'NOCOMM': 'mail/nocomm_notification.html',
        'NOPARENT': 'mail/noparent_notification.html'
    }

    @staticmethod
    def should_notify(event_type):
        """Check if an event type should be notified"""
        try:
            # Use the model from db.ModelClasses
            NotificationSettings = get_notification_settings_model()
            setting = NotificationSettings.query.filter_by(event_type=event_type).first()
            return setting and setting.enabled
        except Exception as e:
            logger.error(f"Error checking notification settings: {e}")
            return False

    @staticmethod
    def get_template_data(event_type, ups_name):
        """
        Get the template data using existing APIs
        Args:
            event_type: Event type (ONBATT, ONLINE, etc)
            ups_name: UPS name
        Returns:
            dict: Formatted data for the template
        """
        try:
            ups_data = get_ups_data()
            if not ups_data:
                logger.error("Failed to get UPS data")
                return {}
            
            # Base data common to all templates
            now = datetime.now(get_timezone())
            logger.info(f"📧 Preparing email with timezone {get_timezone().zone}, time: {now}")
            
            # Get server_name from database
            server_name = "UPS Monitor"  # Default fallback
            try:
                # Use direct database access
                from core.db.orm.orm_ups_initial_setup import init_model
                
                # Initialize the model directly
                InitialSetupModel = init_model(db.Model, get_timezone())
                
                # Get server name directly from the model
                server_name = InitialSetupModel.get_server_name()
                logger.debug(f"Using server name from database: {server_name}")
            except Exception as e:
                logger.error(f"Failed to get server name from database: {str(e)}")
                # Continue with default server_name instead of raising exception
                logger.info(f"Using fallback server name: {server_name}")
            
            base_data = {
                'event_date': now.strftime('%Y-%m-%d'),
                'event_time': now.strftime('%H:%M:%S'),
                'ups_model': getattr(ups_data, 'device_model', 'N/A'),
                'ups_host': ups_name,
                'ups_status': ups_data.ups_status,
                'current_year': now.year,
                'is_test': False,
                'server_name': server_name  # Add server_name from database
            }
            
            # Add specific data based on the event type
            if event_type in ['ONBATT', 'ONLINE', 'LOWBATT', 'SHUTDOWN']:
                # Format battery charge
                battery_charge = f"{ups_data.battery_charge:.1f}%" if ups_data.battery_charge else "N/A"
                
                # Calculate runtime estimate with fallbacks
                runtime_estimate = "N/A"
                
                # First try: Use battery_runtime directly
                if hasattr(ups_data, 'battery_runtime') and ups_data.battery_runtime:
                    runtime_estimate = format_runtime(ups_data.battery_runtime)
                    logger.debug(f"Using battery_runtime for runtime_estimate: {runtime_estimate}")
                
                # Second try: Use battery_runtime_low if available
                elif hasattr(ups_data, 'battery_runtime_low') and ups_data.battery_runtime_low:
                    runtime_estimate = format_runtime(ups_data.battery_runtime_low)
                    logger.debug(f"Using battery_runtime_low for runtime_estimate: {runtime_estimate}")
                
                # Third try: Estimate from battery charge (1% = 1 minute, rough approximation)
                elif ups_data.battery_charge and ups_data.battery_charge > 0:
                    runtime_estimate = estimate_runtime_from_charge(ups_data.battery_charge)
                    logger.debug(f"Estimated runtime from battery charge: {runtime_estimate}")
                
                # Update the data dictionary
                base_data.update({
                    'battery_charge': battery_charge,
                    'input_voltage': f"{ups_data.input_voltage:.1f}V" if ups_data.input_voltage else "N/A",
                    'battery_voltage': f"{ups_data.battery_voltage:.1f}V" if ups_data.battery_voltage else "N/A",
                    'runtime_estimate': runtime_estimate,
                    'battery_duration': get_battery_duration()
                })
            
            if event_type == 'REPLBATT':
                base_data.update({
                    'battery_age': get_battery_age(),
                    'battery_efficiency': calculate_battery_efficiency(),
                    'battery_capacity': f"{ups_data.battery_charge:.1f}%" if ups_data.battery_charge else "N/A",
                    'battery_voltage': f"{ups_data.battery_voltage:.1f}V" if ups_data.battery_voltage else "N/A"
                })
            
            if event_type in ['NOCOMM', 'COMMBAD', 'COMMOK']:
                base_data.update({
                    'last_known_status': get_last_known_status(),
                    'comm_duration': get_comm_duration()
                })
                # Add battery data only for COMMOK
                if event_type == 'COMMOK':
                    base_data.update({
                        'battery_charge': f"{ups_data.battery_charge:.1f}%" if ups_data.battery_charge else "N/A",
                        'battery_voltage': f"{ups_data.battery_voltage:.1f}V" if ups_data.battery_voltage else "N/A"
                    })
            
            logger.debug(f"Template data prepared for {event_type}: {base_data}")
            return base_data
        
        except Exception as e:
            logger.error(f"Error preparing template data: {str(e)}")
            return {}

    @staticmethod
    def send_notification(event_type: str, event_data: dict) -> tuple[bool, str]:
        """Send email notification for UPS event"""
        try:
            logger.info(f"📅 Sending scheduled report...")
            
            # Get timezone from Flask app context
            current_tz = get_timezone()
            if not current_tz:
                logger.error("Cannot access CACHE_TIMEZONE to send notification")
                return False, "Cannot access timezone from application context"
                
            logger.debug(f"🔍 Scheduler using timezone: {current_tz.zone}")
            logger.info(f"Sending notification for event type: {event_type}")
            
            # Check SECRET_KEY status
            from core.mail.mail import SECRET_KEY
            logger.debug(f"SECRET_KEY status in send_notification: {'[SET]' if SECRET_KEY else '[MISSING]'}")
            logger.debug(f"SECRET_KEY first bytes: {SECRET_KEY[:5] if SECRET_KEY else 'None'}")
            
            # Check that event_data is a dictionary
            if isinstance(event_data, dict):
                data_for_template = event_data
            else:
                # If it's not a dictionary, try to convert it
                data_for_template = event_data.to_dict() if hasattr(event_data, "to_dict") else {
                    k: v for k, v in event_data.__dict__.items() 
                    if not k.startswith('_')
                } if hasattr(event_data, "__dict__") else {}

            logger.debug(f"Template data prepared for {event_type}: {data_for_template}")

            # Get notification settings
            # Use the model from db.ModelClasses
            NotificationSettings = get_notification_settings_model()
            logger.debug(f"NotificationSettings model: {'Available' if NotificationSettings else 'Not available'}")
            
            # Check if NotificationSettings model is available
            if not NotificationSettings:
                logger.error("NotificationSettings model is not available")
                return False, "Notification settings model is not available"
                
            # Now safe to access query
            notification_settings = NotificationSettings.query.filter_by(event_type=event_type).first()
            if not notification_settings:
                logger.warning("No notification settings found")
                return False, "No notification settings found"

            # Ignore enabled check if it's a test
            if not notification_settings.enabled and not data_for_template.get('is_test', False):
                logger.info("Notifications are disabled")
                return False, "Notifications are disabled"

            # Check if this event type should be notified
            event_enabled = getattr(notification_settings, f"notify_{event_type.lower()}", True)
            if not event_enabled and not data_for_template.get('is_test', False):
                logger.info(f"Notifications for {event_type} are disabled")
                return False, f"Notifications for {event_type} are disabled"

            # Get the email configuration based on id_email if present, otherwise use default
            mail_config = None
            
            # Check if id_email is provided in the test data
            test_id_email = data_for_template.get('id_email')
            
            if test_id_email and data_for_template.get('is_test', False):
                mail_config = get_mail_config_model().query.get(test_id_email)
                if not mail_config:
                    logger.warning(f"Email configuration with ID {test_id_email} not found, falling back to notification settings")
                else:
                    logger.info(f"Using email configuration with ID {test_id_email} for test")
                    # Check if the configuration is enabled
                    if not mail_config.enabled:
                        logger.warning(f"Email configuration with ID {test_id_email} is disabled, but will use it anyway for test")
                        # For tests, we use the configuration even if it's disabled
            
            # If no mail_config from test data, use the one from notification settings
            if not mail_config and notification_settings.id_email:
                logger.debug(f"Getting mail config with ID {notification_settings.id_email} from notification settings")
                mail_config = get_mail_config_model().query.filter_by(id=notification_settings.id_email).first()
                if not mail_config:
                    logger.warning(f"Email configuration with ID {notification_settings.id_email} not found, falling back to default")
            
            # If no specific email config found or specified, use default
            if not mail_config:
                logger.debug("Attempting to get default mail config")
                mail_config = get_mail_config_model().query.filter_by(is_default=True).first() or get_mail_config_model().query.first()
                if mail_config:
                    logger.debug(f"Using default mail config with ID {mail_config.id}")
            
            # For tests, ignore the enabled check
            if not mail_config or (not mail_config.enabled and not data_for_template.get('is_test', False)):
                logger.info("Email configuration not found or disabled")
                return False, "Email configuration not found or disabled"

            logger.debug(f"Using mail config: ID={mail_config.id}, provider={mail_config.provider}, server={mail_config.smtp_server}")
            logger.debug(f"Mail config has password set: {'Yes' if mail_config.password else 'No'}")
            
            # Check if the mail config has a valid password
            if not mail_config.password:
                logger.error("Mail config has no password set")
                return False, "Mail configuration has no password set"
            
            # Try to access the password which will test decryption
            try:
                password_value = mail_config.password
                logger.debug(f"Password access successful, length: {len(password_value) if password_value else 0}")
            except Exception as pwd_err:
                logger.error(f"Failed to access password (likely encryption issue): {str(pwd_err)}")
                logger.error(f"Traceback: {traceback.format_exc()}")
                return False, f"Failed to decrypt email password: {str(pwd_err)}"

            # List of providers that have issues with base64 inline images and modern CSS
            problematic_providers = ['gmail', 'yahoo', 'outlook', 'office365']
            provider = mail_config.provider.lower() if mail_config.provider else ''
            
            # Add is_problematic_provider to template data
            data_for_template['is_problematic_provider'] = provider in problematic_providers
            
            # Get email template
            template = EmailNotifier.TEMPLATE_MAP.get(event_type)
            if not template:
                logger.error(f"No template found for event type: {event_type}")
                return False, f"No template found for event type: {event_type}"

            # Adjust template path
            if not template.startswith("dashboard/"):
                template = f"dashboard/{template}"

            # Add current year to template data
            data_for_template['current_year'] = datetime.now(get_timezone()).year
            
            # Render template
            try:
                html_content = render_template(template, **data_for_template)
                logger.debug(f"Template rendering successful, length: {len(html_content)}")
            except Exception as e:
                logger.error(f"Error rendering template: {str(e)}")
                logger.error(f"Traceback: {traceback.format_exc()}")
                return False, f"Error rendering template: {template}"

            # Determine if we should use SMTP settings from event_data (for tests)
            # or from the mail_config (for normal notifications)
            use_event_data_settings = data_for_template.get('is_test', False) and all(
                key in data_for_template for key in ['smtp_server', 'smtp_port', 'from_email']
            )
            
            if use_event_data_settings:
                logger.debug("Using SMTP settings from event_data for test")
                smtp_settings = {
                    'host': data_for_template['smtp_server'],
                    'port': data_for_template['smtp_port'],
                    'username': data_for_template.get('username', data_for_template['from_email']),
                    'password': mail_config.password,  # Still use the password from the database
                    'use_tls': data_for_template.get('tls', True),
                    'from_addr': data_for_template['from_email'],
                    'provider': data_for_template.get('provider', ''),
                    'tls_starttls': data_for_template.get('tls_starttls', True)
                }
            else:
                logger.debug("Using SMTP settings from mail_config")
                smtp_settings = {
                    'smtp_server': mail_config.smtp_server,
                    'smtp_port': mail_config.smtp_port,
                    'username': mail_config.username,
                    'password': mail_config.password,
                    'from_email': mail_config.from_email,  # Use from_email property instead of username
                    'provider': mail_config.provider,
                    'tls': mail_config.tls,
                    'tls_starttls': mail_config.tls_starttls
                }
                
            logger.debug(f"SMTP settings: host={smtp_settings.get('smtp_server', smtp_settings.get('host', 'N/A'))}, port={smtp_settings.get('smtp_port', smtp_settings.get('port', 'N/A'))}")
            logger.debug(f"SMTP settings: username={smtp_settings.get('username', 'N/A')}, has_password={'Yes' if smtp_settings.get('password') else 'No'}")
            logger.debug(f"SMTP settings: provider={smtp_settings.get('provider', 'N/A')}")

            # Determine recipient email address
            # First check if to_email is in event_data
            to_email = data_for_template.get('to_email')
            # If not, check if mail_config has to_email
            if not to_email or to_email.strip() == '':
                to_email = mail_config.to_email
            # If still not available, use the username as fallback
            if not to_email or to_email.strip() == '':
                to_email = mail_config.username
                
            logger.debug(f"Using recipient email: {to_email}")

            # Get server name from template data
            server_name = data_for_template.get('server_name', '')
            
            # Prepare email subject with server name
            if server_name:
                subject = f"{server_name} - UPS Event: {event_type}"
            else:
                subject = f"UPS Event: {event_type}"

            # Send email
            logger.debug(f"Calling send_email function with subject: {subject}")
            success, message = send_email(
                to_addr=[to_email],  # Send to the specified recipient
                subject=subject,
                html_content=html_content,
                smtp_settings=smtp_settings
            )
            
            logger.debug(f"Send email result: success={success}, message={message}")

            return success, message

        except Exception as e:
            logger.error(f"Error sending notification: {str(e)}", exc_info=True)
            logger.error(f"Traceback: {traceback.format_exc()}")
            return False, str(e)

def handle_notification(event_data):
    """
    Handles the email notification for an UPS event
    Args:
        event_data: Dict containing event data (ups, event)
    """
    try:
        event_type = event_data.get('event')
        ups = event_data.get('ups')
        
        logger.info(f"Processing notification for event {event_type} from UPS {ups}")
        
        # Ensure mail models are available before proceeding
        # Use the model from db.ModelClasses
        NotificationSettings = get_notification_settings_model()
        if NotificationSettings is None:
            logger.error("❌ Cannot send notification: NotificationSettings model not available")
            logger.error("⚠️ This usually means the database is not fully initialized yet")
            return
            
        MailConfig = get_mail_config_model()
        if MailConfig is None:
            logger.error("❌ Cannot send notification: MailConfig model not available")
            logger.error("⚠️ This usually means the database is not fully initialized yet")
            return
        
        # Check if notifications are enabled for this event
        notify_setting = NotificationSettings.query.filter_by(event_type=event_type).first()
        if not notify_setting or not notify_setting.enabled:
            logger.info(f"Notifications disabled for event type: {event_type}")
            return
        
        # Get the email configuration based on the notification settings
        mail_config = None
        if notify_setting.id_email:
            mail_config = get_mail_config_model().query.get(notify_setting.id_email)
            logger.info(f"Using email configuration with ID {notify_setting.id_email} for event {event_type}")
        
        # If no specific email config found, use default
        if not mail_config:
            mail_config = get_mail_config_model().query.filter_by(is_default=True).first() or get_mail_config_model().query.first()
            logger.info(f"Using default email configuration for event {event_type}")
            
        if not mail_config or not mail_config.enabled:
            logger.info("Email configuration not found or disabled")
            return
            
        # Get the template data using existing APIs
        notification_data = EmailNotifier.get_template_data(event_type, ups)
        if not notification_data:
            logger.error("Failed to get template data")
            return
            
        # Add to_email to notification data if available
        if mail_config.to_email and mail_config.to_email.strip() != '':
            notification_data['to_email'] = mail_config.to_email
        
        # Add id_email to notification data
        notification_data['id_email'] = mail_config.id
            
        # Send the notification using the correct template
        success, message = EmailNotifier.send_notification(
            event_type,
            notification_data
        )
        
        if not success:
            logger.error(f"Failed to send notification: {message}")
            return
            
        logger.info("Notification sent successfully")
        
    except Exception as e:
        logger.error(f"Error handling notification: {str(e)}", exc_info=True)

def init_notification_settings():
    """Initialize notification settings"""
    try:
        # Ensure all tables exist
        db.create_all()
        
        # Initialize notifications
        # Use the model from db.ModelClasses
        NotificationSettings = get_notification_settings_model()
        settings = NotificationSettings.query.all()
        if not settings:
            for event_type in EmailNotifier.TEMPLATE_MAP.keys():
                setting = NotificationSettings(event_type=event_type, enabled=False)
                db.session.add(setting)
            db.session.commit()
            logger.info("Notification settings initialized")
            
    except Exception as e:
        logger.error(f"Error initializing notification settings: {str(e)}")
        db.session.rollback()

def get_notification_settings():
    """Get all notification settings"""
    try:
        # Use the model from db.ModelClasses
        NotificationSettings = get_notification_settings_model()
        # Try to get all notification settings
        return NotificationSettings.query.all()
    except Exception as e:
        logger.error(f"Error retrieving notification settings: {str(e)}")
        return []

def test_notification(event_type, test_data=None):
    """
    Function to test email notifications with simulated data
    Args:
        event_type: Event type to test
        test_data: Optional dictionary with test parameters
    Returns:
        tuple: (success, message)
    """
    global _last_test_notification_time
    
    # Debounce protection - prevent multiple rapid calls
    current_time = time.time()
    if current_time - _last_test_notification_time < _test_notification_cooldown:
        logger.warning(f"Test notification called too soon after previous call ({current_time - _last_test_notification_time:.2f}s < {_test_notification_cooldown}s)")
        return False, "Please wait a few seconds before sending another test notification"
    
    _last_test_notification_time = current_time
    
    try:
        # Get real UPS data first
        ups_data = get_ups_data() or {}
        
        # Get server_name from database
        server_name = "UPS Monitor"  # Default fallback
        try:
            # Use direct database access
            from core.db.orm.orm_ups_initial_setup import init_model
            
            # Initialize the model directly
            InitialSetupModel = init_model(db.Model, get_timezone())
            
            # Get server name directly from the model
            server_name = InitialSetupModel.get_server_name()
            logger.debug(f"Using server name for test notification: {server_name}")
        except Exception as e:
            logger.error(f"Failed to get server name from database for test: {str(e)}")
            # Continue with default server_name instead of raising exception
            logger.info(f"Using fallback server name: {server_name}")
        
        # Base data common to all events
        base_data = {
            'device_model': getattr(ups_data, 'device_model', 'N/A'),
            'device_serial': getattr(ups_data, 'device_serial', 'Unknown'),
            'ups_status': getattr(ups_data, 'ups_status', 'OL'),
            'battery_charge': getattr(ups_data, 'battery_charge', '100'),
            'battery_voltage': getattr(ups_data, 'battery_voltage', '13.2'),
            'battery_runtime': getattr(ups_data, 'battery_runtime', '2400'),
            'input_voltage': getattr(ups_data, 'input_voltage', '230.0'),
            'ups_load': getattr(ups_data, 'ups_load', '35'),
            'ups_realpower': getattr(ups_data, 'ups_realpower', '180'),
            'ups_temperature': getattr(ups_data, 'ups_temperature', '32.5'),
            # Add a flag to indicate that it's a test
            'is_test': True,
            'event_date': datetime.now(get_timezone()).strftime('%Y-%m-%d'),
            'event_time': datetime.now(get_timezone()).strftime('%H:%M:%S'),
            'battery_duration': get_battery_duration(),
            'server_name': server_name  # Add server_name from database
        }

        # Specific data for event type
        event_specific_data = {
            'ONLINE': {
                'ups_status': 'OL',
                'battery_runtime': '300',
                'input_voltage': '230.0',
                'input_transfer_reason': 'Utility power restored'
            },
            'ONBATT': {
                'ups_status': 'OB',
                'input_voltage': '0.0',
                'battery_runtime': '1800',
                'input_transfer_reason': 'Line power fail'
            },
            'LOWBATT': {
                'ups_status': 'OB LB',
                'battery_charge': '10',
                'battery_runtime': '180',
                'battery_runtime': '1200',
                'input_voltage': '0.0'
            },
            'COMMOK': {
                'ups_status': 'OL',
                'input_transfer_reason': 'Communication restored'
            },
            'COMMBAD': {
                'ups_status': 'OL COMMOK',
                'input_transfer_reason': 'Communication failure'
            },
            'SHUTDOWN': {
                'ups_status': 'OB LB',
                'battery_charge': '5',
                'battery_runtime': '60',
                'battery_runtime': '1500',
                'ups_timer_shutdown': '30',
                'input_voltage': '0.0'
            },
            'REPLBATT': {
                'ups_status': 'OL RB',
                'battery_date': '2020-01-01',
                'battery_mfr_date': '2020-01-01',
                'battery_type': 'Li-ion',
                'battery_voltage_nominal': '12.0'
            },
            'NOCOMM': {
                'ups_status': 'OL COMMOK',
                'input_transfer_reason': 'Communication lost'
            },
            'NOPARENT': {
                'ups_status': 'OL',
                'input_transfer_reason': 'Process terminated'
            }
        }

        # Combine base data with specific event data
        event_data = base_data.copy()
        if event_type in event_specific_data:
            event_data.update(event_specific_data[event_type])
        
        # If test_data is provided, update with those values
        if test_data:
            # Add id_email to the test data if provided
            if 'id_email' in test_data:
                event_data['id_email'] = test_data['id_email']
                # Verify that the email configuration exists
                mail_config = get_mail_config_model().query.get(test_data['id_email'])
                if not mail_config:
                    return False, f"Email configuration with ID {test_data['id_email']} not found"
            
            # Add to_email if provided
            if 'to_email' in test_data:
                event_data['to_email'] = test_data['to_email']
            
            # Mark as test
            event_data['is_test'] = True

        # Create a DotDict object with test data
        test_data_obj = DotDict(event_data)
            
        # Use the existing handle_notification function to send the test email
        success, message = EmailNotifier.send_notification(event_type, test_data_obj)
        
        return success, message

    except Exception as e:
        logger.error(f"Error testing notification: {str(e)}")
        return False, str(e)

def test_notification_settings():
    """Test the email settings by sending a test email"""
    try:
        logger.info("📊 Testing Report Settings...")
        
        # Get the mail configuration from the database
        mail_config = get_mail_config_model().query.first()
        if not mail_config:
            logger.error("❌ No mail configuration found in database")
            return False, "No mail configuration found in database"
            
        # Check if required fields are present
        if not mail_config.smtp_server or not mail_config.smtp_port or not mail_config.from_email:
            logger.error("❌ Missing required mail configuration fields")
            missing_fields = []
            if not mail_config.smtp_server:
                missing_fields.append("smtp_server")
            if not mail_config.smtp_port:
                missing_fields.append("smtp_port")
            if not mail_config.from_email:
                missing_fields.append("from_email")
            return False, f"Missing required fields: {', '.join(missing_fields)}"
            
        # Get UPS data for the test email
        ups_data = get_ups_data() or {}
        
        # Get server_name from database
        server_name = None
        try:
            # Use direct database access
            from core.db.orm.orm_ups_initial_setup import init_model
            
            # Initialize the model directly
            InitialSetupModel = init_model(db.Model, get_timezone())
            
            # Get server name directly from the model
            server_name = InitialSetupModel.get_server_name()
            logger.debug(f"Using server name for test notification settings: {server_name}")
        except Exception as e:
            logger.error(f"Failed to get server name from database for test settings: {str(e)}")
            raise  # Re-raise to halt execution if server_name is required
        
        # Prepare test data
        test_data = {
            'ups_model': get_ups_model(),
            'ups_serial': getattr(ups_data, 'device_serial', 'Unknown'),
            'test_date': datetime.now(get_timezone()).strftime('%Y-%m-%d %H:%M:%S'),
            'current_year': datetime.now(get_timezone()).year,
            'is_test': True,  # Mark this as a test
            'smtp_server': mail_config.smtp_server,
            'smtp_port': mail_config.smtp_port,
            'username': mail_config.username,
            'provider': mail_config.provider,
            'tls': mail_config.tls,
            'tls_starttls': mail_config.tls_starttls,
            'server_name': server_name  # Add server_name from database
        }
        
        logger.debug(f"🔍 Report will use timezone: {get_timezone().zone}")
        logger.debug(f"📧 Test data: {test_data}")
        
        # Create a test event type for the general test
        test_event_type = "TEST"
        
        # Make sure we have a template mapping for TEST
        if "TEST" not in EmailNotifier.TEMPLATE_MAP:
            EmailNotifier.TEMPLATE_MAP["TEST"] = 'mail/test_template.html'
        
        # Make sure we have notification settings for TEST
        with data_lock:
            test_setting = get_notification_settings_model().query.filter_by(event_type=test_event_type).first()
            if not test_setting:
                test_setting = get_notification_settings_model()(event_type=test_event_type, enabled=True)
                db.session.add(test_setting)
                db.session.commit()
        
        # Send the test email using the correct parameters
        success, message = EmailNotifier.send_notification(test_event_type, test_data)
        
        if success:
            # Update the test status
            with data_lock:
                if mail_config:
                    db.session.commit()
        
        return success, message

    except Exception as e:
        logger.error(f"Error testing notification: {str(e)}", exc_info=True)
        return False, str(e)

def format_runtime(seconds):
    """Format the runtime in a readable format"""
    try:
        # Handle empty, null, or non-numeric values
        if seconds is None or seconds == "":
            return "N/A"
            
        # Convert to float and validate
        try:
            seconds = float(seconds)
        except (ValueError, TypeError):
            logger.warning(f"Invalid runtime value: {seconds}, cannot convert to float")
            return "N/A"
            
        # Ensure seconds is positive
        if seconds <= 0:
            logger.debug(f"Non-positive runtime value: {seconds}, returning N/A")
            return "N/A"
            
        # Format based on duration
        if seconds < 60:
            return f"{int(seconds)} sec"
            
        minutes = int(seconds / 60)
        if minutes < 60:
            return f"{minutes} min"
            
        hours = minutes // 60
        mins = minutes % 60
        return f"{hours}h {mins}m"
    except Exception as e:
        logger.error(f"Error formatting runtime: {str(e)}")
        return "N/A"

def get_battery_duration():
    """Calculate the time passed since the last battery event"""
    try:
        # Get the UPSEvent model from ModelClasses
        if not hasattr(db, 'ModelClasses') or not hasattr(db.ModelClasses, 'UPSEvent'):
            logger.warning("UPSEvent model not available through ModelClasses")
            return "N/A"
            
        UPSEvent = db.ModelClasses.UPSEvent
        
        # For ONLINE, find the last complete ONBATT->ONLINE cycle
        last_online = UPSEvent.query.filter(
            UPSEvent.event_type == 'ONLINE'
        ).order_by(UPSEvent.timestamp_utc.desc()).first()
        
        if last_online:
            # Find the ONBATT that precedes this ONLINE
            last_onbatt = UPSEvent.query.filter(
                UPSEvent.event_type == 'ONBATT',
                UPSEvent.timestamp_utc < last_online.timestamp_utc
            ).order_by(UPSEvent.timestamp_utc.desc()).first()
            
            if last_onbatt:
                duration = last_online.timestamp_utc - last_onbatt.timestamp_utc
                seconds = duration.total_seconds()
                if seconds < 60:
                    return f"{int(seconds)} sec"
                minutes = int(seconds / 60)
                return f"{minutes} min"
        
        return "N/A"
    except Exception as e:
        logger.error(f"Error calculating battery duration: {str(e)}")
        return "N/A"

def get_last_known_status():
    """Get the last known UPS status"""
    try:
        ups_data = get_ups_data()
        if ups_data and ups_data.ups_status:
            return ups_data.ups_status
            
        # Get the UPSEvent model from ModelClasses
        if not hasattr(db, 'ModelClasses') or not hasattr(db.ModelClasses, 'UPSEvent'):
            logger.warning("UPSEvent model not available through ModelClasses")
            return "Unknown"
            
        UPSEvent = db.ModelClasses.UPSEvent
            
        # Fallback on events if get_ups_data doesn't have the status
        last_event = UPSEvent.query.order_by(UPSEvent.timestamp_utc.desc()).first()
        if last_event and last_event.ups_status:
            return last_event.ups_status
            
        return "Unknown"
    except Exception as e:
        logger.error(f"Error getting last known status: {str(e)}")
        return "Unknown"

def get_comm_duration():
    """Calculate the duration of the communication interruption"""
    try:
        # Get the UPSEvent model from ModelClasses
        if not hasattr(db, 'ModelClasses') or not hasattr(db.ModelClasses, 'UPSEvent'):
            logger.warning("UPSEvent model not available through ModelClasses")
            return "N/A"
            
        UPSEvent = db.ModelClasses.UPSEvent
        
        # Find the last COMMBAD/NOCOMM event
        last_comm_fail = UPSEvent.query.filter(
            UPSEvent.event_type.in_(['COMMBAD', 'NOCOMM'])
        ).order_by(UPSEvent.timestamp_utc.desc()).first()
        
        if last_comm_fail:
            # Get timezone from Flask app context
            current_tz = get_timezone()
            if not current_tz:
                logger.error("Cannot access CACHE_TIMEZONE to calculate comm duration")
                return "N/A"
                
            # Calculate the duration until the current event
            now = datetime.now(current_tz)
            duration = now - last_comm_fail.timestamp_utc
            seconds = duration.total_seconds()
            
            if seconds < 60:
                return f"{int(seconds)} sec"
            minutes = int(seconds / 60)
            return f"{minutes} min"
        
        return "N/A"
    except Exception as e:
        logger.error(f"Error calculating comm duration: {str(e)}")
        return "N/A"

def get_battery_age():
    """Calculate the battery age"""
    try:
        ups_data = get_ups_data()
        if ups_data and ups_data.battery_mfr_date:  # Use battery_mfr_date instead of battery_date
            try:
                # Get timezone from Flask app context
                current_tz = get_timezone()
                if not current_tz:
                    logger.error("Cannot access CACHE_TIMEZONE to calculate battery age")
                    return "N/A"
                    
                install_date = datetime.strptime(ups_data.battery_mfr_date, '%Y/%m/%d')
                age = datetime.now(current_tz) - install_date
                return f"{age.days // 365} years and {(age.days % 365) // 30} months"
            except ValueError as e:
                logger.error(f"Error parsing battery date: {str(e)}")
                return "N/A"
    except Exception as e:
        logger.error(f"Error calculating battery age: {str(e)}")
    return "N/A"

def calculate_battery_efficiency():
    """Calculate the battery efficiency based on runtime"""
    try:
        ups_data = get_ups_data()
        if ups_data:
            # Calculate the efficiency based on runtime and current charge
            runtime = float(ups_data.battery_runtime or 0)
            charge = float(ups_data.battery_charge or 0)
            
            # A new UPS should have about 30-45 minutes of runtime at 100% charge
            nominal_runtime = 2700  # 45 minutes in seconds
            
            if charge > 0:
                # Normalize the runtime to 100% charge
                normalized_runtime = (runtime / charge) * 100
                efficiency = (normalized_runtime / nominal_runtime) * 100
                return f"{min(100, efficiency):.1f}%"
    except Exception as e:
        logger.error(f"Error calculating battery efficiency: {str(e)}")
    return "N/A"

def estimate_runtime_from_charge(charge_percent):
    """
    Estimate runtime based on battery charge percentage
    This is a fallback method when direct runtime data is not available
    
    Args:
        charge_percent: Battery charge percentage
        
    Returns:
        str: Estimated runtime in a readable format
    """
    try:
        if charge_percent is None or charge_percent == "":
            return "N/A"
            
        # Convert to float and validate
        try:
            charge = float(charge_percent)
            if isinstance(charge_percent, str) and charge_percent.endswith('%'):
                charge = float(charge_percent[:-1])  # Remove % if present
        except (ValueError, TypeError):
            logger.warning(f"Invalid charge value: {charge_percent}")
            return "N/A"
            
        # Ensure charge is within valid range
        if charge <= 0 or charge > 100:
            logger.warning(f"Charge out of range: {charge}")
            return "N/A"
            
        # Simple linear model: 1% charge = 1 minute runtime (very rough approximation)
        # For a more sophisticated model, we could use UPS specs or historical data
        minutes = int(charge)
        
        # Format based on duration
        if minutes < 60:
            return f"{minutes} min"
            
        hours = minutes // 60
        mins = minutes % 60
        return f"{hours}h {mins}m"
    except Exception as e:
        logger.error(f"Error estimating runtime from charge: {str(e)}")
        return "N/A"

def validate_emails(emails):
    """
    Validate email addresses
    Args:
        emails: List of email addresses or single email address
    Returns:
        List of valid email addresses
    """
    from email_validator import validate_email, EmailNotValidError
    
    if isinstance(emails, str):
        emails = [emails]
        
    valid_emails = []
    for email in emails:
        try:
            valid = validate_email(email.strip())
            valid_emails.append(valid.email)
        except EmailNotValidError as e:
            logger.warning(f"Invalid email: {email} - {str(e)}")
    return valid_emails

def get_current_email_settings():
    """
    Get configured email from mail settings
    
    Returns:
        str or None: The configured email address if available, or None if not configured
    """
    try:
        MailConfig = get_mail_config_model()
        if not MailConfig:
            logger.warning("MailConfig model not available")
            return None
            
        mail_config = MailConfig.get_default()
        if mail_config and getattr(mail_config, 'enabled', False):
            # Return the username as email address
            logger.debug(f"Using mail config: username={mail_config.username}, enabled={mail_config.enabled}")
            return mail_config.username
        elif mail_config:
            logger.debug(f"Mail config found but disabled: username={mail_config.username}, enabled={getattr(mail_config, 'enabled', False)}")
        else:
            logger.debug("No mail configuration found")
        return None
    except Exception as e:
        logger.error(f"Error getting email settings: {str(e)}", exc_info=True)
        return None

def interpret_email_error(error_message):
    """
    Interprets technical error messages and provides user-friendly versions
    
    Args:
        error_message (str): The original technical error message
        
    Returns:
        str: User-friendly error message
    """
    # Convert to lowercase for easier matching
    error_lower = error_message.lower()
    
    # UTF-8 decoding errors related to TLS
    if "utf-8" in error_lower and "decode" in error_lower and "invalid continuation byte" in error_lower:
        return "TLS Error"
    
    # Authentication errors with specific message for server not supporting authentication
    if "server does not support authentication" in error_lower:
        # If the message contains information about starttls, it's a STARTTLS issue
        if "starttls" in error_lower:
            return "STARTTLS Error"
        # If it mentions TLS, it's a TLS error
        elif "tls" in error_lower:
            return "TLS/SSL Error"
        # Otherwise, provide a generic message about enabling encryption
        elif ("tmp" in error_lower):
            return "Without encryption it does not work"
        return "Authentication Error"
    
    # TLS/SSL related errors
    if "cannot establish ssl connection" in error_lower:
        return "SSL Error"
    
    if "certificate verification failed" in error_lower:
        return "SSL Certificate Error"
    
    # STARTTLS errors
    if "starttls failed" in error_lower:
        return "STARTTLS Error"
    
    # Connection errors
    if "connection refused" in error_lower:
        return "Connection Error"
        
    if "network unreachable" in error_lower or "no route to host" in error_lower:
        return "Network Error"
    
    if "timeout" in error_lower:
        return "Timeout Error"
    
    # Authentication errors
    if "authentication failed" in error_lower or "auth failed" in error_lower:
        return "Authentication Error"
    
    # SMTP errors
    if "protocol error" in error_lower:
        return "SMTP Protocol Error"
    
    # Generic msmtp errors from temp files - often encryption related
    if "msmtp:" in error_lower and "tmp" in error_lower and "could not send mail" in error_lower:
        return "Configuration Error"
    
    # If no specific match, return a generic but improved message
    return f"Mail Error: {error_message}" 