import os
import re
from pathlib import Path
import pytz
from datetime import datetime
import logging
import sys

# Set up module path so it's available for import system
import os as _os
__path__ = [_os.path.dirname(_os.path.abspath(__file__))]

# Base directory of the application
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Directory for logs
LOG_DIR = os.path.join(BASE_DIR, 'logs')
os.makedirs(LOG_DIR, exist_ok=True)

# Main log file
LOG_FILE = os.path.join(LOG_DIR, 'system.log')

# Remove the creation of other log files
if not os.path.exists(LOG_FILE):
    with open(LOG_FILE, 'w') as f:
        f.write(f"Log file created on {datetime.now().isoformat()}\n")

# Add the logger for settings
logger = logging.getLogger('system')

# Store all settings in a dictionary for access by __getattr__
_ALL_SETTINGS = {}

# Initial empty encryption key value
# This MUST be replaced with the value from the environment variable or database
SECRET_KEY = None

def get_logger(category, name=None):
    """
    Return a logger for the given category.
    
    Args:
        category (str): The category of the logger.
        name (str, optional): If specified, a child logger will be created.
    
    Returns:
        logging.Logger: The configured logger for the category.
    """
    base_logger = logging.getLogger(category)
    if name:
        return base_logger.getChild(name)
    return base_logger

def parse_value(value):
    """Parse string value into appropriate type"""
    value = value.strip()
    
    # Remove comments
    if '#' in value:
        value = value.split('#')[0].strip()
    
    # Handle multiline strings between triple quotes
    if value.startswith('"""'):
        # Find the closing triple quotes
        end_pos = value.find('"""', 3)
        if end_pos != -1:
            # Return the content between the quotes
            return value[3:end_pos]
        # If no closing quotes found, treat as normal string
        return value.strip('"')
        
    # Boolean
    if value.lower() in ('true', 'false'):
        return value.lower() == 'true'
        
    # Integer
    try:
        if value.isdigit():
            return int(value)
    except ValueError:
        pass
        
    # Float
    try:
        if '.' in value:
            return float(value)
    except ValueError:
        pass
        
    # String (remove quotes if present)
    return value.strip('"\'')

def load_settings():
    """Load settings from config file"""
    global _ALL_SETTINGS
    
    # Definition of default values
    default_settings = {
        'DEBUG_MODE': 'development',
        'SERVER_PORT': 5050,
        'SERVER_HOST': '0.0.0.0',
        'CACHE_SECONDS': 60,
        'LOG_LEVEL': 'DEBUG',
        'LOG_FILE_ENABLED': True,
        'LOG_FORMAT': '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        'LOG_LEVEL_DEBUG': 'DEBUG, %(asctime)s - %(name)s - %(levelname)s - %(message)s',
        'LOG_LEVEL_INFO': 'INFO, %(asctime)s - %(name)s - %(levelname)s - %(message)s',
        'COMMAND_TIMEOUT': 10,
        'SSL_ENABLED': False,
    }
    
    settings = default_settings.copy()
    config_path = Path(__file__).parent.parent.parent / 'config' / 'settings.txt'
    base_path = Path(__file__).parent.parent.parent
    
    if not config_path.exists():
        logger.warning(f"Configuration file not found: {config_path}. Using default settings.")
    else:
        with open(config_path) as f:
            for line in f:
                line = line.strip()
                # Skip comments and empty lines
                if not line or line.startswith('#'):
                    continue
                    
                if '=' in line:
                    key, value = line.split('=', 1)
                    key = key.strip()
                    settings[key] = parse_value(value)
    
    # Validation of required variables
    required_vars = [
        'DB_NAME', 'INSTANCE_PATH',
    ]
    
    # These UPS configuration variables are now optional since they can be loaded from database
    # or other configuration sources
    optional_vars = [
        'UPS_HOST', 'UPS_NAME', 'UPS_USER', 'UPS_PASSWORD', 'UPS_COMMAND',
        'UPS_REALPOWER_NOMINAL', 'UPSCMD_COMMAND', 'UPSCMD_USER', 'UPSCMD_PASSWORD',
        'MSMTP_PATH', 'TLS_CERT_PATH',  # These are now loaded from paths.py
        'SSL_CERT', 'SSL_KEY',  # These are now loaded from paths.py
    ]
    
    missing_vars = [var for var in required_vars if var not in settings]
    if missing_vars:
        # Provide reasonable defaults for critical variables
        if 'DB_NAME' in missing_vars:
            settings['DB_NAME'] = 'nutify.db.sqlite'
            logger.warning(f"Using default DB_NAME: {settings['DB_NAME']}")
        
        if 'INSTANCE_PATH' in missing_vars:
            settings['INSTANCE_PATH'] = 'instance'
            logger.warning(f"Using default INSTANCE_PATH: {settings['INSTANCE_PATH']}")
        
        # Recalculate missing vars after providing defaults
        missing_vars = [var for var in required_vars if var not in settings]
        if missing_vars:
            raise ValueError(f"Missing required configuration variables: {', '.join(missing_vars)}")
    
    # Build absolute paths
    settings['INSTANCE_PATH'] = str(base_path / settings['INSTANCE_PATH'])
    settings['DB_PATH'] = str(base_path / settings['INSTANCE_PATH'] / settings['DB_NAME'])
    
    # Add DB_URI for SQLAlchemy
    settings['DB_URI'] = f"sqlite:///{settings['DB_PATH']}"
    
    # Create the instance directory if it doesn't exist
    instance_path = Path(settings['INSTANCE_PATH'])
    if not instance_path.exists():
        instance_path.mkdir(parents=True)
    
    # Store settings for __getattr__ access
    _ALL_SETTINGS = settings.copy()
    
    # Add SECRET_KEY to _ALL_SETTINGS
    _ALL_SETTINGS['SECRET_KEY'] = SECRET_KEY
    
    return settings

