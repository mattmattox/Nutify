/**
 * Connection Alarm Modal
 * 
 * Simplified version that shows a modal when connection problems are detected
 * and automatically closes when connection is restored.
 */
class ConnectionAlarmModal {
    constructor() {
        // State tracking
        this.isVisible = false;
        this.connectionLost = false;
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = 5;
        this.lastHeartbeatTime = null;
        this.heartbeatCounter = 0;
        this.autoCloseTimer = null;
        this.initializing = true;
        this.initialConnectionCheckDone = false;
        this.modal = null; // Start with no modal in the DOM
        this.connectionErrorType = null; // New: Track the specific error type (e.g., "NOCOMM")
        this.isUsbDisconnect = false; // New: Flag to track USB disconnect specifically
        
        // Debounce and tolerance settings
        this.showModalTimer = null;
        this.showModalDelay = 800; // Wait 800ms before showing the modal (prevents flashing)
        this.connectionIssueCount = 0; // Track consecutive connection issues
        this.connectionIssueThreshold = 2; // Number of consecutive issues before showing modal
        this.pageFocused = document.visibilityState === 'visible';
        this.pageTransitioning = false;
        this.pageTransitionTimer = null;
        
        // Setup initial state
        console.log('[ConnectionAlarm] Initializing');
        
        // Store modal template HTML for later use
        this.modalTemplate = this.getModalTemplate();
        
        // Setup listeners only after a longer delay
        // This gives the app more time to establish websocket connection
        setTimeout(() => {
            this.setupListeners();
            
            // Wait an additional second before clearing initialization flag
            setTimeout(() => {
                // Only clear initialization if we have confirmed a connection
                if (this.initialConnectionCheckDone) {
                    this.initializing = false;
                    console.log('[ConnectionAlarm] Initialization complete');
                } else {
                    // Extend initialization period if needed
                    setTimeout(() => {
                        this.initializing = false;
                        console.log('[ConnectionAlarm] Extended initialization complete');
                    }, 2000);
                }
            }, 1000);
        }, 2000);
        
        // For testing - show modal on page load if URL parameter is present
        if (window.location.search.includes('show_modal=1')) {
            setTimeout(() => this.forceShowModal(), 3000);
        } else if (window.location.search.includes('show_usb_modal=1')) {
            // Special test mode for USB disconnect scenario
            setTimeout(() => {
                this.isUsbDisconnect = true;
                this.connectionErrorType = "NOCOMM";
                this.forceShowModal();
            }, 3000);
        }
    }
    
    /**
     * Get the modal template HTML
     */
    getModalTemplate() {
        return `
            <div class="connection-alarm-modal">
                <div class="connection-alarm-header">
                    <i class="fas fa-exclamation-triangle alarm-icon"></i>
                    <i class="fas fa-usb usb-icon" style="display: none;"></i>
                    <h3>Connection Alert</h3>
                </div>
                <div class="connection-alarm-body">
                    <div class="connection-alarm-status">
                        <i class="fas fa-times-circle"></i>
                        <div class="connection-alarm-message">
                            Communication with the UPS monitoring system has been interrupted.
                            Data collection may be affected.
                        </div>
                    </div>
                    
                    <div class="connection-alarm-recovery">
                        <i class="fas fa-sync-alt fa-spin connection-alarm-spinner"></i>
                        <div class="connection-alarm-recovery-text">Attempting to reconnect...</div>
                    </div>
                    
                    <div class="connection-alarm-tips">
                        <h4>Troubleshooting Tips:</h4>
                        <ul class="general-tips">
                            <li>Check that the UPS is powered on and properly connected</li>
                            <li>Verify network connectivity to the server</li>
                            <li>The system will automatically attempt to reconnect</li>
                            <li>If the issue persists, please contact your system administrator</li>
                        </ul>
                        <ul class="usb-tips" style="display: none;">
                            <li>Check that the UPS USB cable is securely connected</li>
                            <li>Ensure the UPS power is turned on</li>
                            <li>Try disconnecting and reconnecting the USB cable</li>
                            <li>The system will automatically detect when the device is reconnected</li>
                        </ul>
                    </div>
                    
                    <button id="connection-alarm-close" style="margin-top: 15px; padding: 8px 16px; background-color: var(--primary-color); color: white; border: none; border-radius: 4px; cursor: pointer;">
                        Close
                    </button>
                </div>
            </div>
        `;
    }
    
