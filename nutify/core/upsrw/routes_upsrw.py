"""
UPS Read/Write Routes.
"""

from flask import Blueprint, render_template, request, jsonify, current_app
from core.db.ups import get_ups_data
from core.logger import ups_logger as logger
from core.auth import require_permission

routes_upsrw = Blueprint('routes_upsrw', __name__)

def register_routes(app):
    """Register UPS read/write routes with the Flask application."""
    
    @app.route('/upsrw')
    @require_permission('settings')
    def upsrw_page():
        """Render the UPS read/write page"""
        data = get_ups_data()
        return render_template('dashboard/upsrw.html', 
                             data=data,
                             timezone=current_app.CACHE_TIMEZONE)
    
    @app.route('/upsrw/preview')
    @require_permission('settings')
    def upsrw_preview():
        """Render the UPS read/write preview page"""
        data = get_ups_data()
        return render_template('dashboard/upsrw_preview.html', 
                             data=data,
                             timezone=current_app.CACHE_TIMEZONE)
    
    return app 