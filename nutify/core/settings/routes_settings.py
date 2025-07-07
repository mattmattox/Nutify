from flask import Blueprint, render_template, request, jsonify, redirect, url_for, current_app
import os
from datetime import datetime

from .settings import get_logger
from core.db.ups import get_ups_data
from core.mail import get_notification_settings, MailConfig
from core.settings import LOG, LOG_LEVEL, LOG_WERKZEUG
from core.nut_config.routes import get_timezones
from core.auth import get_current_user

logger = get_logger('options')

routes_settings = Blueprint('routes_settings', __name__)

@routes_settings.route('/settings')
@routes_settings.route('/options')
def settings_page():
    """Render the settings page"""
    logger.info("Accessing settings page")
    
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
        mail_config = MailConfig.query.first()
        data['mail_config'] = {
            'enabled': mail_config and mail_config.enabled,
            'provider': mail_config.provider if mail_config else None,
            'smtp_server': mail_config.smtp_server if mail_config else None,
            'username': mail_config.username if mail_config else None
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

@routes_settings.route('/settings/system')
def system_settings():
    """Render the system settings page"""
    logger.info("Accessing system settings page")
    return render_template('system_settings.html')

@routes_settings.route('/settings/advanced')
def advanced_settings():
    """Render the advanced settings page"""
    logger.info("Accessing advanced settings page")
    return render_template('advanced_settings.html')

@routes_settings.route('/settings/backup')
def backup_settings():
    """Render the backup/restore settings page"""
    logger.info("Accessing backup settings page")
    return render_template('backup_settings.html') 