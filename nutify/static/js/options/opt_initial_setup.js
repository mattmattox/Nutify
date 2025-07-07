/**
 * Initial Setup Variables Manager
 * Provides functionality to view and modify the initial setup configuration
 */

class InitialSetupManager {
    constructor() {
        this.formEl = null;
        this.serverNameEl = null;
        this.timezoneEl = null;
        this.upsRealpowerNominalEl = null;
        this.saveButtonEl = null;
        this.alertContainerEl = null;
        this.initialSetupData = null;
        this.isInitialized = false;
    }

    /**
     * Initialize the Initial Setup Variables manager
     */
    initialize() {
        if (this.isInitialized) return;

        // Initialize elements
        this.formEl = document.getElementById('initialSetupForm');
        this.serverNameEl = document.getElementById('server_name');
        this.timezoneEl = document.getElementById('timezone');
        this.upsRealpowerNominalEl = document.getElementById('ups_realpower_nominal');
        this.saveButtonEl = document.getElementById('saveInitialSetupBtn');
        this.alertContainerEl = document.getElementById('initialSetupAlertContainer');

        // Set up event listeners
        if (this.saveButtonEl) {
            this.saveButtonEl.addEventListener('click', () => this.saveInitialSetup());
        }

        // Load initial setup data
        this.loadInitialSetup();

        this.isInitialized = true;
    }

    /**
     * Load the initial setup configuration from the server
     */
    async loadInitialSetup() {
        try {
            const response = await fetch('/api/options/options-from-initial-setup');
            const data = await response.json();

            if (data.success && data.data) {
                this.initialSetupData = data.data;
                this.populateForm(data.data);
            } else {
                this.showAlert('Failed to load initial setup configuration', 'error');
            }
        } catch (error) {
            console.error('Error loading initial setup configuration:', error);
            this.showAlert(`Error loading initial setup configuration: ${error.message}`, 'error');
        }
    }

    /**
     * Populate the form with initial setup data
     * @param {Object} data - The initial setup data
     */
    populateForm(data) {
        if (!data) return;

        if (this.serverNameEl) {
            this.serverNameEl.value = data.server_name || '';
        }

        if (this.timezoneEl) {
            this.timezoneEl.value = data.timezone || '';
        }

        if (this.upsRealpowerNominalEl) {
            this.upsRealpowerNominalEl.value = data.ups_realpower_nominal || '';
        }
    }

    /**
     * Save the initial setup configuration
     */
    async saveInitialSetup() {
        if (!this.formEl) return;

        try {
            const formData = {
                server_name: this.serverNameEl ? this.serverNameEl.value : '',
                timezone: this.timezoneEl ? this.timezoneEl.value : '',
                ups_realpower_nominal: this.upsRealpowerNominalEl ? this.upsRealpowerNominalEl.value : null
            };

            // Validate required fields
            if (!formData.server_name || !formData.timezone) {
                this.showAlert('Server Name and Timezone are required fields', 'error');
                return;
            }

            // Show saving indicator
            this.saveButtonEl.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Saving...';
            this.saveButtonEl.disabled = true;

            // Send request to update initial setup
            const response = await fetch('/api/options/options-from-initial-setup', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(formData)
            });

            const data = await response.json();

            if (data.success) {
                this.showAlert('Initial setup configuration saved successfully. Rebooting system...', 'success');
                // Update the form with the returned data
                this.initialSetupData = data.data;
                this.populateForm(data.data);
                
                // Use createRestartCountdown to restart the system
                if (typeof createRestartCountdown === 'function') {
                    // Wait a moment to show the success message before starting the countdown
                    setTimeout(() => {
                        createRestartCountdown(this.saveButtonEl, '/api/restart');
                    }, 1500);
                } else {
                    // Fallback if createRestartCountdown is not available
                    this.saveButtonEl.innerHTML = '<i class="fas fa-check"></i> Saved';
                    this.showAlert('Restart function not available. Please restart the system manually.', 'warning');
                }
            } else {
                // Reset button state
                this.saveButtonEl.innerHTML = '<i class="fas fa-save"></i> Save & Reboot';
                this.saveButtonEl.disabled = false;
                this.showAlert(`Failed to save initial setup configuration: ${data.error}`, 'error');
            }
        } catch (error) {
            // Reset button state
            if (this.saveButtonEl) {
                this.saveButtonEl.innerHTML = '<i class="fas fa-save"></i> Save & Reboot';
                this.saveButtonEl.disabled = false;
            }

            console.error('Error saving initial setup configuration:', error);
            this.showAlert(`Error saving initial setup configuration: ${error.message}`, 'error');
        }
    }

    /**
     * Show an alert message
     * @param {string} message - The message to display
     * @param {string} type - The type of alert (success, error, info, warning)
     */
    showAlert(message, type = 'info') {
        if (!this.alertContainerEl) return;

        // Clear any existing alerts
        this.alertContainerEl.innerHTML = '';

        // Create alert element
        const alertEl = document.createElement('div');
        alertEl.className = `alert alert-${type}`;
        alertEl.innerHTML = `
            <div class="alert-icon">
                <i class="fas ${this.getAlertIcon(type)}"></i>
            </div>
            <div class="alert-message">${message}</div>
            <button class="close-btn">
                <i class="fas fa-times"></i>
            </button>
        `;

        // Add event listener to close button
        const closeBtn = alertEl.querySelector('.close-btn');
        if (closeBtn) {
            closeBtn.addEventListener('click', () => {
                alertEl.remove();
            });
        }

        // Auto-hide the alert after 5 seconds
        setTimeout(() => {
            if (alertEl.parentNode) {
                alertEl.remove();
            }
        }, 5000);

        // Add alert to container
        this.alertContainerEl.appendChild(alertEl);
    }

    /**
     * Get the appropriate icon for the alert type
     * @param {string} type - The type of alert
     * @returns {string} - The icon class
     */
    getAlertIcon(type) {
        switch (type) {
            case 'success':
                return 'fa-check-circle';
            case 'error':
                return 'fa-exclamation-circle';
            case 'warning':
                return 'fa-exclamation-triangle';
            case 'info':
            default:
                return 'fa-info-circle';
        }
    }
}

// Initialize the Initial Setup Variables manager when the page loads
function initializeInitialSetupModule() {
    const initialSetupManager = new InitialSetupManager();
    
    // Initialize the manager when the Advanced tab is selected
    const tabLinks = document.querySelectorAll('.options_tab_button');
    tabLinks.forEach(tabLink => {
        tabLink.addEventListener('click', () => {
            if (tabLink.getAttribute('data-tab') === 'Advanced') {
                initialSetupManager.initialize();
            }
        });
    });
    
    // Also initialize if Advanced tab is already selected
    const advancedButton = document.querySelector('.options_tab_button[data-tab="Advanced"]');
    if (advancedButton && advancedButton.classList.contains('active')) {
        initialSetupManager.initialize();
    }
    
    return initialSetupManager;
}

// Initialize the module when the document is ready
document.addEventListener('DOMContentLoaded', initializeInitialSetupModule); 