# Load settings into module namespace
globals().update(load_settings())

# Add SECRET_KEY to _ALL_SETTINGS
_ALL_SETTINGS['SECRET_KEY'] = SECRET_KEY

def init_application_timezone():
    """
    This function is kept for compatibility only.
    All timezone functionality is now handled by app.py with CACHE_TIMEZONE.
    
    Returns:
        tuple: (database_timezone, display_timezone) - Both pytz timezone objects
    """
    # Import the Flask current_app context
    from flask import current_app
    
    # For database operations, always use UTC
    db_timezone = pytz.UTC
    
    # For display, always use the global CACHE_TIMEZONE from app
    if not (current_app and hasattr(current_app, 'CACHE_TIMEZONE')):
        raise RuntimeError("CACHE_TIMEZONE not available. Application not properly initialized.")
        
    display_timezone = current_app.CACHE_TIMEZONE
    logger.info(f"🌏 Using display timezone from app.CACHE_TIMEZONE: {display_timezone.zone}")
    return (db_timezone, display_timezone)

def get_server_name():
    """
    Get the server name ONLY from the database with NO fallbacks
    
    Returns:
        str: The server name from the database
        
    Raises:
        Exception: If the server name cannot be retrieved from the database
    """
    global DB_URI
    
    # Import required modules for direct ORM access
    try:
        from flask import current_app
        from core.db.orm.orm_ups_initial_setup import init_model
        
        # Check if we're in an application context
        if current_app:
            # We're in an app context, can use current_app
            from core.db.ups import db
            
            # Get a logger for database operations
            db_logger = logging.getLogger('database')
            
            # Initialize the model properly with a logger object, not a lambda
            InitialSetupModel = init_model(db.Model, db_logger)
            
            # Get server name directly from the database using ORM
            server_name = InitialSetupModel.get_server_name()
            logger.debug(f"📋 Server name from database: {server_name}")
            
            # Return the server name, will raise an exception if not available
            return server_name
        else:
            # No app context available, create a temporary app and context
            logger.debug("Creating temporary app context to retrieve server name from database")
            from flask import Flask
            from flask_sqlalchemy import SQLAlchemy
            
            # Create temporary app
            temp_app = Flask(__name__)
            temp_app.config['SQLALCHEMY_DATABASE_URI'] = DB_URI
            temp_app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
            
            # Initialize SQLAlchemy with app
            temp_db = SQLAlchemy(temp_app)
            
            # Use app context to ensure ORM works correctly
            with temp_app.app_context():
                # Get a logger for database operations
                db_logger = logging.getLogger('database')
                
                # Initialize the model properly with a logger object, not a lambda
                InitialSetupModel = init_model(temp_db.Model, db_logger)
                
                # Get server name directly from the database using ORM
                server_name = InitialSetupModel.get_server_name()
                logger.debug(f"📋 Server name from database via temp context: {server_name}")
                
                return server_name
    except Exception as e:
        logger.error(f"Error getting server name from database: {str(e)}")
        # Raise the exception - no fallback allowed
        raise

def get_secret_key():
    """
    Get the secret key directly from app config, not from the database
    
    Returns:
        str: The secret key from app config
        
    Raises:
        RuntimeError: If no secret key is found
    """
    try:
        from flask import current_app
        
        # Check if we're in an application context
        if current_app and current_app.config.get('SECRET_KEY'):
            # Get directly from app config
            return current_app.config.get('SECRET_KEY')
        else:
            # No app context or no key in app config
            raise RuntimeError("SECRET_KEY is not available in Flask app config")
    except Exception as e:
        logger.error(f"Error getting secret key: {str(e)}")
        raise RuntimeError(f"SECRET_KEY is not available. Make sure it is set in environment variables.")

