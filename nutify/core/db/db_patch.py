"""
Database patching module for Nutify.
This module provides functions to check and patch database schema issues.
"""

import logging
from sqlalchemy import inspect, text
from flask import current_app
from sqlalchemy.exc import SQLAlchemyError
import pytz
from datetime import datetime

from core.logger import database_logger as logger

def get_application_timezone(db):
    """
    Gets the application timezone from the Flask app's CACHE_TIMEZONE.
    
    Args:
        db: SQLAlchemy database instance (needed for function signature compatibility)
        
    Returns:
        pytz.timezone: The application timezone object from current_app.CACHE_TIMEZONE
    """
    try:
        if current_app and hasattr(current_app, 'CACHE_TIMEZONE'):
            logger.info(f"🕒 Using application timezone from app.CACHE_TIMEZONE: {current_app.CACHE_TIMEZONE.zone}")
            return current_app.CACHE_TIMEZONE
        else:
            logger.error("❌ CACHE_TIMEZONE not available from Flask app! This should never happen.")
            return pytz.UTC
    except Exception as e:
        logger.error(f"❌ Error getting application timezone: {str(e)}")
        logger.warning("⚠️ Falling back to UTC timezone for conversion")
        return pytz.UTC

def check_timestamp_columns(db, app):
    """
    Checks if timestamp columns in the database are using the correct naming convention.
    If timestamp_tz columns are found, they will be converted to timestamp_utc with UTC values.
    
    This function checks the following tables:
    - ups_dynamic_data
    - ups_static_data
    - ups_events
    
    Args:
        db: SQLAlchemy database instance
        app: Flask application instance
        
    Returns:
        bool: True if all tables have the correct column names, False otherwise
    """
    logger.info("🔍 Checking timestamp columns in database tables...")
    
    app_timezone = get_application_timezone(db)
    
    tables_to_check = {
        'ups_dynamic_data': {'id_column': 'id', 'old_column': 'timestamp_tz', 'new_column': 'timestamp_utc'},
        'ups_static_data': {'id_column': 'id', 'old_column': 'timestamp_tz', 'new_column': 'timestamp_utc'},
        'ups_events': {'id_column': 'id', 'old_column': 'timestamp_tz', 'new_column': 'timestamp_utc'}
    }
    
    inspector = inspect(db.engine)
    existing_tables = inspector.get_table_names()
    all_correct = True
    
    for table_name, columns in tables_to_check.items():
        if table_name not in existing_tables:
            logger.info(f"Table {table_name} doesn't exist yet, skipping")
            continue
        
        table_columns = [c['name'] for c in inspector.get_columns(table_name)]
        
        old_column = columns['old_column']
        new_column = columns['new_column']
        
        if old_column in table_columns and new_column not in table_columns:
            logger.warning(f"⚠️ Table {table_name} has old column '{old_column}' instead of '{new_column}'")
            all_correct = False
            with app.app_context():
                convert_timestamp_column(db, table_name, old_column, new_column, columns['id_column'], app_timezone)
                
        elif old_column not in table_columns and new_column in table_columns:
            logger.info(f"✅ Table {table_name} has correct column '{new_column}'")
            
        elif old_column in table_columns and new_column in table_columns:
            logger.warning(f"⚠️ Table {table_name} has both '{old_column}' and '{new_column}' columns")
            all_correct = False
            with app.app_context():
                transfer_and_drop_column(db, table_name, old_column, new_column, columns['id_column'], app_timezone)
                
        elif old_column not in table_columns and new_column not in table_columns:
            logger.warning(f"⚠️ Table {table_name} doesn't have either '{old_column}' or '{new_column}'")
            all_correct = False
    
    return all_correct

def convert_timestamp_column(db, table_name, old_column, new_column, id_column, app_timezone):
    """
    Converts an old timestamp column to a new one in place for SQLite.
    Converts timestamps to UTC using Python's pytz, then renames the column.
    
    Args:
        db: SQLAlchemy database instance
        table_name: Name of the table to modify
        old_column: Name of the old column
        new_column: Name of the new column
        id_column: Name of the ID column for tracking progress
        app_timezone: Application timezone for conversion
    """
    logger.info(f"🔄 Converting column '{old_column}' to '{new_column}' in table '{table_name}'")
    
    try:
        with db.engine.connect() as conn:
            # Check if table is empty
            result = conn.execute(text(f"SELECT COUNT({id_column}) FROM {table_name}")).fetchone()
            total_rows = result[0] if result else 0
            
            if total_rows == 0:
                logger.info(f"📊 Table {table_name} is empty, performing simple column rename")
                conn.execute(text(f"ALTER TABLE {table_name} RENAME COLUMN {old_column} TO {new_column}"))
                conn.commit()
                logger.info(f"✅ Successfully renamed column in empty table {table_name}")
                return
            
            logger.info(f"📊 Processing {table_name} with {total_rows} rows")
            
            # Fetch all rows with non-NULL timestamps
            rows = conn.execute(text(f"SELECT {id_column}, {old_column} FROM {table_name} WHERE {old_column} IS NOT NULL")).fetchall()
            
            # Convert timestamps to UTC
            for row in rows:
                row_id, timestamp_str = row
                try:
                    # Parse the timestamp (assuming ISO 8601 format)
                    if timestamp_str:
                        # Handle possible formats
                        try:
                            # Try parsing with timezone info
                            dt = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                        except ValueError:
                            # Fallback to naive datetime in app timezone
                            dt = datetime.fromisoformat(timestamp_str)
                            dt = app_timezone.localize(dt)
                        
                        # Convert to UTC
                        dt_utc = dt.astimezone(pytz.UTC)
                        # Format as ISO 8601 without timezone (since SQLite doesn't store it)
                        utc_timestamp = dt_utc.strftime('%Y-%m-%d %H:%M:%S')
                        
                        # Update the row
                        conn.execute(
                            text(f"UPDATE {table_name} SET {old_column} = :utc_timestamp WHERE {id_column} = :row_id"),
                            {"utc_timestamp": utc_timestamp, "row_id": row_id}
                        )
                except ValueError as e:
                    logger.warning(f"⚠️ Invalid timestamp format in {table_name} (ID {row_id}): {timestamp_str}, skipping")
                    continue
            
            conn.commit()
            
            # Rename the column to timestamp_utc
            conn.execute(text(f"ALTER TABLE {table_name} RENAME COLUMN {old_column} TO {new_column}"))
            conn.commit()
            
        logger.info(f"✅ Successfully converted and renamed column in table {table_name}")
        
    except SQLAlchemyError as e:
        logger.error(f"❌ Error converting column in table {table_name}: {str(e)}")
        db.session.rollback()
        raise