    /**
     * Create and add the modal to the DOM
     * Only when needed - not on initial load
     */
    createModal() {
        // If modal already exists, don't recreate
        if (this.modal) return;
        
        // Create the main container
        this.modal = document.createElement('div');
        this.modal.className = 'connection-alarm-backdrop';
        
        // Set the modal HTML
        this.modal.innerHTML = this.modalTemplate;
        
        // Initial state - hidden
        this.modal.style.display = 'none';
        this.modal.style.opacity = '0';
        this.modal.style.visibility = 'hidden';
        
        // Add to the DOM
        document.body.appendChild(this.modal);
        
        // Store references to DOM elements
        this.messageElement = this.modal.querySelector('.connection-alarm-message');
        this.recoveryElement = this.modal.querySelector('.connection-alarm-recovery');
        this.closeButton = this.modal.querySelector('#connection-alarm-close');
        this.alarmIcon = this.modal.querySelector('.alarm-icon');
        this.usbIcon = this.modal.querySelector('.usb-icon');
        this.generalTips = this.modal.querySelector('.general-tips');
        this.usbTips = this.modal.querySelector('.usb-tips');
        
        // Add close button handler
        this.closeButton.addEventListener('click', () => {
            this.hideModal();
        });
        
        console.log('[ConnectionAlarm] Modal created and added to DOM');
    }
    
    /**
     * Remove the modal from the DOM completely
     */
    removeModal() {
        if (this.modal && this.modal.parentNode) {
            this.modal.parentNode.removeChild(this.modal);
            this.modal = null;
            this.messageElement = null;
            this.recoveryElement = null;
            this.closeButton = null;
            this.alarmIcon = null;
            this.usbIcon = null;
            this.generalTips = null;
            this.usbTips = null;
            console.log('[ConnectionAlarm] Modal removed from DOM');
        }
    }
    
    /**
     * Setup event listeners
     */
    setupListeners() {
        console.log('[ConnectionAlarm] Setting up event listeners');
        
        // Listen for WebSocket state changes
        window.addEventListener('websocket_state', (event) => {
            const state = event.detail;
            this.handleConnectionState(state);
        });
        
        // Check for COMMBAD events - only if not in initialization
        document.addEventListener('commbad_event', () => {
            if (!this.initializing) {
                this.handleCommBadEvent();
            }
        });
        
        // Listen for WebSocket data messages (UPS status updates)
        window.addEventListener('websocket_message', (event) => {
            const data = event.detail;
            
            // Only proceed if initialization flag is cleared
            if (!this.initializing) {
                this.handleWebSocketData(data);
            } else {
                // During initialization, just check for OK status to set initialConnectionCheckDone
                const statusValue = data.ups_status;
                if (statusValue && statusValue !== 'ERROR' && statusValue !== 'NOCOMM' && statusValue !== 'TIMEOUT') {
                    // Normal status during initialization
                    this.initialConnectionCheckDone = true;
                    console.log('[ConnectionAlarm] Initial connection check passed: Normal UPS status');
                }
            }
        });
        
        // New: Listen for specific USB disconnect events from backend
        window.addEventListener('usb_disconnect', (event) => {
            if (!this.initializing) {
                console.log('[ConnectionAlarm] USB disconnect event received via WebSocket', event.detail);
                this.isUsbDisconnect = true;
                this.connectionErrorType = "NOCOMM";
                // Create modal immediately for USB disconnect
                this.createModal();
                this.updateModalForUsbDisconnect();
                this.showModal();
            }
        });
    }
    
