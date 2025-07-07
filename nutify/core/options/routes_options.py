from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, send_file
import os
from datetime import datetime
from .options import (
    get_database_stats,
    backup_database,
    optimize_database,
    vacuum_database,
    get_log_files,
    get_log_content,
    download_logs,
    get_system_info,
    get_filtered_logs,
    clear_logs,
    get_variable_config
)
from core.logger import options_logger as logger
from core.mail import get_notification_settings, get_mail_config_model
from core.settings import LOG, LOG_LEVEL, LOG_WERKZEUG
from core.db.ups import get_ups_data, db
from core.nut_config.routes import get_timezones
from core.auth import require_permission, get_current_user

routes_options = Blueprint('routes_options', __name__, url_prefix='/options')

logger.info("🔄 Initializing options routes")

# Helper function to safely get the MailConfig model
def get_mail_config():
    """Safely get the MailConfig model"""
    MailConfig = get_mail_config_model()
    if MailConfig is None:
        logger.error("❌ MailConfig model not available")
    return MailConfig

@routes_options.route('/')
@require_permission('options')
def options_dashboard():
    """Render the options dashboard page"""
    # Get the UPS data for the template
    data = get_ups_data()
    
    # Get current user and their options tabs permissions
    current_user = get_current_user()
    user_options_tabs = {}
    user_is_admin = False
    
    if current_user:
        user_is_admin = current_user.get('role') == 'administrator' or current_user.get('id') == 1
        
        if not user_is_admin:
            # Get user's options tabs permissions from database
            try:
                from core.auth import LoginAuth
                if LoginAuth:
                    user = LoginAuth.query.filter_by(id=current_user['id'], is_active=True).first()
                    if user:
                        user_options_tabs = user.get_options_tabs()
                        logger.debug(f"🔐 User {current_user['username']} options tabs: {user_options_tabs}")
                    else:
                        logger.warning(f"🔐 User {current_user['id']} not found in database")
                else:
                    logger.error("🔐 LoginAuth model not available")
            except Exception as e:
                logger.error(f"🔐 Error loading user options tabs: {str(e)}")
                user_options_tabs = {}
        else:
            # Admin has access to all tabs
            user_options_tabs = {
                'email': True,
                'extranotifs': True,
                'webhook': True,
                'powerflow': True,
                'database': True,
                'log': True,
                'advanced': True,
                'admin': True
            }
    
    try:
        notify_settings = get_notification_settings()
    except Exception as e:
        logger.error(f"Error loading notification settings in options page: {str(e)}")
        notify_settings = []
    
    try:
        MailConfig = get_mail_config()
        if MailConfig:
            mail_config = MailConfig.query.first()
            data['mail_config'] = {
                'enabled': mail_config and mail_config.enabled,
                'provider': mail_config.provider if mail_config else None,
                'smtp_server': mail_config.smtp_server if mail_config else None,
                'username': mail_config.username if mail_config else None
            }
        else:
            data['mail_config'] = {
                'enabled': False,
                'provider': None,
                'smtp_server': None,
                'username': None
            }
    except Exception as e:
        logger.error(f"Error loading mail configuration in options page: {str(e)}")
        data['mail_config'] = {
            'enabled': False,
            'provider': None,
            'smtp_server': None,
            'username': None
        }
    
    # Read values from settings.txt; if LOG is not bool, normalize the comparison:
    log_enabled = str(LOG).strip().lower() == 'true'
    werkzeug_log_enabled = str(LOG_WERKZEUG).strip().lower() == 'true'
    
    # Debug logs for log settings
    logger.debug(f"DEBUG OPTIONS: LOG = {LOG!r}, log_enabled = {log_enabled}")
    logger.debug(f"DEBUG OPTIONS: LOG_WERKZEUG = {LOG_WERKZEUG!r}, werkzeug_log_enabled = {werkzeug_log_enabled}")
    
    # Get timezones from the TimeZone.readme file
    timezones = get_timezones()
    
    return render_template('dashboard/options.html',
                         data=data,
                         notify_settings=notify_settings,
                         log_enabled=log_enabled,
                         log_level=LOG_LEVEL,
                         werkzeug_log_enabled=werkzeug_log_enabled,
                         timezone=current_app.CACHE_TIMEZONE,
                         timezones=timezones,
                         user_options_tabs=user_options_tabs,
                         user_is_admin=user_is_admin)

