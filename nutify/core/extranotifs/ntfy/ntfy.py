import requests
import json
import logging
from flask import current_app

logger = logging.getLogger(__name__)

class NtfyNotifier:
    def __init__(self, config):
        self.config = config
        self.server = config.get('server', 'https://ntfy.sh')
        self.topic = config.get('topic', '')
        self.use_auth = config.get('use_auth', False)
        self.username = config.get('username', '')
        self.password = config.get('password', '')
        self.priority = config.get('priority', 3)
        self.use_tags = config.get('use_tags', True)
        self.server_name = config.get('server_name', '')
    
    def send_notification(self, title, message, event_type=None, priority=None):
        """
        Send a notification to Ntfy
        
        Args:
            title (str): Notification title
            message (str): Notification message
            event_type (str, optional): Event type for tagging. Defaults to None.
            priority (int, optional): Override default priority. Defaults to None.
        
        Returns:
            dict: Response with success status and message
        """
        try:
            # Prepare headers
            headers = {
                "Title": title,
                "Priority": str(priority if priority is not None else self.priority)
            }
            
            # Add tags based on event type if enabled
            if self.use_tags and event_type:
                tag = self._get_tag_for_event(event_type)
                if tag:
                    headers["Tags"] = tag
            
            # Add the server name to message if it exists and isn't already included
            if self.server_name and not message.startswith(f"[{self.server_name}]"):
                message = f"[{self.server_name}] {message}"
            
            # Prepare auth
            auth = None
            if self.use_auth and self.username and self.password:
                # If the password is asterisks, we need to get the real password from the database
                if self.password == '********':
                    # Get the real password from the database
                    from app import db
                    from core.extranotifs.ntfy.db import get_ntfy_model
                    
                    NtfyConfig = get_ntfy_model() or db.ModelClasses.NtfyConfig
                    config_id = self.config.get('id')
                    
                    if config_id:
                        config = NtfyConfig.query.get(config_id)
                        if config and config.password:
                            self.password = config.password
                
                # Set auth tuple with username and password
                auth = (self.username, self.password)
            
            # Send notification
            url = f"{self.server}/{self.topic}"
            logger.debug(f"Sending ntfy notification to {url} with auth: {bool(auth)}")
            
            response = requests.post(
                url,
                data=message,
                headers=headers,
                auth=auth,
                timeout=10
            )
            
            if response.status_code in [200, 201, 202]:
                logger.info(f"Ntfy notification sent successfully to {self.topic}")
                return {"success": True, "message": "Notification sent successfully"}
            else:
                logger.error(f"Failed to send Ntfy notification: {response.text}")
                return {"success": False, "message": f"Error {response.status_code}: {response.text}"}
                
        except Exception as e:
            logger.error(f"Error sending Ntfy notification: {str(e)}")
            return {"success": False, "message": str(e)}
    
    def _get_tag_for_event(self, event_type):
        """Map event types to appropriate Ntfy tags"""
        event_tags = {
            "ONLINE": "white_check_mark",
            "ONBATT": "battery",
            "LOWBATT": "warning,battery",
            "COMMOK": "signal_strength",
            "COMMBAD": "no_mobile_phones",
            "SHUTDOWN": "sos,warning",
            "REPLBATT": "wrench,battery",
            "NOCOMM": "no_entry,warning",
            "NOPARENT": "ghost"
        }
        return event_tags.get(event_type, "")

def _get_server_name():
    """Get the server name from database without fallback"""
    try:
        # Import here to avoid circular imports
        from core.db.ups import db
        from core.db.orm.orm_ups_initial_setup import init_model
        
        # Initialize the model with the logger instead of timezone
        InitialSetupModel = init_model(db.Model, logger)
        
        # Get server name directly from the database
        server_name = InitialSetupModel.get_server_name()
        logger.debug(f"Ntfy using server name: {server_name}")
        return server_name
    except Exception as e:
        logger.error(f"Failed to get server name in Ntfy: {str(e)}")
        raise  # Re-raise the error rather than providing a fallback

