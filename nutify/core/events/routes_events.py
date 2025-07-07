"""
Routes for UPS events handling and display.
"""

from flask import Blueprint, render_template, jsonify, request, current_app
from core.db.ups import get_ups_data
from core.logger import events_logger as logger
from core.auth import require_permission
from core.upsmon import handle_nut_event, get_event_history, get_events_table

# Create a blueprint for events routes
routes_events = Blueprint('routes_events', __name__)

@routes_events.route('/events')
@require_permission('events')
def events_page():
    """Render the events page"""
    data = get_ups_data()  # This takes the static UPS data
    return render_template('dashboard/events.html', 
                         data=data,
                         timezone=current_app.CACHE_TIMEZONE)

@routes_events.route('/nut_event', methods=['POST'])
def nut_event_route():
    """Handles incoming NUT events"""
    try:
        data = request.get_json()
        return handle_nut_event(current_app, data)
    except Exception as e:
        logger.error(f"Error handling NUT event: {str(e)}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500 