@routes_options.route('/settings')
@require_permission('options')
def settings_redirect():
    """Redirect /settings to /options"""
    return redirect(url_for('routes_options.options_dashboard'))

@routes_options.route('/database')
@require_permission('options')
def database_options():
    """Render the database options page"""
    data = get_ups_data()
    db_stats = get_database_stats()
    
    return render_template(
        'dashboard/database.html',
        data=data,
        db_stats=db_stats,
        timezone=current_app.CACHE_TIMEZONE
    )

@routes_options.route('/database/backup', methods=['POST'])
@require_permission('options')
def create_backup_ui():
    """Create database backup from UI"""
    backup_path = backup_database()
    if backup_path:
        flash(f'Database backup created successfully at {backup_path}', 'success')
    else:
        flash('Failed to create database backup', 'error')
    return redirect(url_for('routes_options.database_options'))

@routes_options.route('/database/optimize', methods=['POST'])
@require_permission('options')
def optimize_db_ui():
    """Optimize database from UI"""
    success = optimize_database()
    if success:
        flash('Database optimized successfully', 'success')
    else:
        flash('Failed to optimize database', 'error')
    return redirect(url_for('routes_options.database_options'))

@routes_options.route('/database/vacuum', methods=['POST'])
@require_permission('options')
def vacuum_db_ui():
    """Vacuum database from UI"""
    success = vacuum_database()
    if success:
        flash('Database vacuumed successfully', 'success')
    else:
        flash('Failed to vacuum database', 'error')
    return redirect(url_for('routes_options.database_options'))

@routes_options.route('/logs')
@require_permission('options')
def logs_page():
    """Render the logs page"""
    data = get_ups_data()
    log_type = request.args.get('type', 'all')
    log_level = request.args.get('level', 'all')
    date_range = request.args.get('date_range', 'all')
    try:
        page = int(request.args.get('page', '1'))
    except ValueError:
        page = 1
    
    logs = get_filtered_logs(
        log_type=log_type, 
        log_level=log_level, 
        date_range=date_range,
        page=page,
        page_size=50  # Smaller page size for UI
    )
    
    # Define available log types and levels for filters
    log_types = {
        'all': 'All Logs',
        'system': 'System',
        'database': 'Database',
        'ups': 'UPS',
        'energy': 'Energy',
        'web': 'Web',
        'mail': 'Mail',
        'options': 'Options',
        'battery': 'Battery',
        'upsmon': 'UPS Monitor',
        'socket': 'Socket',
        'voltage': 'Voltage',
        'power': 'Power'
    }
    
    log_levels = {
        'all': 'All Levels',
        'debug': 'Debug',
        'info': 'Info',
        'warning': 'Warning',
        'error': 'Error'
    }
    
    date_ranges = {
        'all': 'All Time',
        'today': 'Today',
        'week': 'This Week',
        'month': 'This Month'
    }
    
    return render_template(
        'dashboard/logs.html',
        data=data,
        logs=logs,
        log_type=log_type,
        log_level=log_level,
        date_range=date_range,
        page=page,
        log_types=log_types,
        log_levels=log_levels,
        date_ranges=date_ranges,
        timezone=current_app.CACHE_TIMEZONE
    )

@routes_options.route('/logs/download')
@require_permission('options')
def download_logs_ui():
    """Download logs from UI"""
    log_type = request.args.get('type', 'all')
    log_level = request.args.get('level', 'all')
    date_range = request.args.get('date_range', 'all')
    
    zip_path = download_logs(log_type, log_level, date_range)
    
    if zip_path:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        return send_file(
            zip_path,
            as_attachment=True,
            download_name=f'logs_{timestamp}.zip',
            mimetype='application/zip'
        )
    
    flash('No logs to download', 'error')
    return redirect(url_for('routes_options.logs_page'))

@routes_options.route('/logs/clear/<log_type>', methods=['POST'])
@require_permission('options')
def clear_logs_ui(log_type):
    """Clear logs from UI"""
    success, message = clear_logs(log_type)
    if success:
        flash(message, 'success')
    else:
        flash(f'Error clearing logs: {message}', 'error')
    return redirect(url_for('routes_options.logs_page'))

@routes_options.route('/system')
@require_permission('options')
def system_info_page():
    """Render the system info page"""
    data = get_ups_data()
    system_info = get_system_info()
    
    return render_template(
        'dashboard/system.html',
        data=data,
        system_info=system_info,
        timezone=current_app.CACHE_TIMEZONE
    ) 