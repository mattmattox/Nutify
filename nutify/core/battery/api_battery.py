from flask import jsonify, request, current_app
from datetime import datetime, timedelta
from core.logger import battery_logger as logger
from core.db.ups import get_ups_model
from .battery import (
    get_available_battery_metrics,
    get_battery_stats,
    get_battery_history
)

# Import functions from battery module
logger.info("🔋 Initializing battery API routes")

def register_api_routes(app):
    """Register all API routes related to the battery"""
    
    @app.route('/api/battery/metrics')
    def api_battery_metrics():
        """API for available metrics"""
        metrics = get_available_battery_metrics()
        return jsonify({'success': True, 'data': metrics})
    
    @app.route('/api/battery/stats')
    def api_battery_stats():
        """API for statistics"""
        period = request.args.get('period', 'day')
        from_time = request.args.get('from_time')
        to_time = request.args.get('to_time')
        if period == 'day':
            selected_date = request.args.get('selected_date')
            tz = current_app.CACHE_TIMEZONE
            if selected_date:
                try:
                    selected_date_dt = datetime.strptime(selected_date, '%Y-%m-%d')
                    if selected_date_dt.tzinfo is None:
                        selected_date_dt = tz.localize(selected_date_dt)
                except ValueError:
                    logger.error(f"Invalid selected_date format: {selected_date}")
                    selected_date_dt = datetime.now(tz)
            else:
                selected_date_dt = datetime.now(tz)
            stats = get_battery_stats(period, from_time, to_time, selected_date_dt)
        else:
            stats = get_battery_stats(period, from_time, to_time)
        return jsonify({'success': True, 'data': stats})
    
    @app.route('/api/battery/has_hour_data')
    def api_battery_has_hour_data():
        """
        API endpoint to check if there is at least 60 minutes of battery data.
        
        Returns:
            JSON response with a boolean indicating if enough data exists.
        """
        try:
            UPSDynamicData = get_ups_model()
            tz = current_app.CACHE_TIMEZONE
            logger.debug(f"Using timezone: {tz.zone}")
            
            # Get current time in UTC directly (using naive datetime for SQLite compatibility)
            now_utc = datetime.utcnow()
            one_hour_ago_utc = now_utc - timedelta(hours=1)
            
            # Format for logging
            now_str = now_utc.strftime('%Y-%m-%d %H:%M:%S')
            one_hour_ago_str = one_hour_ago_utc.strftime('%Y-%m-%d %H:%M:%S')
            
            # Log the time values for debugging
            logger.debug(f"Checking for battery data between {one_hour_ago_str} and {now_str} (UTC)")
            
            # Query to find records in the last hour with valid battery data
            # Using battery_charge as the main metric as it's usually the most reliable
            data = UPSDynamicData.query\
                .filter(
                    UPSDynamicData.timestamp_utc >= one_hour_ago_utc,
                    UPSDynamicData.timestamp_utc <= now_utc,
                    UPSDynamicData.battery_charge.isnot(None)
                ).order_by(UPSDynamicData.timestamp_utc.asc()).all()
            
            # Get the count of data points
            data_count = len(data)
            logger.debug(f"Found {data_count} battery data points in the query")
            
            # Check if we have at least 30 data points (minimum threshold)
            if data_count < 30:
                logger.debug(f"Insufficient data points: {data_count} < 30")
                return jsonify({'has_data': False})
            
            # Check if we have data spanning at least 50 minutes
            if data:
                timestamps = [record.timestamp_utc for record in data]
                first_timestamp = min(timestamps)
                last_timestamp = max(timestamps)
                
                time_span_minutes = (last_timestamp - first_timestamp).total_seconds() / 60
                
                logger.debug(f"Data time span: {time_span_minutes:.2f} minutes with {data_count} points")
                logger.debug(f"First record: {first_timestamp}, Last record: {last_timestamp}")
                
                # Require at least 50 minutes of data
                has_sufficient_data = time_span_minutes >= 50
                
                # Add additional debug output
                logger.debug(f"Final decision - has_sufficient_data: {has_sufficient_data}")
                
                return jsonify({'has_data': has_sufficient_data})
            
            logger.debug("No data found after filtering")
            return jsonify({'has_data': False})
            
        except Exception as e:
            logger.error(f"Error checking for hour data: {str(e)}")
            return jsonify({'has_data': False, 'error': str(e)})
    
    @app.route('/api/battery/history')
    def api_battery_history():
        """API for history data"""
        period = request.args.get('period', 'day')
        from_time = request.args.get('from_time')
        to_time = request.args.get('to_time')
        selected_date = request.args.get('selected_date')
        today_mode = request.args.get('today_mode') == 'true'
        
        logger.debug(f"📊 API Battery History request: period={period}, from={from_time}, to={to_time}, today_mode={today_mode}")
        
        # For 'today' period or today_mode=true, pass it directly to get_battery_history as 'today'
        if period == 'today' or today_mode:
            history = get_battery_history(period='today')
            logger.debug("Using explicit TODAY period for battery history")
        elif period == 'day' and selected_date:
            tz = current_app.CACHE_TIMEZONE
            try:
                selected_date_dt = datetime.strptime(selected_date, '%Y-%m-%d')
                if selected_date_dt.tzinfo is None:
                    selected_date_dt = tz.localize(selected_date_dt)
            except ValueError:
                logger.error(f"Invalid selected_date format in history: {selected_date}")
                selected_date_dt = None
            history = get_battery_history(period, from_time, to_time, selected_date_dt)
        else:
            history = get_battery_history(period, from_time, to_time)
        
        return jsonify({'success': True, 'data': history})
    
    return app 