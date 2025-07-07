"""
UPS Commands Routes.
"""

from flask import Blueprint, render_template, current_app
from core.db.ups import get_ups_data
from core.logger import ups_logger as logger
from core.auth import require_permission

routes_upscmd = Blueprint('routes_upscmd', __name__)

def register_routes(app):
    """Register all HTML routes for the UPS commands section"""
    
    @app.route('/upscmd')
    @require_permission('command')
    def upscmd_page():
        """Page for running commands directly on the UPS"""
        try:
            data = get_ups_data()
            return render_template('dashboard/upscmd.html', 
                                 data=data,
                                 timezone=current_app.CACHE_TIMEZONE)
        except Exception as e:
            logger.error(f"Error rendering UPScmd page: {str(e)}", exc_info=True)
            # In case of error, pass at least the device_model
            return render_template('dashboard/upscmd.html', 
                                 data={'device_model': 'UPS Monitor'}, 
                                 timezone=current_app.CACHE_TIMEZONE)
    
    return app 