    /**
     * Handle WebSocket data messages, checking for UPS status errors
     * @param {Object} data - The data received from the WebSocket
     */
    handleWebSocketData(data) {
        if (!data) return;
        
        // Check for error status in the UPS data
        const statusValue = data.ups_status;
        const isHeartbeat = data.is_heartbeat === true;
        // Check for USB disconnect flag from backend
        const isUsbDisconnect = data.is_usb_disconnect === true;
        
        if (isHeartbeat) {
            this.heartbeatCounter = data.heartbeat_seq || (this.heartbeatCounter + 1);
            this.lastHeartbeatTime = new Date();
            console.log(`[ConnectionAlarm] Received heartbeat #${this.heartbeatCounter}`);
        }
        
        // Check for ERROR, NOCOMM, or TIMEOUT status
        if (statusValue === 'ERROR' || statusValue === 'NOCOMM' || statusValue === 'TIMEOUT') {
            this.connectionIssueCount++;
            this.connectionErrorType = statusValue;
            
            // Update USB disconnect flag if the backend indicates this
            if (isUsbDisconnect) {
                this.isUsbDisconnect = true;
                console.log('[ConnectionAlarm] USB disconnect detected from status data');
            } else if (statusValue === 'NOCOMM') {
                // As a fallback, assume NOCOMM might be a USB disconnect
                // The backend will eventually tell us if it's a confirmed USB disconnect
                this.isUsbDisconnect = true;
            }
            
            console.log(`[ConnectionAlarm] Connection issue detected (${this.connectionIssueCount}/${this.connectionIssueThreshold})`);
            
            // Only set connection lost and show modal if we've reached the threshold
            if (this.connectionIssueCount >= this.connectionIssueThreshold) {
                this.connectionLost = true;
                
                // Cancel any auto-close timer
                if (this.autoCloseTimer) {
                    clearTimeout(this.autoCloseTimer);
                    this.autoCloseTimer = null;
                }
                
                // Create modal if it doesn't exist
                this.createModal();
                
                // Update the message to show the specific error
                if (this.messageElement) {
                    if (this.isUsbDisconnect) {
                        this.messageElement.textContent = 
                            `USB connection to UPS has been lost (${statusValue}). ` +
                            `The UPS may be unplugged or powered off. ` +
                            `The system will automatically detect when the USB device is reconnected.`;
                    } else {
                        this.messageElement.textContent = 
                            `UPS connection is in ${statusValue} state. ` +
                            `Communication with the UPS monitoring system has been interrupted. ` +
                            `Data collection may be affected.`;
                    }
                }
                
                // Update modal appearance based on error type
                this.updateModalForErrorType();
                
                // Make sure spinner is spinning
                const spinner = this.recoveryElement?.querySelector('.connection-alarm-spinner');
                if (spinner && !spinner.classList.contains('fa-spin')) {
                    spinner.classList.add('fa-spin');
                }
                
                // Update recovery text
                const recoveryText = this.recoveryElement?.querySelector('.connection-alarm-recovery-text');
                if (recoveryText) {
                    if (this.isUsbDisconnect) {
                        recoveryText.textContent = 'Scanning for USB device...';
                    } else {
                        recoveryText.textContent = 'Attempting to reconnect...';
                    }
                }
                
                this.debouncedShowModal();
                console.log(`[ConnectionAlarm] UPS error status detected: ${statusValue}`);
            }
        } 
        // If we get a normal status, reset the connection issue count
        else if (statusValue && statusValue !== 'ERROR' && statusValue !== 'NOCOMM' && statusValue !== 'TIMEOUT') {
            // Reset connection issue count
            if (this.connectionIssueCount > 0) {
                console.log('[ConnectionAlarm] Connection issue count reset');
                this.connectionIssueCount = 0;
            }
            
            // Reset USB disconnect flag
            if (this.isUsbDisconnect) {
                this.isUsbDisconnect = false;
                console.log('[ConnectionAlarm] USB connection restored');
            }
            
            // If we had lost connection and the modal is showing, prepare to auto-close
            if (this.connectionLost && this.modal && this.isVisible) {
                console.log(`[ConnectionAlarm] UPS status recovered: ${statusValue}`);
                this.connectionLost = false;
                this.connectionErrorType = null;
                
                // Cancel any pending show timers
                if (this.showModalTimer) {
                    clearTimeout(this.showModalTimer);
                    this.showModalTimer = null;
                }
                
                // Update the message
                if (this.messageElement) {
                    this.messageElement.textContent = 
                        `UPS connection has been restored (status: ${statusValue}). ` +
                        `This message will close automatically in 3 seconds.`;
                }
                
                // Stop the spinner and update recovery text
                if (this.recoveryElement) {
                    const spinner = this.recoveryElement.querySelector('.connection-alarm-spinner');
                    if (spinner) spinner.classList.remove('fa-spin');
                    
                    const recoveryText = this.recoveryElement.querySelector('.connection-alarm-recovery-text');
                    if (recoveryText) recoveryText.textContent = 'Connection restored!';
                }
                
                // Auto-close the modal after 3 seconds
                this.autoCloseTimer = setTimeout(() => {
                    this.hideModal();
                    // Also completely remove the modal from DOM after hiding
                    setTimeout(() => this.removeModal(), 500);
                    this.autoCloseTimer = null;
                }, 3000);
            }
        }
    }
    
