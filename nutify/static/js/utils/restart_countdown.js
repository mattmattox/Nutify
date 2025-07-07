/**
 * Restart Countdown Timer
 * Creates and displays a circular countdown timer in the center of the page
 * with a dimmed overlay and automatically reloads the page when countdown reaches zero.
 */

function createRestartCountdown(buttonElement, apiEndpoint = '/api/restart', redirectUrl = null) {
    // Disable button to prevent multiple clicks
    buttonElement.disabled = true;
    
    // Create overlay
    const overlay = document.createElement('div');
    overlay.className = 'countdown-overlay';
    document.body.appendChild(overlay);
    
    // Create countdown container
    const countdownContainer = document.createElement('div');
    countdownContainer.className = 'countdown-container';
    countdownContainer.innerHTML = `
        <div class="countdown-circle-container">
            <svg class="countdown-circle" viewBox="0 0 36 36">
                <path class="countdown-circle-bg"
                    d="M18 2.0845
                    a 15.9155 15.9155 0 0 1 0 31.831
                    a 15.9155 15.9155 0 0 1 0 -31.831"
                    fill="none" 
                />
                <path class="countdown-circle-progress"
                    d="M18 2.0845
                    a 15.9155 15.9155 0 0 1 0 31.831
                    a 15.9155 15.9155 0 0 1 0 -31.831"
                    stroke-dasharray="100, 100" 
                    fill="none"
                />
            </svg>
            <div class="countdown-number">30</div>
        </div>
        <div class="countdown-text">Application restarting, please wait...</div>
    `;
    
    // Add countdown to body (not replacing the button)
    document.body.appendChild(countdownContainer);
    
    // Set countdown duration in seconds
    const totalSeconds = 30;
    let secondsLeft = totalSeconds;
    
    // Get countdown elements
    const countdownNumber = countdownContainer.querySelector('.countdown-number');
    const progressCircle = countdownContainer.querySelector('.countdown-circle-progress');
    
    // Setup countdown
    const circumference = 2 * Math.PI * 15.9155; // Circle path length
    progressCircle.style.strokeDasharray = `${circumference} ${circumference}`;
    progressCircle.style.strokeDashoffset = '0';
    
    // Update countdown every second
    const countdownInterval = setInterval(() => {
        secondsLeft--;
        
        // Update text
        countdownNumber.textContent = secondsLeft;
        
        // Update progress circle
        const progress = (secondsLeft / totalSeconds) * circumference;
        progressCircle.style.strokeDashoffset = circumference - progress;
        
        // When countdown reaches zero
        if (secondsLeft <= 0) {
            clearInterval(countdownInterval);
            // Redirect to specified URL or reload current page
            window.location.href = redirectUrl || window.location.href;
        }
    }, 1000);
    
    // Show a message that the application is restarting
    if (window.notify) {
        window.notify('The application is restarting. Please wait...', 'info');
    }
    
    // Send request to restart the application
    fetch(apiEndpoint, {
        method: 'POST'
    })
    .then(response => response.json())
    .then(data => {
        if (!data.success) {
            // Only handle error case - success will continue the countdown
            clearInterval(countdownInterval);
            
            if (window.notify) {
                window.notify('Error restarting application: ' + data.message, 'error');
            }
            
            // Remove countdown and overlay
            document.body.removeChild(countdownContainer);
            document.body.removeChild(overlay);
            
            // Re-enable the button
            buttonElement.disabled = false;
        }
    })
    .catch(error => {
        console.error('Error:', error);
        // The error might be because the server is already restarting
        // We'll continue the countdown in this case
    });
    
    return countdownInterval;
} 