def transfer_and_drop_column(db, table_name, old_column, new_column, id_column, app_timezone):
    """
    Handles cases where both timestamp_tz and timestamp_utc exist in SQLite.
    Transfers data from old_column to new_column (converting to UTC) and drops old_column.
    
    Args:
        db: SQLAlchemy database instance
        table_name: Name of the table to modify
        old_column: Name of the old column
        new_column: Name of the new column
        id_column: Name of the ID column for tracking progress
        app_timezone: Application timezone for conversion
    """
    logger.info(f"🔄 Transferring data from '{old_column}' to '{new_column}' in table '{table_name}'")
    
    try:
        with db.engine.connect() as conn:
            # Check if table is empty
            result = conn.execute(text(f"SELECT COUNT({id_column}) FROM {table_name}")).fetchone()
            total_rows = result[0] if result else 0
            
            if total_rows == 0:
                logger.info(f"📊 Table {table_name} is empty, dropping old column")
                conn.execute(text(f"ALTER TABLE {table_name} DROP COLUMN {old_column}"))
                conn.commit()
                logger.info(f"✅ Successfully dropped old column in empty table {table_name}")
                return
            
            logger.info(f"📊 Processing {table_name} with {total_rows} rows")
            
            # Fetch rows where old_column is not NULL and new_column needs updating
            rows = conn.execute(
                text(f"SELECT {id_column}, {old_column} FROM {table_name} WHERE {old_column} IS NOT NULL")
            ).fetchall()
            
            # Convert timestamps to UTC and update new_column
            for row in rows:
                row_id, timestamp_str = row
                try:
                    if timestamp_str:
                        # Parse the timestamp
                        try:
                            dt = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                        except ValueError:
                            dt = datetime.fromisoformat(timestamp_str)
                            dt = app_timezone.localize(dt)
                        
                        # Convert to UTC
                        dt_utc = dt.astimezone(pytz.UTC)
                        utc_timestamp = dt_utc.strftime('%Y-%m-%d %H:%M:%S')
                        
                        # Update new_column
                        conn.execute(
                            text(f"UPDATE {table_name} SET {new_column} = :utc_timestamp WHERE {id_column} = :row_id"),
                            {"utc_timestamp": utc_timestamp, "row_id": row_id}
                        )
                except ValueError as e:
                    logger.warning(f"⚠️ Invalid timestamp format in {table_name} (ID {row_id}): {timestamp_str}, skipping")
                    continue
            
            conn.commit()
            
            # Drop the old column
            # Note: SQLite doesn't support DROP COLUMN directly, so we need to recreate the table
            inspector = inspect(db.engine)
            columns = inspector.get_columns(table_name)
            new_columns = [c for c in columns if c['name'] != old_column]
            
            # Create a new table with all columns except old_column
            temp_table_name = f"{table_name}_temp"
            column_defs = []
            for col in new_columns:
                col_name = col['name']
                col_type = 'TEXT' if col_name in [new_column, old_column] else str(col['type']).upper()
                col_def = f"{col_name} {col_type}"
                if col_name == id_column:
                    col_def += " PRIMARY KEY"
                if not col.get('nullable', True):
                    col_def += " NOT NULL"
                column_defs.append(col_def)
            
            create_stmt = f"CREATE TABLE {temp_table_name} ({', '.join(column_defs)})"
            conn.execute(text(create_stmt))
            
            # Copy data to new table
            column_names = [c['name'] for c in new_columns]
            columns_sql = ', '.join(column_names)
            conn.execute(text(f"INSERT INTO {temp_table_name} ({columns_sql}) SELECT {columns_sql} FROM {table_name}"))
            
            # Drop original table and rename new table
            conn.execute(text(f"DROP TABLE {table_name}"))
            conn.execute(text(f"ALTER TABLE {temp_table_name} RENAME TO {table_name}"))
            
            conn.commit()
            
        logger.info(f"✅ Successfully transferred data and dropped old column in table {table_name}")
        
    except SQLAlchemyError as e:
        logger.error(f"❌ Error transferring data in table {table_name}: {str(e)}")
        db.session.rollback()
        # Clean up temp table if it exists
        try:
            with db.engine.connect() as conn:
                inspector = inspect(db.engine)
                if temp_table_name in inspector.get_table_names():
                    conn.execute(text(f"DROP TABLE {temp_table_name}"))
                    conn.commit()
        except:
            pass
        raise