"""
Database Models Entry Point.
This module serves as the main entry point for initializing SQLAlchemy ORM models.
All model definitions have been moved to the core.db.orm package.
"""

from datetime import datetime
import pytz

# Import models from the orm package
from core.db.orm import (
    UPSEvent, VariableConfig, UPSCommand, UPSVariable, 
    MailConfig, NtfyConfig, NotificationSettings, ReportSchedule,
    InitialSetup, LoginAuth
    # UPSStaticData and UPSDynamicData are dynamically created by db_module.py
)

# Import the centralized ModelClasses
from core.db.model_classes import ModelClasses, init_model_classes

# Will be set in init_models
db = None

def get_db_timezone():
    """
    Returns UTC timezone for database operations.
    Database always stores dates in UTC, regardless of display timezone.
    
    Returns:
        function: A function that returns pytz.UTC
    """
    return lambda: pytz.UTC

def init_models(db_instance, timezone_getter=None):
    """
    Initialize the SQLAlchemy models
    
    Args:
        db_instance: SQLAlchemy database instance
        timezone_getter: Function to get the timezone (provided for backward compatibility but not used)
        
    Returns:
        dict: Dictionary of initialized model classes
    """
    global db
    db = db_instance
    
    # Check if we already have a ModelClasses namespace stored on db
    if hasattr(db, 'ModelClasses'):
        from core.logger import database_logger as logger
        logger.debug("📚 ORM models already initialized, returning existing models")
        # Return a dictionary of the existing models
        models_dict = {name: getattr(db.ModelClasses, name) for name in dir(db.ModelClasses) 
                      if not name.startswith('__')}
        return models_dict
    
    # Log key information
    from core.logger import database_logger as logger
    logger.info("📚 Initializing ORM models")
    
    # Initialize ModelClasses using UTC for database operations
    models = init_model_classes(db, get_db_timezone())
    
    # Create a dictionary of models for backwards compatibility
    models_dict = {
        'UPSEvent': models.UPSEvent,
        'VariableConfig': models.VariableConfig,
        'UPSCommand': models.UPSCommand,
        'UPSVariable': models.UPSVariable,
        'MailConfig': models.MailConfig,
        'NtfyConfig': models.NtfyConfig,
        'NotificationSettings': models.NotificationSettings,
        'ReportSchedule': models.ReportSchedule,
        'InitialSetup': models.InitialSetup,
        'LoginAuth': models.LoginAuth
    }
    
    # UPSStaticData and UPSDynamicData models are dynamically created and managed 
    # exclusively by db_module.py
    
    # Log summary
    logger.info(f"✅ Created {len(models_dict)} ORM models successfully")
    
    # Make models available via ModelClasses attached to db
    db.ModelClasses = models
    
    # Tables will be created automatically by Flask-SQLAlchemy
    # or by the database integrity system during application startup
    # EXCEPT for ups_static_data and ups_dynamic_data tables which are managed by db_module.py
    
    return models_dict 