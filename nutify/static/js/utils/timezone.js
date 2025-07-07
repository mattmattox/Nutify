/**
 * timezone.js - Central timezone configuration for Nutify
 * 
 * Provides a single access point for the application timezone
 * Reading directly from app.py's CACHE_TIMEZONE (via meta tag)
 * 
 * STRICT MODE: This module will ONLY use the server-provided timezone
 * regardless of the user's browser timezone or physical location.
 */

// Get the timezone from the meta tag (set by Flask from app.py's CACHE_TIMEZONE)
const metaTag = document.querySelector('meta[name="timezone"]');
let timezone = metaTag && metaTag.content ? metaTag.content.trim() : null;

// Validate the timezone - NO FALLBACK ALLOWED
function isValidTimezone(tz) {
    if (!tz || tz === '') return false;
    
    try {
        Intl.DateTimeFormat(undefined, { timeZone: tz });
        return true;
    } catch (e) {
        console.error('Invalid timezone in meta tag:', tz, e);
        return false;
    }
}

// STRICT MODE: If the server-provided timezone is invalid, throw an error
// Never use fallback, never use browser timezone
if (!timezone || !isValidTimezone(timezone)) {
    const errorMessage = 'ERROR: Server provided an invalid or missing timezone. This is a critical server configuration issue.';
    console.error(errorMessage);
    // Alert the user about the critical configuration issue
    alert(errorMessage);
    // Throw an error to stop further execution - timezone is mandatory
    throw new Error('Server timezone configuration error: Timezone is mandatory and must be valid');
}

// Log timezone info when initialized successfully
console.log('Timezone initialized:', timezone);
console.log('NOTICE: Browser timezone is ignored - using server timezone only');

/**
 * Returns the application timezone configured in app.py (CACHE_TIMEZONE)
 * All application components should use this function to get the timezone
 * @returns {string} The configured timezone
 */
function cache_timezone_js() {
    return timezone;
}

/**
 * Format date to locale string using the application timezone
 * @param {Date} date - The date to format
 * @returns {string} Formatted date string
 */
function format_date_js(date) {
    return date.toLocaleDateString(undefined, { timeZone: timezone });
}

/**
 * Format time to locale string using the application timezone
 * @param {Date} date - The date to format
 * @returns {string} Formatted time string (HH:MM)
 */
function format_time_js(date) {
    return date.toLocaleTimeString(undefined, { 
        hour: '2-digit', 
        minute: '2-digit',
        timeZone: timezone 
    });
}

/**
 * Format date and time to locale string using the application timezone
 * @param {Date} date - The date to format
 * @returns {string} Formatted date and time string
 */
function format_datetime_js(date) {
    return date.toLocaleString(undefined, { timeZone: timezone });
}

/**
 * Formatter for ApexCharts tooltips and labels to ensure timezone consistency
 * @param {number|string} timestamp - Timestamp value from chart data
 * @param {string} format - Optional format string (e.g. 'HH:mm', 'dd MMM')
 * @returns {string} Formatted date string in the application timezone
 */
function format_chart_datetime(timestamp, format) {
    // If timestamp is not provided or invalid, return empty string
    if (!timestamp) return '';
    
    // Convert to date object
    const date = new Date(timestamp);
    
    // If format is not provided, use default datetime format
    if (!format) {
        return format_datetime_js(date);
    }
    
    // Basic format handling based on common ApexCharts formats
    // This could be enhanced with a more comprehensive formatting library if needed
    try {
        // Convert date to the configured timezone
        const dateOptions = { timeZone: timezone };
        
        // Format based on the provided format string
        if (format === 'HH:mm') {
            dateOptions.hour = '2-digit';
            dateOptions.minute = '2-digit';
            return date.toLocaleTimeString(undefined, dateOptions);
        } else if (format === 'HH:mm:ss') {
            dateOptions.hour = '2-digit';
            dateOptions.minute = '2-digit';
            dateOptions.second = '2-digit';
            return date.toLocaleTimeString(undefined, dateOptions);
        } else if (format === 'dd MMM') {
            dateOptions.day = '2-digit';
            dateOptions.month = 'short';
            return date.toLocaleDateString(undefined, dateOptions);
        } else if (format === 'dd MMM yyyy') {
            dateOptions.day = '2-digit';
            dateOptions.month = 'short';
            dateOptions.year = 'numeric';
            return date.toLocaleDateString(undefined, dateOptions);
        } else if (format === 'dd MMM yyyy HH:mm:ss') {
            return format_datetime_js(date);
        }
        
        // Default to standard datetime format if format is not recognized
        return format_datetime_js(date);
    } catch (e) {
        console.error('Error formatting chart date:', e);
        return date.toISOString();
    }
}

/**
 * Creates a formatter function for ApexCharts xaxis or tooltip labels
 * @param {string} format - Date format string
 * @returns {Function} Formatter function compatible with ApexCharts
 */
function create_chart_formatter(format) {
    return function(value) {
        return format_chart_datetime(value, format);
    };
}

/**
 * Parses a UTC timestamp from the server and returns a millisecond timestamp
 * that can be used to create a Date object.
 * 
 * IMPORTANT: The server stores all timestamps in UTC. This function ensures
 * those UTC timestamps are correctly interpreted without timezone shifting.
 * 
 * @param {string} utcTimestamp - UTC timestamp from server (e.g. "2023-04-23T17:43:00")
 * @returns {number} Millisecond timestamp
 */
function parse_utc_timestamp(utcTimestamp) {
    if (!utcTimestamp) return null;
    
    try {
        // Force UTC interpretation by adding Z if not present
        if (!utcTimestamp.endsWith('Z') && !utcTimestamp.includes('+')) {
            utcTimestamp = utcTimestamp + 'Z';
        }
        
        // Parse as UTC timestamp
        return new Date(utcTimestamp).getTime();
    } catch (e) {
        console.error('Error parsing UTC timestamp:', utcTimestamp, e);
        return null;
    }
}

/**
 * Helper function to create a Date object for a specific datetime in the server timezone
 * Useful when you need to create a specific date in the server's timezone context
 * 
 * @param {number} year - Year
 * @param {number} month - Month (0-11)
 * @param {number} day - Day of month
 * @param {number} hour - Hour (0-23)
 * @param {number} minute - Minute
 * @param {number} second - Second
 * @returns {Date} Date object in server timezone
 */
function create_timezone_date(year, month, day, hour = 0, minute = 0, second = 0) {
    // Create a formatter that will respect the server timezone
    const formatter = new Intl.DateTimeFormat('en-US', {
        timeZone: timezone,
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        hour12: false
    });
    
    // Create a baseline date
    const baseDate = new Date(Date.UTC(year, month, day, hour, minute, second));
    
    // Format and reinterpret to ensure timezone is respected
    const formattedParts = formatter.formatToParts(baseDate);
    
    // Extract parts
    const parts = {};
    formattedParts.forEach(part => {
        if (part.type !== 'literal') {
            parts[part.type] = parseInt(part.value, 10);
        }
    });
    
    // JavaScript months are 0-based
    return new Date(parts.year, parts.month - 1, parts.day, parts.hour, parts.minute, parts.second);
}

// Export the functions globally
window.cache_timezone_js = cache_timezone_js;
window.format_date_js = format_date_js;
window.format_time_js = format_time_js;
window.format_datetime_js = format_datetime_js;
window.format_chart_datetime = format_chart_datetime;
window.create_chart_formatter = create_chart_formatter;
window.parse_utc_timestamp = parse_utc_timestamp;
window.create_timezone_date = create_timezone_date; 