# For backward compatibility, maintain the old method name but now returns secret_key
def get_encryption_key():
    """
    Legacy function that now calls get_secret_key()
    
    Returns:
        str: The secret key from app config
        
    Raises:
        RuntimeError: If no secret key is found
    """
    return get_secret_key()

def get_ups_realpower_nominal():
    """
    Get UPS nominal power from database if possible
    
    Returns:
        int: The UPS nominal power value or None if not set
    """
    global DB_URI
    
    try:
        # First try to get from database if available
        from flask import current_app
        if current_app:
            from core.db.ups import db
            if hasattr(db, 'ModelClasses') and hasattr(db.ModelClasses, 'InitialSetup'):
                nominal_power = db.ModelClasses.InitialSetup.get_ups_realpower_nominal()
                if nominal_power is not None:
                    logger.debug(f"⚡ Using UPS nominal power from database: {nominal_power}")
                    return nominal_power
        else:
            # No app context available, try to create a temporary app and context
            try:
                logger.debug("Creating temporary app context to retrieve UPS nominal power from database")
                from flask import Flask
                from flask_sqlalchemy import SQLAlchemy
                from core.db.orm.orm_ups_initial_setup import init_model
                
                # Create temporary app
                temp_app = Flask(__name__)
                temp_app.config['SQLALCHEMY_DATABASE_URI'] = DB_URI
                temp_app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
                
                # Initialize SQLAlchemy with app
                temp_db = SQLAlchemy(temp_app)
                
                # Use app context to ensure ORM works correctly
                with temp_app.app_context():
                    # Get a logger for database operations
                    db_logger = logging.getLogger('database')
                    
                    # Initialize the model properly with a logger object, not a lambda
                    InitialSetupModel = init_model(temp_db.Model, db_logger)
                    
                    # Get UPS nominal power directly from the database using ORM
                    nominal_power = InitialSetupModel.get_ups_realpower_nominal()
                    if nominal_power is not None:
                        logger.debug(f"⚡ Using UPS nominal power from database via temp context: {nominal_power}")
                        return nominal_power
            except Exception as e:
                # If this fails during bootstrap, we'll log the error
                logger.debug(f"Could not create temporary app context: {str(e)}")
    except Exception as e:
        logger.debug(f"Error getting UPS nominal power from database: {str(e)}")
    
    # Return None to allow the calling code to use the actual UPS value
    # This ensures the UPS value takes priority over any default
    logger.debug(f"⚡ No UPS nominal power in database, returning None")
    return None

def parse_time_format(time_str, default_time=None):
    """
    Parse a time string in various formats and return a time object.
    
    Args:
        time_str: String representing time in various formats
        default_time: Default time to return if parsing fails (None for current time)
    
    Returns:
        time object
    """
    if not time_str:
        if default_time is None:
            return datetime.now().time()
        return default_time
        
    # Try different time formats
    formats = [
        '%H:%M',       # 24-hour format (13:30)
        '%I:%M %p',    # 12-hour format with AM/PM (1:30 PM)
        '%I:%M%p',     # 12-hour without space (1:30PM)
        '%H.%M',       # 24-hour with dot (13.30)
        '%I.%M %p',    # 12-hour with dot (1.30 PM)
        '%I:%M %P',    # 12-hour with lowercase am/pm (1:30 pm)
        '%I.%M%p',     # 12-hour with dot without space (1.30PM)
    ]
    
    for fmt in formats:
        try:
            return datetime.strptime(time_str, fmt).time()
        except ValueError:
            continue
    
    # If all formats fail, log and return default
    logger.error(f"Could not parse time string: {time_str}")
    
    if default_time is None:
        return datetime.now().time()
    return default_time

# Special handler for missing attributes in this module
def __getattr__(name):
    """
    Fallback for getting attributes that aren't directly defined.
    This allows accessing any setting without explicitly defining it.
    """
    global _ALL_SETTINGS
    
    # Handle special functions that should not be looked up in _ALL_SETTINGS
    if name in ('get_server_name', 'get_ups_realpower_nominal', 'get_encryption_key'):
        logger.error(f"Attempted to access function '{name}' via __getattr__. This should be imported directly.")
        return lambda: None  # Return a no-op function
        
    if name in _ALL_SETTINGS:
        return _ALL_SETTINGS[name]
    
    # Don't log errors for special Python attributes like __path__, __all__, etc.
    if name.startswith('__') and name.endswith('__'):
        return None
    
    # For critical settings that should use getter functions
    critical_db_settings = ['SERVER_NAME', 'UPS_REALPOWER_NOMINAL']
    if name in critical_db_settings:
        logger.error(f"Critical setting '{name}' must be retrieved from database using the appropriate function")
        raise Exception(f"Setting '{name}' must be retrieved from database, not from settings.txt")
    
    # Log error for missing attribute but don't raise an exception
    # This allows the application to start even with missing settings
    logger.error(f"Requested setting '{name}' not found in configuration")
    return None 