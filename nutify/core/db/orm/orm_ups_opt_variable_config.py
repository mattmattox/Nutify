"""
Variable Configuration ORM Model.
This module defines the SQLAlchemy ORM model for the ups_opt_variable_config table.
"""

from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
import json
import logging
import pytz
from flask import current_app
from typing import Dict, List, Optional, Union, Any
from core.db.ups import db as app_db

# These will be set during initialization
db = None

class VariableConfig:
    """Model for variable configuration"""
    __tablename__ = 'ups_opt_variable_config'

    id = Column(Integer, primary_key=True)
    currency = Column(String(3), nullable=False, default='EUR')
    price_per_kwh = Column(Float, nullable=False, default=0.25)
    co2_factor = Column(Float, nullable=False, default=0.4)
    polling_interval = Column(Integer, nullable=False, default=1)       
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(pytz.UTC))
    updated_at = Column(DateTime(timezone=True), 
                       default=lambda: datetime.now(pytz.UTC),
                       onupdate=lambda: datetime.now(pytz.UTC))
    
    @classmethod
    def init_default_config(cls):
        """Initialize default configuration if not exists"""
        try:
            from core.logger import database_logger as logger
            
            # Import the SQLAlchemy db instance from the core app
            from core.db.ups import db as app_db
            
            logger.info("Starting VariableConfig initialization")
            
            # Check if a default config already exists
            existing_config = app_db.session.query(cls).first()
            if existing_config:
                logger.info(f"Default config already exists: {existing_config.id}")
                return False
                
            logger.info("No default config found, creating one")
            
            # Create a new default config
            default_config = cls(
                id=1,
                currency='EUR',
                price_per_kwh=0.25,
                co2_factor=0.4,
                polling_interval=1
            )
            app_db.session.add(default_config)
            
            # Commit the transaction to the database
            try:
                app_db.session.commit()
                logger.info("Default variable configuration created and committed")
                return True
            except Exception as e:
                # If error occurs during commit due to transaction issues, try a different approach
                if "transaction is already begun" in str(e):
                    logger.debug("Transaction already begun, trying to flush instead")
                    app_db.session.flush()
                    logger.info("Default variable configuration flushed to session")
                    return True
                else:
                    # Another type of error, propagate it
                    app_db.session.rollback()
                    logger.error(f"Error during commit: {str(e)}")
                    raise
            
        except Exception as e:
            # Ensure we rollback any open transaction
            try:
                app_db.session.rollback()
            except:
                pass
                
            from core.logger import database_logger as logger
            logger.error(f"Error initializing default variable config: {str(e)}")
            return False
    
    @classmethod
    def utc_to_local(cls, utc_dt):
        """
        Convert a UTC datetime to the configured local timezone.
        
        Args:
            utc_dt: UTC datetime object
            
        Returns:
            datetime: Local timezone datetime object
        """
        from core.db.ups.utils import utc_to_local as utils_utc_to_local
        return utils_utc_to_local(utc_dt)
    
    @classmethod
    def local_to_utc(cls, local_dt):
        """
        Convert a local timezone datetime to UTC.
        
        Args:
            local_dt: Local timezone datetime object
            
        Returns:
            datetime: UTC datetime object
        """
        from core.db.ups.utils import local_to_utc as utils_local_to_utc
        return utils_local_to_utc(local_dt)

def init_model(model_base):
    """
    Initialize the VariableConfig model with the SQLAlchemy base.
    
    Args:
        model_base: SQLAlchemy declarative base class
        
    Returns:
        The initialized VariableConfig model class
    """
    global db
    db = model_base
    
    class VariableConfigModel(model_base, VariableConfig):
        """ORM model for variable configuration"""
        __table_args__ = {'extend_existing': True}
    
    return VariableConfigModel 