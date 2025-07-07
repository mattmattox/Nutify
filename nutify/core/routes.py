from flask import render_template, jsonify, request, send_file, redirect, url_for, current_app
from flask_socketio import emit
from .db.ups import (
    get_ups_data, 
    get_ups_model, 
    create_static_model,
    data_lock, 
    db
)
from .upsmon import handle_nut_event, get_event_history, get_events_table, acknowledge_event
import datetime
import json
import os
import logging
from datetime import datetime
import configparser
import pytz
from .energy.routes_energy import register_routes as register_energy_routes
from .battery.routes_battery import register_routes as register_battery_routes
from .power.routes_power import register_routes as register_power_routes
from .voltage.routes_voltage import register_routes as register_voltage_routes
from .voltage.api_voltage import register_api_routes as register_voltage_api_routes
from .upscmd.routes_upscmd import register_routes as register_upscmd_routes
from .upsrw.routes_upsrw import register_routes as register_upsrw_routes
from .advanced.routes_advanced import register_routes as register_advanced_routes
from .options import api_options, api_options_compat, routes_options
from core.options import (
    get_database_stats, get_log_files, get_system_info,
    get_filtered_logs, optimize_database, vacuum_database, backup_database, clear_logs
)
from core.logger import web_logger as logger
from core.settings import LOG, LOG_LEVEL, LOG_WERKZEUG, NUT_CONF_DIR
from core.auth import require_permission
# Remove direct import of CACHE_TIMEZONE to avoid circular import
import base64
from core.events import routes_events
from core.infoapi import routes_info
from core.infoups.routes_infoups import routes_infoups
logger.info("📡 Initializing routes")

def register_routes(app):
    """Registers all web routes for the application"""
    
    register_energy_routes(app)
    register_battery_routes(app)
    register_power_routes(app)
    register_voltage_routes(app)
    register_voltage_api_routes(app)
    register_upscmd_routes(app)
    register_upsrw_routes(app)
    register_advanced_routes(app)
    
    # Register options blueprints
    app.register_blueprint(api_options)
    app.register_blueprint(api_options_compat)  # Register compatibility routes
    app.register_blueprint(routes_options)
    
    # Register events blueprint
    app.register_blueprint(routes_events)
    
    # Register infoapi blueprint for API documentation
    app.register_blueprint(routes_info)
    app.register_blueprint(routes_infoups)
    
    @app.route('/')
    @require_permission('home')
    def index():
        """Main dashboard view - requires authentication"""
        try:
            # Check authentication first
            from core.auth import is_login_configured, is_authenticated
            
            if not is_login_configured():
                return redirect(url_for('auth.setup'))
            elif not is_authenticated():
                return redirect(url_for('auth.login'))
            
            # Check if UPS connection is available using the connection monitor
            from core.db.internal_checker import is_ups_connected, get_ups_connection_status
            
            connection_available = is_ups_connected()
            if not connection_available:
                # Get connection status for display
                connection_status = get_ups_connection_status()
                
                # Provide a graceful degraded view with connection status
                return render_template(
                    'dashboard/main.html',
                    data=None,
                    connection_error=True,
                    connection_status=connection_status,
                    recovery_mode=connection_status.get('in_recovery_mode', False),
                    recovery_attempts=connection_status.get('recovery_attempts', 0),
                    current_time=datetime.now(app.CACHE_TIMEZONE),
                    timezone=app.CACHE_TIMEZONE
                )
            
            # Normal processing when connection is available
            data = get_ups_data()
            return render_template(
                'dashboard/main.html',
                data=data,
                connection_error=False,
                current_time=datetime.now(app.CACHE_TIMEZONE),
                timezone=app.CACHE_TIMEZONE
            )
        except Exception as e:
            logger.exception(f"Error in index route: {str(e)}")
            from core.settings import NUT_CONF_DIR
            
            # Create a minimal data structure with enough information to render the page
            data = {'device_model': 'UPS Monitor', 'errors': [str(e)]}
            
            # Add the NUT configuration directory to the data dictionary for the template
            data['nut_conf_dir'] = NUT_CONF_DIR
            
            return render_template(
                'dashboard/main.html',
                data=data,
                connection_error=True,
                error=str(e),
                current_time=datetime.now(app.CACHE_TIMEZONE),
                timezone=app.CACHE_TIMEZONE
            )
    
    @app.route('/websocket-test')
    def websocket_test():
        """Render the WebSocket test page - requires authentication"""
        try:
            # Check authentication first
            from core.auth import is_login_configured, is_authenticated
            
            if not is_login_configured():
                return redirect(url_for('auth.setup'))
            elif not is_authenticated():
                return redirect(url_for('auth.login'))
            
            data = get_ups_data()  # Get UPS data for the header
        except Exception as e:
            logger.warning(f"Error getting UPS data for websocket test page: {str(e)}")
            # Create a minimal data structure with enough information to render the page
            data = {'device_model': 'UPS Monitor', 'errors': [str(e)]}
        
        return render_template('dashboard/websocket_test.html',
                             title='WebSocket Test',
                             data=data,
                             timezone=app.CACHE_TIMEZONE)

    return app