    /**
     * Update modal appearance based on error type
     */
    updateModalForErrorType() {
        if (!this.modal) return;
        
        if (this.isUsbDisconnect) {
            this.updateModalForUsbDisconnect();
        } else {
            // Regular connection issue
            if (this.alarmIcon) this.alarmIcon.style.display = 'inline-block';
            if (this.usbIcon) this.usbIcon.style.display = 'none';
            if (this.generalTips) this.generalTips.style.display = 'block';
            if (this.usbTips) this.usbTips.style.display = 'none';
        }
    }
    
    /**
     * Update modal appearance for USB disconnect
     */
    updateModalForUsbDisconnect() {
        if (!this.modal) {
            this.createModal();
        }
        
        // Switch icons
        if (this.alarmIcon) this.alarmIcon.style.display = 'none';
        if (this.usbIcon) this.usbIcon.style.display = 'inline-block';
        
        // Switch tips
        if (this.generalTips) this.generalTips.style.display = 'none';
        if (this.usbTips) this.usbTips.style.display = 'block';
        
        // Update message if it exists
        if (this.messageElement) {
            this.messageElement.textContent = 
                `USB connection to UPS has been lost. ` +
                `The UPS may be unplugged or powered off. ` +
                `The system will automatically detect when the USB device is reconnected.`;
        }
        
        // Update recovery message
        const recoveryText = this.recoveryElement?.querySelector('.connection-alarm-recovery-text');
        if (recoveryText) {
            recoveryText.textContent = 'Scanning for USB device...';
        }
        
        console.log('[ConnectionAlarm] Modal updated for USB disconnect');
    }
    
    /**
     * Handle WebSocket connection state changes
     */
    handleConnectionState(state) {
        if (!state) return;
        
        if (state.reconnecting) {
            // Attempting to reconnect - connection lost
            this.connectionIssueCount++;
            this.reconnectAttempts = state.reconnectAttempt || this.reconnectAttempts + 1;
            
            console.log(`[ConnectionAlarm] Connection issue detected (${this.connectionIssueCount}/${this.connectionIssueThreshold})`);
            
            // Only proceed if issue threshold is met and we're not in initialization or page transition
            if (this.connectionIssueCount >= this.connectionIssueThreshold && 
                !this.initializing && 
                !this.pageTransitioning) {
                
                this.connectionLost = true;
                
                // Create modal if needed
                this.createModal();
                
                // Update modal appearance based on error type
                this.updateModalForErrorType();
                
                this.debouncedShowModal();
                console.log(`[ConnectionAlarm] Connection lost, attempt ${this.reconnectAttempts}`);
            }
        } 
        else if (state.maxAttemptsReached) {
            // Max reconnection attempts reached
            if (!this.initializing && !this.pageTransitioning) {
                this.connectionLost = true;
                
                // Create modal if needed
                this.createModal();
                
                if (this.messageElement) {
                    this.messageElement.textContent = 'Maximum reconnection attempts reached. Please refresh the page or contact your administrator.';
                }
                
                if (this.recoveryElement) {
                    this.recoveryElement.style.display = 'none';
                }
                
                // Update modal appearance based on error type
                this.updateModalForErrorType();
                
                this.debouncedShowModal();
                console.log('[ConnectionAlarm] Max reconnection attempts reached');
            }
        } else if (state.connected === true) {
            // Connection established successfully
            console.log('[ConnectionAlarm] WebSocket connection established');
            
            // Reset issue count since we have a successful connection
            this.connectionIssueCount = 0;
            this.isUsbDisconnect = false;
            this.connectionErrorType = null;
            
            // If we were in connection lost state, update
            if (this.connectionLost) {
                this.connectionLost = false;
                
                // Cancel any pending show timers
                if (this.showModalTimer) {
                    clearTimeout(this.showModalTimer);
                    this.showModalTimer = null;
                }
                
                // If the modal is visible, prepare to hide it
                if (this.isVisible && this.modal) {
                    // Update message
                    if (this.messageElement) {
                        this.messageElement.textContent = 'Connection has been restored. This message will close automatically.';
                    }
                    
                    // Schedule auto-close
                    this.autoCloseTimer = setTimeout(() => {
                        this.hideModal();
                        setTimeout(() => this.removeModal(), 500);
                    }, 3000);
                }
            }
            
            // If we're in initialization phase, mark connection as good
            if (this.initializing) {
                this.initialConnectionCheckDone = true;
            }
        }
    }
    
