"""
NUT Configuration Checker and Manager.

This module provides functions to check for NUT configuration files
and manage the configuration status.
"""

import os
import logging
import sqlite3
from flask import g, current_app, has_app_context
from core.logger import system_logger as logger
from core.settings import (
    NUT_CONF_PATH, UPS_CONF_PATH, UPSD_CONF_PATH, 
    UPSD_USERS_PATH, UPSMON_CONF_PATH, NUT_CONF_DIR,
    INSTANCE_PATH, DB_NAME, DB_PATH, DB_URI
)

# Global variable to track configuration status
_nut_configured = False

def is_nut_configured():
    """
    Returns True if NUT is configured, False otherwise.
    
    This function uses a global variable that is set during the
    check_nut_config_files function call.
    
    Returns:
        bool: True if NUT is configured, False otherwise.
    """
    return _nut_configured

def check_nut_config_files():
    """
    Checks if required NUT configuration files exist based on the NUT mode.
    For net-client mode, only nut.conf and upsmon.conf are required.
    For standalone and netserver modes, more files are required.
    
    Also checks if the database is properly configured with required fields
    in the ups_initial_setup table.
    
    Returns:
        tuple: (bool, list) - (is_configured, missing_files)
    """
    global _nut_configured
    
    # First check if NUT_CONF_DIR exists
    if not os.path.exists(NUT_CONF_DIR):
        logger.warning(f"NUT configuration directory doesn't exist: {NUT_CONF_DIR}")
        _nut_configured = False
        return False, ["NUT configuration directory"]
    
    # Always check if nut.conf exists first - it's required for all modes
    if not os.path.exists(NUT_CONF_PATH):
        logger.warning(f"Main NUT configuration file doesn't exist: {NUT_CONF_PATH}")
        _nut_configured = False
        return False, ["nut.conf"]
    
    # Determine the NUT mode from nut.conf to know which files to check
    nut_mode = "standalone"  # Default mode
    try:
        with open(NUT_CONF_PATH, 'r') as f:
            for line in f:
                if line.strip().startswith('MODE='):
                    nut_mode = line.strip().split('=')[1].strip('"\'').lower()
                    break
        logger.info(f"Detected NUT mode: {nut_mode}")
    except Exception as e:
        logger.warning(f"Failed to read NUT mode from {NUT_CONF_PATH}: {str(e)}")
    
    # Define required files based on mode
    required_config_files = []
    
    if nut_mode == "none":
        # Mode "none" means NUT is not active, so no additional files required
        logger.warning("NUT mode is set to 'none', meaning NUT is not active.")
        _nut_configured = False
        return False, ["NUT not active (mode=none)"]
    
    elif nut_mode == "netclient":
        # For netclient, we need upsmon.conf
        required_config_files = [
            (UPSMON_CONF_PATH, "upsmon.conf")
        ]
    
    else:  # standalone or netserver
        # For standalone or netserver, we need these files
        required_config_files = [
            (UPS_CONF_PATH, "ups.conf"),
            (UPSD_CONF_PATH, "upsd.conf"),
            (UPSD_USERS_PATH, "upsd.users")
        ]
        
        # upsmon.conf is needed for all modes except "none"
        if os.path.exists(UPSMON_CONF_PATH):
            logger.info(f"upsmon.conf found at {UPSMON_CONF_PATH}")
        else:
            logger.warning(f"upsmon.conf not found at {UPSMON_CONF_PATH}")
            required_config_files.append((UPSMON_CONF_PATH, "upsmon.conf"))
    
    missing_files = []
    for config_file_path, config_file_name in required_config_files:
        if not os.path.exists(config_file_path):
            missing_files.append(config_file_name)
    
    if missing_files:
        logger.warning(f"Required NUT configuration files for mode '{nut_mode}' are missing: {', '.join(missing_files)}")
        logger.warning("The application will run in setup mode.")
        _nut_configured = False
        return False, missing_files
    
    # Check database configuration if file checks passed
    db_missing = []
    
    # Check if database file exists
    if not os.path.exists(DB_PATH):
        logger.warning(f"Database check: Database file not found at {DB_PATH}")
        db_missing.append("Database file")
    else:
        # Use SQLAlchemy instead of direct SQLite connection
        try:
            from sqlalchemy import create_engine, MetaData, Table, Column, String, Integer, Boolean, inspect, select
            
            # Create engine
            engine = create_engine(f'sqlite:///{DB_PATH}')
            inspector = inspect(engine)
            
            # Check if the table exists using SQLAlchemy inspector
            if 'ups_initial_setup' not in inspector.get_table_names():
                logger.warning("Database check: ups_initial_setup table does not exist.")
                db_missing.append("Database table 'ups_initial_setup'")
            else:
                # Define the table structure for ups_initial_setup
                metadata = MetaData()
                ups_initial_setup = Table(
                    'ups_initial_setup', 
                    metadata,
                    Column('id', Integer, primary_key=True),
                    Column('server_name', String),
                    Column('timezone', String),
                    Column('is_configured', Boolean)
                )
                
                # Check if there are configured rows using SQLAlchemy
                with engine.connect() as connection:
                    # Count configured entries
                    from sqlalchemy.sql import func
                    query = select(func.count()).select_from(ups_initial_setup).where(
                        ups_initial_setup.c.is_configured == 1
                    )
                    
                    result = connection.execute(query).scalar()
                    
                    if result == 0:
                        logger.warning("Database check: No configured entries in ups_initial_setup table.")
                        db_missing.append("Initial setup configuration")
                    else:
                        # Check required fields
                        query = select(
                            ups_initial_setup.c.server_name,
                            ups_initial_setup.c.timezone
                        ).where(
                            ups_initial_setup.c.is_configured == 1
                        )
                        
                        config_row = connection.execute(query).fetchone()
                        
                        if not config_row[0]:  # server_name
                            db_missing.append("server_name in database")
                        if not config_row[1]:  # timezone
                            db_missing.append("timezone in database")
        
        except Exception as e:
            logger.warning(f"Database check: Error checking database with SQLAlchemy: {str(e)}")
            db_missing.append("Database access error")
    
    # Add any database issues to missing_files
    if db_missing:
        missing_files.extend(db_missing)
        logger.warning(f"Database check failed: {', '.join(db_missing)}")
    
    if missing_files:
        logger.warning("The application will run in setup mode due to missing configuration.")
        _nut_configured = False
        return False, missing_files
    
    _nut_configured = True
    return True, [] 