"""
Initial Setup ORM Model.
This module defines the SQLAlchemy ORM model for the ups_initial_setup table.
Stores configuration variables collected during the setup wizard.
"""

from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text
from typing import Dict, Any, Optional
import pytz
from flask import current_app

# These will be set during initialization
db = None
logger = None

class InitialSetup:
    """Model for storing initial setup configuration from the wizard"""
    __tablename__ = 'ups_initial_setup'
    
    id = Column(Integer, primary_key=True)
    server_name = Column(String(100), nullable=False)
    timezone = Column(String(50), nullable=False, default='UTC')
    is_configured = Column(Boolean, default=False)
    ups_realpower_nominal = Column(Integer, nullable=True)
    # Store all datetimes in UTC
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(pytz.UTC))
    updated_at = Column(DateTime(timezone=True), 
                      default=lambda: datetime.now(pytz.UTC),
                      onupdate=lambda: datetime.now(pytz.UTC))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if logger:
            logger.debug(f"📅 Creating InitialSetup with timezone: {self.timezone}")
            logger.debug(f"📅 Created at will use UTC: {datetime.now(pytz.UTC)}")

    @classmethod
    def get_current_config(cls) -> Optional['InitialSetup']:
        """Get the current configuration or None if not configured"""
        return cls.query.filter_by(is_configured=True).first()

    @classmethod
    def is_setup_complete(cls) -> bool:
        """Check if initial setup has been completed"""
        return cls.query.filter_by(is_configured=True).count() > 0
        
    @classmethod
    def get_server_name(cls) -> str:
        """
        Get the server name ONLY from the database with NO fallbacks
        
        Returns:
            str: The server name from the database
            
        Raises:
            Exception: If the server name cannot be retrieved from the database
        """
        try:
            config = cls.get_current_config()
            if config and config.server_name:
                if logger:
                    logger.debug(f"🔍 get_server_name: Retrieved server_name '{config.server_name}' from current config")
                return config.server_name
            
            # If no config found or no server_name set, try any config
            any_config = cls.query.first()
            if any_config and any_config.server_name:
                if logger:
                    logger.debug(f"🔍 get_server_name: Retrieved server_name '{any_config.server_name}' from first config")
                return any_config.server_name
                
            # No configurations found, raise exception
            if logger:
                logger.error("🔍 get_server_name: No config found in database")
            raise Exception("No server_name found in database")
        except Exception as e:
            if logger:
                logger.error(f"Error retrieving server name from database: {str(e)}")
            raise Exception(f"Failed to retrieve server name from database: {str(e)}")
    
    @classmethod
    def get_cache_seconds(cls) -> int:
        """
        Get the cache seconds. Always returns 60 seconds.
        
        Returns:
            int: Always 60 seconds
        """
        return 60
    
    @classmethod
    def get_timezone(cls) -> str:
        """
        Get the timezone from the database. No fallbacks provided.
        
        Returns:
            str: The timezone from the database, or raises an exception
        
        Raises:
            Exception: If no timezone is found in the database
        """
        try:
            config = cls.get_current_config()
            if config and config.timezone:
                return config.timezone
            
            # If no config found or no timezone set, try any config
            any_config = cls.query.first()
            if any_config and any_config.timezone:
                return any_config.timezone
                
            # No configurations found, raise exception
            if logger:
                logger.error("No timezone found in database")
            raise Exception("No timezone found in database")
        except Exception as e:
            if logger:
                logger.error(f"Error retrieving timezone from database: {str(e)}")
            raise Exception(f"Failed to retrieve timezone from database: {str(e)}")
    
    @classmethod
    def utc_to_local(cls, utc_dt):
        """
        Convert a UTC datetime to the configured local timezone.
        
        Args:
            utc_dt: UTC datetime object
            
        Returns:
            datetime: Local timezone datetime object
        """
        if utc_dt is None:
            return None
            
        # Ensure datetime has UTC timezone
        if utc_dt.tzinfo is None:
            utc_dt = pytz.UTC.localize(utc_dt)
        elif utc_dt.tzinfo != pytz.UTC:
            utc_dt = utc_dt.astimezone(pytz.UTC)
            
        # Convert to local timezone using app.CACHE_TIMEZONE
        return utc_dt.astimezone(current_app.CACHE_TIMEZONE)
    
    @classmethod
    def local_to_utc(cls, local_dt):
        """
        Convert a local timezone datetime to UTC.
        
        Args:
            local_dt: Local timezone datetime object
            
        Returns:
            datetime: UTC datetime object
        """
        if local_dt is None:
            return None
            
        # If datetime has no timezone, assume it's in local timezone from app.CACHE_TIMEZONE
        if local_dt.tzinfo is None:
            local_dt = current_app.CACHE_TIMEZONE.localize(local_dt)
            
        # Convert to UTC
        return local_dt.astimezone(pytz.UTC)

    @classmethod
    def get_ups_realpower_nominal(cls) -> Optional[int]:
        """
        Get the UPS nominal power from the database.
        
        Returns:
            int: The UPS nominal power in Watts, or None if not set
        """
        try:
            config = cls.get_current_config()
            if config and config.ups_realpower_nominal:
                return config.ups_realpower_nominal
            
            # If no config found or no nominal power set, try any config
            any_config = cls.query.first()
            if any_config and any_config.ups_realpower_nominal:
                return any_config.ups_realpower_nominal
                
            # No configurations found, return None
            return None
        except Exception as e:
            if logger:
                logger.error(f"Error retrieving UPS nominal power from database: {str(e)}")
            return None

    @classmethod
    def create_or_update(cls, config_data: Dict[str, Any]) -> 'InitialSetup':
        """
        Create a new configuration or update the existing one.
        
        Args:
            config_data: Dictionary containing configuration values
            
        Returns:
            InitialSetup: The created or updated configuration
        """
        try:
            # Import the SQLAlchemy db instance from the core app
            from core.db.ups import db as app_db
            
            if logger:
                logger.info("Saving initial setup configuration")
            
            # Check if a configuration already exists
            existing_config = cls.query.first()
            
            if existing_config:
                # Update existing configuration
                existing_config.server_name = config_data.get('server_name', existing_config.server_name)
                existing_config.timezone = config_data.get('timezone', existing_config.timezone)
                existing_config.is_configured = config_data.get('is_configured', existing_config.is_configured)
                existing_config.ups_realpower_nominal = config_data.get('ups_realpower_nominal', existing_config.ups_realpower_nominal)
                
                if logger:
                    logger.info(f"Updated existing configuration (ID: {existing_config.id})")
                
                app_db.session.commit()
                return existing_config
            else:
                # Create new configuration
                new_config = cls(
                    server_name=config_data.get('server_name'),
                    timezone=config_data.get('timezone', 'UTC'),
                    is_configured=config_data.get('is_configured', False),
                    ups_realpower_nominal=config_data.get('ups_realpower_nominal', None)
                )
                
                app_db.session.add(new_config)
                app_db.session.commit()
                
                if logger:
                    logger.info(f"Created new configuration (ID: {new_config.id})")
                
                return new_config
                
        except Exception as e:
            # Ensure we rollback any open transaction
            try:
                app_db.session.rollback()
            except:
                pass
                
            if logger:
                logger.error(f"Error saving initial setup configuration: {str(e)}")
            raise

def init_model(model_base, db_logger=None):
    """
    Initialize the ORM model for initial setup configuration.
    
    Args:
        model_base: SQLAlchemy model base class
        db_logger: Logger instance or function to get logger
        
    Returns:
        class: Initialized InitialSetupModel class
    """
    global db, logger
    
    # Set the database logger
    from core.logger import database_logger
    logger = database_logger
    
    class InitialSetupModel(model_base, InitialSetup):
        """ORM model for initial setup configuration"""
        __table_args__ = {'extend_existing': True}
    
    return InitialSetupModel 