def test_notification(config, event_type=None):
    """
    Send a test notification using the provided configuration
    
    Args:
        config (dict): Ntfy configuration
        event_type (str, optional): Event type for test. Defaults to None.
    
    Returns:
        dict: Response with success status and message
    """
    try:
        # Get server name
        server_name = _get_server_name()
        
        # Add server_name to config
        config['server_name'] = server_name
        
        notifier = NtfyNotifier(config)
        
        event_messages = {
            "ONLINE": "Your UPS is now running on line power",
            "ONBATT": "Your UPS has switched to battery power",
            "LOWBATT": "Warning: UPS battery is running low",
            "COMMOK": "Communication with UPS has been restored",
            "COMMBAD": "Communication with UPS has been lost",
            "SHUTDOWN": "System shutdown is imminent due to low battery",
            "REPLBATT": "UPS battery needs replacement",
            "NOCOMM": "Cannot communicate with the UPS",
            "NOPARENT": "Parent process has been lost"
        }
        
        # Include server_name in title (more prominently)
        title = f"[{server_name}] Test Notification"
        if event_type:
            message = event_messages.get(event_type, f"Test notification for {event_type} event")
            title = f"[{server_name}] Test: {event_type}"
        else:
            message = "This is a test notification from Nutify"
        
        return notifier.send_notification(title, message, event_type)
    except Exception as e:
        logger.error(f"Error in Ntfy test notification: {str(e)}")
        return {"success": False, "message": str(e)}

def send_event_notification(event_type, message):
    """
    Send a notification for a specific event type
    
    Args:
        event_type (str): Event type
        message (str): Notification message
    
    Returns:
        dict: Response with success status
    """
    try:
        from app import db
        from core.extranotifs.ntfy.db import get_ntfy_model
        
        NtfyConfig = get_ntfy_model() or db.ModelClasses.NtfyConfig
        
        # Check all configurations to find one with this event type enabled
        field_name = f"notify_{event_type.lower()}"
        
        # Find all configs with this event type enabled
        # Using direct ORM query instead of dictionary conversion for efficiency
        configs_with_event = NtfyConfig.query.filter(getattr(NtfyConfig, field_name) == True).all()
        
        if not configs_with_event:
            logger.debug(f"No Ntfy configurations have {event_type} notification enabled")
            return {"success": False, "message": f"No configurations have {event_type} notification enabled"}
        
        # Use the first config that has this event type enabled
        config_obj = configs_with_event[0]
        logger.debug(f"Using Ntfy config ID {config_obj.id} (server: {config_obj.server}) for {event_type} notification")
        
        # Convert to dictionary for the notifier
        config = config_obj.to_dict()
        
        # Make sure we have the actual database password instead of masked one
        if config.get('password') == '********':
            config['password'] = config_obj.password
        
        # Get server name
        server_name = _get_server_name()
        
        # Add server_name to config
        config['server_name'] = server_name
        
        # Send notification
        notifier = NtfyNotifier(config)
        
        event_titles = {
            "ONLINE": "UPS Online",
            "ONBATT": "UPS On Battery",
            "LOWBATT": "UPS Low Battery",
            "COMMOK": "UPS Communication Restored",
            "COMMBAD": "UPS Communication Lost",
            "SHUTDOWN": "System Shutdown Imminent",
            "REPLBATT": "UPS Battery Replacement Needed",
            "NOCOMM": "UPS Not Reachable",
            "NOPARENT": "Parent Process Lost"
        }
        
        # Add server_name to the title in a more prominent way
        base_title = event_titles.get(event_type, f"UPS Event: {event_type}")
        title = f"[{server_name}] {base_title}"
        
        logger.debug(f"Sending event notification for {event_type} with config ID {config_obj.id}, server: {config_obj.server}")
        return notifier.send_notification(title, message, event_type)
        
    except Exception as e:
        logger.error(f"Error sending Ntfy event notification: {str(e)}")
        return {"success": False, "message": str(e)} 