    /**
     * Handle COMMBAD event
     */
    handleCommBadEvent() {
        // Only process COMMBAD if we're not in initialization or page transition
        if (!this.initializing && !this.pageTransitioning) {
            this.connectionIssueCount++;
            this.connectionErrorType = "COMMBAD";
            
            if (this.connectionIssueCount >= this.connectionIssueThreshold) {
                this.connectionLost = true;
                // Create modal if needed
                this.createModal();
                
                // Update modal appearance based on error type
                this.updateModalForErrorType();
                
                this.debouncedShowModal();
                console.log('[ConnectionAlarm] COMMBAD event detected');
            } else {
                console.log(`[ConnectionAlarm] COMMBAD event detected (${this.connectionIssueCount}/${this.connectionIssueThreshold})`);
            }
        }
    }
    
    /**
     * Debounced show modal - prevents flashing during brief connection issues
     */
    debouncedShowModal() {
        // Clear any existing timer
        if (this.showModalTimer) {
            clearTimeout(this.showModalTimer);
        }
        
        // During page transition or when page is not focused, don't show the modal
        if (this.pageTransitioning || !this.pageFocused) {
            console.log('[ConnectionAlarm] Ignoring show request during page transition or when not focused');
            return;
        }
        
        // Set a timer to show the modal after delay
        this.showModalTimer = setTimeout(() => {
            this.showModal();
            this.showModalTimer = null;
        }, this.showModalDelay);
        
        console.log(`[ConnectionAlarm] Modal show debounced (will show in ${this.showModalDelay}ms if issue persists)`);
    }
    
    /**
     * Show the modal
     */
    showModal() {
        // Don't show modal during initialization phase or when refreshing/navigating
        if (this.initializing || this.pageTransitioning || !this.pageFocused) {
            console.log('[ConnectionAlarm] Ignoring show request during initialization/transition');
            return;
        }
        
        // Ensure the modal exists
        if (!this.modal) {
            this.createModal();
            
            // Update modal appearance based on error type
            this.updateModalForErrorType();
        }
        
        if (!this.isVisible && this.modal) {
            // Manually manipulate styles
            this.modal.style.display = 'flex';
            this.modal.style.opacity = '1';
            this.modal.style.visibility = 'visible';
            this.isVisible = true;
            console.log('[ConnectionAlarm] Modal shown');
        }
    }
    
    /**
     * Hide the modal - done manually by user or automatically when connection is restored
     */
    hideModal() {
        if (this.isVisible && this.modal) {
            this.modal.style.display = 'none';
            this.modal.style.opacity = '0';
            this.modal.style.visibility = 'hidden';
            this.isVisible = false;
            console.log('[ConnectionAlarm] Modal hidden');
            
            // Cancel any existing auto-close timer
            if (this.autoCloseTimer) {
                clearTimeout(this.autoCloseTimer);
                this.autoCloseTimer = null;
            }
        }
    }
    
    /**
     * Force show the modal (for testing)
     */
    forceShowModal() {
        // Override initialization check for direct testing
        this.initializing = false;
        this.pageTransitioning = false;
        // Create modal if needed
        this.createModal();
        
        // Update modal appearance based on error type  
        this.updateModalForErrorType();
        
        this.showModal();
    }
}

// Create the modal instance when the DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    window.connectionAlarmModal = new ConnectionAlarmModal();
    
    // Test trigger via keyboard shortcut (Alt+M)
    document.addEventListener('keydown', (event) => {
        if (event.altKey && event.key === 'm') {
            console.log('[ConnectionAlarm] Manual trigger via keyboard shortcut (Alt+M)');
            window.connectionAlarmModal.forceShowModal();
        }
        
        // Test USB disconnect modal (Alt+U)
        if (event.altKey && event.key === 'u') {
            console.log('[ConnectionAlarm] Manual USB disconnect trigger via keyboard shortcut (Alt+U)');
            window.connectionAlarmModal.isUsbDisconnect = true;
            window.connectionAlarmModal.connectionErrorType = "NOCOMM";
            window.connectionAlarmModal.forceShowModal();
        }
    });
    
    // Add a custom COMMBAD event trigger for testing if in test mode
    if (window.location.search.includes('test_modal=1')) {
        // Set a longer delay to ensure the modal is fully initialized
        setTimeout(() => {
            document.dispatchEvent(new CustomEvent('commbad_event'));
        }, 3000);
    } else if (window.location.search.includes('test_usb_modal=1')) {
        // Test USB disconnect modal
        setTimeout(() => {
            window.connectionAlarmModal.isUsbDisconnect = true;
            window.connectionAlarmModal.connectionErrorType = "NOCOMM";
            window.connectionAlarmModal.forceShowModal();
        }, 3000);
    }
}); 