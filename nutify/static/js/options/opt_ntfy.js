/**
 * Ntfy Configuration Module
 * Handles Ntfy push notification configuration and settings
 */

class NtfyManager {
    constructor() {
        try {
            this.initializeEventListeners();
            this.loadNtfyConfig().then(() => {
                try {
                    this.loadNtfySettings();
                } catch (settingsError) {
                    if (window.webLogger) {
                        window.webLogger.error('Failed to load Ntfy settings', settingsError);
                    }
                }
            }).catch(configError => {
                if (window.webLogger) {
                    window.webLogger.error('Failed to load Ntfy configuration', configError);
                }
            });
        } catch (error) {
            if (window.webLogger) {
                window.webLogger.error('Failed to initialize Ntfy functionality', error);
            }
            
            // Show error message
            const errorContainer = document.getElementById('options_ntfy_status');
            if (errorContainer) {
                errorContainer.textContent = "Failed to initialize Ntfy functionality";
                errorContainer.className = "options_alert error";
                errorContainer.classList.remove('hidden');
            }
        }
    }

    /**
     * Initialize all event listeners for Ntfy configuration
     */
    initializeEventListeners() {
        // Add Ntfy Configuration button
        const addNtfyConfigBtn = document.getElementById('addNtfyConfigBtn');
        if (addNtfyConfigBtn) {
            addNtfyConfigBtn.addEventListener('click', () => {
                this.clearNtfyFormFields();
                this.setNtfyConfiguredState(false);
            });
        }
        
        // Test Ntfy button
        const testNtfyBtn = document.getElementById('testNtfyBtn');
        if (testNtfyBtn) {
            testNtfyBtn.addEventListener('click', () => this.testNtfyFromForm());
        }
        
        // Save Ntfy Config button
        const saveNtfyConfigBtn = document.getElementById('saveNtfyConfigBtn');
        if (saveNtfyConfigBtn) {
            saveNtfyConfigBtn.addEventListener('click', () => this.saveNtfyConfig());
        }
        
        // Cancel Ntfy Config button
        const cancelNtfyConfigBtn = document.getElementById('cancelNtfyConfigBtn');
        if (cancelNtfyConfigBtn) {
            cancelNtfyConfigBtn.addEventListener('click', () => {
                // Show header card and hide form card
                document.getElementById('addNtfyConfigContainer').style.display = 'block';
                document.getElementById('ntfyConfigFormCard').style.display = 'none';
            });
        }
        
        // Reconfigure Ntfy button
        const reconfigureNtfyBtn = document.getElementById('reconfigureNtfyBtn');
        if (reconfigureNtfyBtn) {
            reconfigureNtfyBtn.addEventListener('click', () => {
                this.setNtfyConfiguredState(false);
            });
        }
        
        // Server type change
        const ntfyServerType = document.getElementById('ntfy_server_type');
        if (ntfyServerType) {
            ntfyServerType.addEventListener('change', () => {
                const customServerContainer = document.getElementById('custom_server_container');
                if (ntfyServerType.value === 'custom') {
                    customServerContainer.style.display = 'block';
                } else {
                    customServerContainer.style.display = 'none';
                    document.getElementById('ntfy_custom_server').value = '';
                }
            });
        }
        
        // Auth checkbox
        const ntfyUseAuth = document.getElementById('ntfy_use_auth');
        if (ntfyUseAuth) {
            ntfyUseAuth.addEventListener('change', () => {
                const authFields = document.querySelectorAll('.auth-field');
                authFields.forEach(field => {
                    field.style.display = ntfyUseAuth.checked ? 'block' : 'none';
                });
            });
        }
        
        // Ntfy notification checkboxes
        const ntfyCheckboxes = document.querySelectorAll('.options_ntfy_checkbox');
        ntfyCheckboxes.forEach(checkbox => {
            checkbox.addEventListener('change', () => {
                const eventType = checkbox.getAttribute('data-event-type');
                const enabled = checkbox.checked;
                const dropdown = document.querySelector(`.options_ntfy_select[data-event-type="${eventType}"]`);
                
                // If turning off, reset dropdown to default "Select..." option
                if (!enabled && dropdown) {
                    const previousValue = dropdown.value;
                    // Save previous value in a data attribute for debugging purposes
                    dropdown.dataset.previousValue = previousValue;
                    dropdown.value = '';
                    console.log(`Ntfy notification for ${eventType} disabled, reset dropdown from ${previousValue} to default`);
                    
                    // Update the notification setting (disable it)
                    this.updateNtfyNotificationSetting(eventType, false, previousValue);
                    
                    return;
                }
                
                // Get configId directly from the dropdown value
                const configId = dropdown ? dropdown.value : '';
                
                // Store the current configId in the checkbox's data attribute
                if (enabled && configId) {
                    checkbox.dataset.configId = configId;
                }
                
                // Log the operation for debugging
                console.log(`Checkbox for ${eventType} changed to ${enabled}, using config ${configId}`);
                
                this.updateNtfyNotificationSetting(eventType, enabled, configId);
            });
        });
        
        // Ntfy notification dropdowns
        const ntfyDropdowns = document.querySelectorAll('.options_ntfy_select');
        ntfyDropdowns.forEach(dropdown => {
            dropdown.addEventListener('change', () => {
                const eventType = dropdown.getAttribute('data-event-type');
                const configId = dropdown.value;
                const checkbox = document.getElementById(`ntfy_${eventType.toLowerCase()}`);
                const testButton = document.querySelector(`.options_ntfy_test[data-event-type="${eventType}"]`);
                
                console.log(`Dropdown for ${eventType} changed to ${configId}`);
                
                // If a configuration is selected
                if (configId && configId !== '') {
                    // Show the checkbox and test button
                    if (checkbox) {
                        checkbox.style.display = 'inline-block';
                        // Automatically check the checkbox when a configuration is selected
                        checkbox.checked = true;
                        
                        // Store the current configId in a data attribute for when the user checks the box
                        checkbox.dataset.configId = configId;
                        
                        // Update server with the new configuration
                        this.updateNtfyNotificationSetting(eventType, true, configId);
                    }
                    
                    if (testButton) {
                        testButton.style.display = 'inline-block';
                    }
                } else {
                    // No configuration selected, hide and uncheck controls
                    if (checkbox) {
                        checkbox.style.display = 'none';
                        checkbox.checked = false;
                        checkbox.dataset.configId = '';
                    }
                    
                    if (testButton) {
                        testButton.style.display = 'none';
                    }
                    
                    // Ensure the notification is disabled in the server
                    this.updateNtfyNotificationSetting(eventType, false, '');
                }
            });
            
            // Initialize visibility on page load
            const eventType = dropdown.getAttribute('data-event-type');
            const configId = dropdown.value;
            const checkbox = document.getElementById(`ntfy_${eventType.toLowerCase()}`);
            const testButton = document.querySelector(`.options_ntfy_test[data-event-type="${eventType}"]`);
            
            console.log(`Initial state for ${eventType}: config=${configId}`);
            
            // Hide checkboxes by default, they will be shown when loadNtfySettings is called
            if (checkbox) checkbox.style.display = 'none';
            if (testButton) testButton.style.display = 'none';
        });
        
        // Ntfy test buttons
        const ntfyTestButtons = document.querySelectorAll('.options_ntfy_test');
        ntfyTestButtons.forEach(button => {
            button.addEventListener('click', async () => {
                const eventType = button.getAttribute('data-event-type');
                const dropdown = document.querySelector(`.options_ntfy_select[data-event-type="${eventType}"]`);
                const configId = dropdown ? dropdown.value : '';
                
                console.log(`Testing Ntfy notification for event ${eventType} with config ID: ${configId}`);
                
                if (!configId) {
                    this.showNtfyAlert('Please select a Ntfy configuration first', 'error');
                    return;
                }
                
                // Show loader
                button.querySelector('.btn-text').style.display = 'none';
                button.querySelector('.btn-loader').classList.remove('hidden');
                
                try {
                    // Send test notification
                    const response = await fetch(`/api/ntfy/test/${configId}?event_type=${eventType}`, {
                        method: 'POST'
                    });
                    
                    if (!response.ok) {
                        throw new Error(`Server returned ${response.status}: ${response.statusText}`);
                    }
                    
                    const data = await response.json();
                    console.log('Ntfy test response:', data);
                    
                    if (data.success) {
                        this.showNtfyAlert(`Test notification for ${eventType} sent successfully!`, 'success');
                        
                        // Add a notification within the page for better visibility
                        if (window.notify) {
                            window.notify(`Test notification for ${eventType} sent to Ntfy. Please check your Ntfy app.`, 'info', 8000);
                        }
                    } else {
                        this.showNtfyAlert(`Error: ${data.message || 'Failed to send notification'}`, 'error');
                        console.error('Ntfy test failed:', data.message);
                    }
                } catch (error) {
                    this.showNtfyAlert(`Error: ${error.message}`, 'error');
                    console.error('Ntfy test error:', error);
                } finally {
                    // Hide loader
                    button.querySelector('.btn-text').style.display = 'inline';
                    button.querySelector('.btn-loader').classList.add('hidden');
                }
            });
        });
    }

    /**
     * Clear all form fields in the Ntfy configuration form
     */
    clearNtfyFormFields() {
        document.getElementById('ntfy_config_id').value = '';
        document.getElementById('ntfy_server_type').value = 'ntfy.sh';
        document.getElementById('ntfy_custom_server').value = '';
        document.getElementById('ntfy_topic').value = '';
        document.getElementById('ntfy_use_auth').checked = false;
        document.getElementById('ntfy_username').value = '';
        document.getElementById('ntfy_password').value = '';
        document.getElementById('ntfy_priority').value = '3';
        document.getElementById('ntfy_use_tags').checked = true;
        
        // Hide auth fields
        document.querySelectorAll('.auth-field').forEach(field => {
            field.style.display = 'none';
        });
        
        // Hide custom server field
        document.getElementById('custom_server_container').style.display = 'none';
        
        // Hide the Save Configuration button until a successful test
        const saveNtfyConfigBtn = document.getElementById('saveNtfyConfigBtn');
        if (saveNtfyConfigBtn) {
            saveNtfyConfigBtn.style.display = 'none';
        }
    }

    /**
     * Test Ntfy notification using form data
     */
    testNtfyFromForm() {
        const serverType = document.getElementById('ntfy_server_type').value;
        const customServer = document.getElementById('ntfy_custom_server').value;
        const topic = document.getElementById('ntfy_topic').value;
        const useAuth = document.getElementById('ntfy_use_auth').checked;
        const username = document.getElementById('ntfy_username').value;
        const password = document.getElementById('ntfy_password').value;
        const priority = document.getElementById('ntfy_priority').value;
        const useTags = document.getElementById('ntfy_use_tags').checked;
        
        const server = serverType === 'ntfy.sh' ? 'https://ntfy.sh' : customServer;
        
        if (!topic) {
            this.showAlert('ntfyStatus', 'Please enter a topic name', 'error');
            return;
        }
        
        if (serverType === 'custom' && !customServer) {
            this.showAlert('ntfyStatus', 'Please enter a server URL', 'error');
            return;
        }
        
        // Show loader
        const testBtn = document.getElementById('testNtfyBtn');
        testBtn.querySelector('.btn-text').style.display = 'none';
        testBtn.querySelector('.btn-loader').classList.remove('hidden');
        
        // Prepare test data
        const testData = {
            server: server,
            topic: topic,
            use_auth: useAuth,
            username: username,
            password: password,
            priority: priority,
            use_tags: useTags,
            test: true
        };
        
        // Send test notification
        fetch('/api/ntfy/test', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(testData)
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                this.showAlert('ntfyStatus', 'Test notification sent successfully!', 'success');
                
                // Show the Save Configuration button only after successful test
                const saveNtfyConfigBtn = document.getElementById('saveNtfyConfigBtn');
                if (saveNtfyConfigBtn) {
                    saveNtfyConfigBtn.style.display = 'flex';
                }
            } else {
                this.showAlert('ntfyStatus', `Error: ${data.message}`, 'error');
                
                // Hide the Save Configuration button if the test fails
                const saveNtfyConfigBtn = document.getElementById('saveNtfyConfigBtn');
                if (saveNtfyConfigBtn) {
                    saveNtfyConfigBtn.style.display = 'none';
                }
            }
        })
        .catch(error => {
            this.showAlert('ntfyStatus', `Error: ${error.message}`, 'error');
            
            // Hide the Save Configuration button if there's an error
            const saveNtfyConfigBtn = document.getElementById('saveNtfyConfigBtn');
            if (saveNtfyConfigBtn) {
                saveNtfyConfigBtn.style.display = 'none';
            }
        })
        .finally(() => {
            // Hide loader
            testBtn.querySelector('.btn-text').style.display = 'inline';
            testBtn.querySelector('.btn-loader').classList.add('hidden');
        });
    }

    /**
     * Save Ntfy configuration
     */
    saveNtfyConfig() {
        const configId = document.getElementById('ntfy_config_id').value;
        const serverType = document.getElementById('ntfy_server_type').value;
        const customServer = document.getElementById('ntfy_custom_server').value;
        const topic = document.getElementById('ntfy_topic').value;
        const useAuth = document.getElementById('ntfy_use_auth').checked;
        const username = document.getElementById('ntfy_username').value;
        const password = document.getElementById('ntfy_password').value;
        const priority = document.getElementById('ntfy_priority').value;
        const useTags = document.getElementById('ntfy_use_tags').checked;
        
        const server = serverType === 'ntfy.sh' ? 'https://ntfy.sh' : customServer;
        
        if (!topic) {
            this.showAlert('ntfyStatus', 'Please enter a topic name', 'error');
            return;
        }
        
        if (serverType === 'custom' && !customServer) {
            this.showAlert('ntfyStatus', 'Please enter a server URL', 'error');
            return;
        }
        
        if (useAuth && (!username || !password)) {
            this.showAlert('ntfyStatus', 'Please enter both username and password for authentication', 'error');
            return;
        }
        
        // Prepare config data
        const configData = {
            id: configId || null,
            server_type: serverType,
            server: server,
            topic: topic,
            use_auth: useAuth,
            username: username,
            password: password,
            priority: priority,
            use_tags: useTags
        };
        
        // Save configuration
        fetch('/api/ntfy/config', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(configData)
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                this.showAlert('ntfyStatus', 'Configuration saved successfully!', 'success');
                this.loadNtfyConfig();
                this.setNtfyConfiguredState(true, data.config);
                
                // Update dropdowns
                this.populateNtfyDropdowns();
            } else {
                this.showAlert('ntfyStatus', `Error: ${data.message}`, 'error');
            }
        })
        .catch(error => {
            this.showAlert('ntfyStatus', `Error: ${error.message}`, 'error');
        });
    }

    /**
     * Update Ntfy configuration summary
     * @param {Object} config - Ntfy configuration object
     */
    updateNtfySummary(config) {
        const configList = document.getElementById('ntfyConfigList');
        
        // Create or update the config summary
        let configElement = document.getElementById(`ntfy-config-${config.id}`);
        
        if (!configElement) {
            configElement = document.createElement('div');
            configElement.id = `ntfy-config-${config.id}`;
            configElement.className = 'email_config_item';
            configList.appendChild(configElement);
        }
        
        const serverDisplay = config.server_type === 'ntfy.sh' ? 'ntfy.sh (Official)' : config.server;
        
        configElement.innerHTML = `
            <div class="email_config_info">
                <div class="email_config_name">
                    <i class="fas fa-bell"></i>
                    <span>${serverDisplay}</span>
                </div>
                <div class="email_config_details">
                    <span>Topic: ${config.topic}</span>
                    ${config.use_auth ? '<span><i class="fas fa-lock"></i> Authentication enabled</span>' : ''}
                </div>
            </div>
            <div class="email_config_actions">
                <button type="button" class="email_config_action" onclick="ntfyManager.testNtfyConfig(${config.id})">
                    <i class="fas fa-paper-plane"></i>
                    Test
                </button>
                <button type="button" class="email_config_action" onclick="ntfyManager.editNtfyConfig(${config.id})">
                    <i class="fas fa-edit"></i>
                    Edit
                </button>
                <button type="button" class="email_config_action" onclick="ntfyManager.deleteNtfyConfig(${config.id})">
                    <i class="fas fa-trash"></i>
                    Delete
                </button>
                <button type="button" class="email_config_action ${config.is_default ? 'default-config' : ''}" 
                        onclick="ntfyManager.setDefaultNtfyConfig(${config.id})" id="ntfy-default-${config.id}">
                    <i class="fas fa-star"></i>
                    ${config.is_default ? 'Default' : 'Set Default'}
                </button>
            </div>
        `;
    }

    /**
     * Render all Ntfy configurations
     * @param {Array} configs - Array of Ntfy configurations
     */
    renderNtfyConfigs(configs) {
        const configList = document.getElementById('ntfyConfigList');
        configList.innerHTML = '';
        
        if (configs && configs.length > 0) {
            configs.forEach(config => {
                // Create the configuration row using the email_config_row class
                const configRow = document.createElement('div');
                configRow.className = 'email_config_row';
                configRow.dataset.id = config.id;
                configRow.id = `ntfy-config-${config.id}`;
                
                // Add default badge if this is the default configuration
                const defaultBadge = config.is_default ? 
                    '<span class="default-badge"><i class="fas fa-check-circle"></i> Default</span>' : '';
                
                const serverDisplay = config.server_type === 'custom' ? config.server : 'ntfy.sh';
                
                configRow.innerHTML = `
                    <div class="email_config_info">
                        <div class="email_provider_info">
                            <i class="fas fa-bell"></i> <span>${serverDisplay}</span>
                            ${defaultBadge}
                        </div>
                        <div class="email_address_info">
                            <i class="fas fa-tag"></i> <span>Topic: ${config.topic}</span>
                            ${config.use_auth ? '<span class="ms-3"><i class="fas fa-lock"></i> Authentication enabled</span>' : ''}
                        </div>
                    </div>
                    <div class="email_config_actions">
                        <button type="button" class="options_btn options_btn_secondary test-btn" data-id="${config.id}">
                            <i class="fas fa-paper-plane"></i> Test
                        </button>
                        <button type="button" class="options_btn options_btn_secondary edit-btn" data-id="${config.id}">
                            <i class="fas fa-cog"></i> Edit
                        </button>
                        <button type="button" class="options_btn options_btn_secondary delete-btn" data-id="${config.id}">
                            <i class="fas fa-trash"></i> Delete
                        </button>
                        ${!config.is_default ? `
                            <button type="button" class="options_btn options_btn_secondary default-btn" data-id="${config.id}">
                                <i class="fas fa-star"></i> Set Default
                            </button>
                        ` : `
                            <button type="button" class="options_btn options_btn_secondary default-config" disabled>
                                <i class="fas fa-star"></i> Default
                            </button>
                        `}
                    </div>
                `;
                
                configList.appendChild(configRow);
            });
            
            // Add event listeners to the buttons
            document.querySelectorAll('.test-btn').forEach(btn => {
                btn.addEventListener('click', () => {
                    const configId = btn.getAttribute('data-id');
                    this.testNtfyConfig(configId);
                });
            });
            
            document.querySelectorAll('.edit-btn').forEach(btn => {
                btn.addEventListener('click', () => {
                    const configId = btn.getAttribute('data-id');
                    this.editNtfyConfig(configId);
                });
            });
            
            document.querySelectorAll('.delete-btn').forEach(btn => {
                btn.addEventListener('click', () => {
                    const configId = btn.getAttribute('data-id');
                    this.deleteNtfyConfig(configId);
                });
            });
            
            document.querySelectorAll('.default-btn').forEach(btn => {
                btn.addEventListener('click', () => {
                    const configId = btn.getAttribute('data-id');
                    this.setDefaultNtfyConfig(configId);
                });
            });
        } else {
            configList.innerHTML = '<div class="no-config-message"><i class="fas fa-info-circle"></i> No Ntfy configurations found. Add one to get started.</div>';
        }
    }

    /**
     * Load all Ntfy configurations from the server
     */
    async loadNtfyConfig() {
        try {
            console.log("Loading Ntfy configurations...");
            const response = await fetch('/api/ntfy/configs');
            
            if (!response.ok) {
                console.error(`Failed to fetch Ntfy configurations: ${response.status} ${response.statusText}`);
                return false;
            }
            
            const data = await response.json();
            
            if (!data.success) {
                console.error("Server reported failure when fetching Ntfy configurations");
                return false;
            }
            
            const configs = data.configs || [];
            console.log(`Loaded ${configs.length} Ntfy configurations`);
            
            // Store configs for later reference
            this.ntfyConfigs = configs;
            
            // Show/hide sections based on whether we have configs
            const ntfyConfigSummary = document.getElementById('ntfyConfigSummary');
            // Target ONLY the Ntfy notification section by finding the h2 with text "Ntfy Notifications"
            const ntfyNotificationSections = Array.from(document.querySelectorAll('.options_card.mt-4 h2'))
                .filter(h2 => h2.textContent.trim() === 'Ntfy Notifications')
                .map(h2 => h2.closest('.options_card.mt-4'));
            
            if (configs.length === 0) {
                // Hide the sections if no configs
                if (ntfyConfigSummary) ntfyConfigSummary.style.display = 'none';
                // Hide only the Ntfy notification section
                ntfyNotificationSections.forEach(section => {
                    if (section) section.style.display = 'none';
                });
                
                return false;
            }
            
            // Show the sections if we have configs
            if (ntfyConfigSummary) ntfyConfigSummary.style.display = 'block';
            // Show only the Ntfy notification section
            ntfyNotificationSections.forEach(section => {
                if (section) section.style.display = 'block';
            });
            
            // Use the existing renderNtfyConfigs function to display the configs
            this.renderNtfyConfigs(configs);
            
            // Follow a specific order to ensure proper initialization:
            
            // Step 1: First populate dropdown options with available configs
            await this.populateNtfyDropdowns();
            
            // Step 2: Then load and display the notification settings
            await this.loadNtfySettings();
            
            return true;
        } catch (error) {
            console.error("Error loading Ntfy configurations:", error);
            return false;
        }
    }

    /**
     * Set the configured state of the Ntfy form
     * @param {boolean} isConfigured - Whether a configuration is active
     * @param {Object} config - The active configuration
     */
    setNtfyConfiguredState(isConfigured, config = {}) {
        const headerCard = document.getElementById('addNtfyConfigContainer');
        const formCard = document.getElementById('ntfyConfigFormCard');
        const configStatus = document.getElementById('ntfyConfigurationStatus');
        
        if (isConfigured) {
            headerCard.style.display = 'block';
            formCard.style.display = 'none';
            configStatus.classList.remove('hidden');
            
            // Update status text with config details
            const serverDisplay = config.server_type === 'ntfy.sh' ? 'ntfy.sh (Official)' : config.server;
            configStatus.querySelector('p').textContent = `Ntfy configured successfully: ${serverDisplay} - Topic: ${config.topic}`;
        } else {
            headerCard.style.display = 'none';
            formCard.style.display = 'block';
            configStatus.classList.add('hidden');
            
            // Hide the Save Configuration button until a successful test
            const saveNtfyConfigBtn = document.getElementById('saveNtfyConfigBtn');
            if (saveNtfyConfigBtn) {
                saveNtfyConfigBtn.style.display = 'none';
            }
        }
    }

    /**
     * Edit a Ntfy configuration
     * @param {number} configId - Configuration ID to edit
     */
    editNtfyConfig(configId) {
        fetch(`/api/ntfy/config/${configId}`)
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    const config = data.config;
                    
                    // Fill form with config data
                    document.getElementById('ntfy_config_id').value = config.id;
                    document.getElementById('ntfy_server_type').value = config.server_type;
                    document.getElementById('ntfy_topic').value = config.topic;
                    document.getElementById('ntfy_use_auth').checked = config.use_auth;
                    document.getElementById('ntfy_priority').value = config.priority;
                    document.getElementById('ntfy_use_tags').checked = config.use_tags;
                    
                    // Handle custom server
                    if (config.server_type === 'custom') {
                        document.getElementById('custom_server_container').style.display = 'block';
                        document.getElementById('ntfy_custom_server').value = config.server;
                    } else {
                        document.getElementById('custom_server_container').style.display = 'none';
                        document.getElementById('ntfy_custom_server').value = '';
                    }
                    
                    // Handle auth fields
                    if (config.use_auth) {
                        document.querySelectorAll('.auth-field').forEach(field => {
                            field.style.display = 'block';
                        });
                        document.getElementById('ntfy_username').value = config.username;
                        // Password is not returned for security reasons
                        document.getElementById('ntfy_password').value = '';
                        document.getElementById('ntfy_password').placeholder = '********';
                    } else {
                        document.querySelectorAll('.auth-field').forEach(field => {
                            field.style.display = 'none';
                        });
                        document.getElementById('ntfy_username').value = '';
                        document.getElementById('ntfy_password').value = '';
                    }
                    
                    // Hide the Save Configuration button until a successful test
                    const saveNtfyConfigBtn = document.getElementById('saveNtfyConfigBtn');
                    if (saveNtfyConfigBtn) {
                        saveNtfyConfigBtn.style.display = 'none';
                    }
                    
                    // Show form
                    this.setNtfyConfiguredState(false);
                }
            })
            .catch(error => {
                
                this.showAlert('ntfyStatus', `Error: ${error.message}`, 'error');
            });
    }

    /**
     * Delete a Ntfy configuration
     * @param {number} configId - Configuration ID to delete
     */
    deleteNtfyConfig(configId) {
        if (confirm('Are you sure you want to delete this Ntfy configuration?')) {
            fetch(`/api/ntfy/config/${configId}`, {
                method: 'DELETE'
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    this.showAlert('ntfyStatus', 'Configuration deleted successfully!', 'success');
                    this.loadNtfyConfig();
                    
                    // Reset notification settings for this config
                    this.resetNotificationSettingsForNtfy(configId);
                } else {
                    this.showAlert('ntfyStatus', `Error: ${data.message}`, 'error');
                }
            })
            .catch(error => {
                this.showAlert('ntfyStatus', `Error: ${error.message}`, 'error');
            });
        }
    }

    /**
     * Reset notification settings for a deleted configuration
     * @param {number} configId - Configuration ID
     */
    resetNotificationSettingsForNtfy(configId) {
        // Reset all notification settings that use this config
        const dropdowns = document.querySelectorAll('.options_ntfy_select');
        
        dropdowns.forEach(dropdown => {
            if (dropdown.value === configId.toString()) {
                dropdown.value = '';
                
                // Get event type and update settings
                const eventType = dropdown.getAttribute('data-event-type');
                const checkbox = document.getElementById(`ntfy_${eventType.toLowerCase()}`);
                
                if (checkbox) {
                    checkbox.checked = false;
                    
                    // Save the updated setting
                    this.updateNtfyNotificationSetting(eventType, false, '');
                }
            }
        });
    }

    /**
     * Updates a notification setting for a specific event type
     * @param {string} eventType - The type of event (e.g., "ONLINE", "ONBATT")
     * @param {boolean} enabled - Whether to enable or disable notifications
     * @param {string} configId - The ID of the Ntfy configuration to use
     */
    updateNtfyNotificationSetting(eventType, enabled, configId) {
        console.log(`Starting update ${eventType} notification: enabled=${enabled}, config=${configId}`);
        
        // If enabling but no config is selected, show an error and revert
        if (enabled && (!configId || configId === '')) {
            this.showToastOrAlert(`Please select a Ntfy configuration for ${eventType} notifications first`, 'error');
            
            // Reset checkbox state since we can't update
            const checkbox = document.getElementById(`ntfy_${eventType.toLowerCase()}`);
            if (checkbox) {
                checkbox.checked = false;
                // Also ensure the checkbox is properly hidden when no config is selected
                checkbox.style.display = 'none';
            }
            
            // Also hide the test button
            const testButton = document.querySelector(`.options_ntfy_test[data-event-type="${eventType}"]`);
            if (testButton) {
                testButton.style.display = 'none';
            }
            
            return;
        }
        
        // Verify that the dropdown has the same configId we're trying to use (sync issue fix)
        if (enabled) {
            const dropdown = document.querySelector(`.options_ntfy_select[data-event-type="${eventType}"]`);
            if (dropdown && dropdown.value !== configId) {
                console.log(`Dropdown value (${dropdown.value}) doesn't match configId (${configId}), updating to match`);
                configId = dropdown.value;
                
                // If after fixing this the configId is still empty, show error and revert
                if (!configId || configId === '') {
                    this.showToastOrAlert(`Please select a Ntfy configuration for ${eventType} notifications first`, 'error');
                    
                    // Reset checkbox state since we can't update
                    const checkbox = document.getElementById(`ntfy_${eventType.toLowerCase()}`);
                    if (checkbox) {
                        checkbox.checked = false;
                        checkbox.style.display = 'none';
                    }
                    
                    // Also hide the test button
                    const testButton = document.querySelector(`.options_ntfy_test[data-event-type="${eventType}"]`);
                    if (testButton) {
                        testButton.style.display = 'none';
                    }
                    
                    return;
                }
            }
        }
        
        // Check if the configId exists in the dropdown - this is key to fixing the issue
        if (enabled) {
            const dropdown = document.querySelector(`.options_ntfy_select[data-event-type="${eventType}"]`);
            if (dropdown) {
                const optionExists = Array.from(dropdown.options).some(opt => 
                    opt.value === configId.toString());
                
                if (!optionExists) {
                    this.showToastOrAlert(`Selected configuration is no longer available. Please select another Ntfy configuration.`, 'error');
                    
                    // Reset checkbox state since config is invalid
                    const checkbox = document.getElementById(`ntfy_${eventType.toLowerCase()}`);
                    if (checkbox) {
                        checkbox.checked = false;
                    }
                    return;
                }
            }
        }
        
        console.log(`Updating ${eventType} notification: enabled=${enabled}, config=${configId}`);
        
        // Disable the checkbox during the operation
        const checkbox = document.getElementById(`ntfy_${eventType.toLowerCase()}`);
        if (checkbox) {
            checkbox.disabled = true;
        }
        
        const settingData = {
            event_type: eventType,
            enabled: enabled,
            config_id: configId
        };
        
        fetch('/api/ntfy/setting', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(settingData)
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                // Show success message
                this.showToastOrAlert(`${eventType} notifications ${enabled ? 'enabled' : 'disabled'}`, 'success');
                
                // Important: Reload all settings from the server after making a change
                // This ensures the UI stays in sync with the database state
                this.loadNtfySettings().then(() => {
                    console.log(`Settings reloaded after updating ${eventType} notification`);
                }).catch(error => {
                    console.error(`Failed to reload settings: ${error}`);
                });
            } else {
                // Show error and revert the checkbox state
                this.showToastOrAlert(`Error updating ${eventType} notification: ${data.message}`, 'error');
                
                if (checkbox) {
                    checkbox.checked = !enabled; // Revert to previous state
                    checkbox.disabled = false;
                    
                    // Ensure proper visibility based on dropdown value
                    const dropdown = document.querySelector(`.options_ntfy_select[data-event-type="${eventType}"]`);
                    const testButton = document.querySelector(`.options_ntfy_test[data-event-type="${eventType}"]`);
                    
                    if (dropdown && (!dropdown.value || dropdown.value === '')) {
                        checkbox.style.display = 'none';
                        if (testButton) testButton.style.display = 'none';
                    } else {
                        checkbox.style.display = 'inline-block';
                        if (testButton) testButton.style.display = 'inline-block';
                    }
                }
            }
        })
        .catch(error => {
            // Handle network errors
            this.showToastOrAlert(`Error updating notification: ${error.message}`, 'error');
            
            if (checkbox) {
                checkbox.checked = !enabled; // Revert to previous state
                checkbox.disabled = false;
                
                // Ensure proper visibility based on dropdown value
                const dropdown = document.querySelector(`.options_ntfy_select[data-event-type="${eventType}"]`);
                const testButton = document.querySelector(`.options_ntfy_test[data-event-type="${eventType}"]`);
                
                if (dropdown && (!dropdown.value || dropdown.value === '')) {
                    checkbox.style.display = 'none';
                    if (testButton) testButton.style.display = 'none';
                } else {
                    checkbox.style.display = 'inline-block';
                    if (testButton) testButton.style.display = 'inline-block';
                }
            }
        });
    }

    /**
     * Show toast or fallback to an alert
     * @param {string} message - Message to display
     * @param {string} type - Message type (success, error, warning)
     */
    showToastOrAlert(message, type) {
        if (typeof showToast === 'function') {
            showToast(message, type);
        } else {
            // Fallback to our own alert
            this.showAlert('options_ntfy_status', message, type);
        }
    }

    /**
     * Test a Ntfy configuration
     * @param {number} configId - Configuration ID to test
     */
    testNtfyConfig(configId) {
        console.log(`Starting test for Ntfy config ID: ${configId}`);
        
        // Find the row with this config ID
        const configRow = document.querySelector(`.email_config_row[data-id="${configId}"]`);
        console.log(`Config row found:`, configRow);
        
        if (!configRow) {
            console.error(`Config row for ID ${configId} not found. Trying alternative selector...`);
            // Try alternative selector
            const altConfigRow = document.querySelector(`#ntfy-config-${configId}`);
            if (altConfigRow) {
                console.log(`Found config row using alternative selector:`, altConfigRow);
                // Process with alternative row
                this._processTestRequest(configId, altConfigRow);
                return;
            }
            
            // If still not found, just send the test request without UI updates
            console.log(`Still cannot find config row. Making direct API call...`);
            this._sendDirectTestRequest(configId);
            return;
        }
        
        // Get the test button
        const testBtn = configRow.querySelector('.test-btn');
        console.log(`Test button found:`, testBtn);
        
        if (!testBtn) {
            console.error(`Test button not found in row. Making direct API call...`);
            // If button not found, just make the API call without UI updates
            this._sendDirectTestRequest(configId);
            return;
        }
        
        // Save original button content
        const originalText = testBtn.innerHTML;
        
        // Show loading state
        testBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Testing...';
        testBtn.disabled = true;
        
        // Send the test notification
        fetch(`/api/ntfy/test/${configId}`, {
            method: 'POST'
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                this.showToastOrAlert('Test ntfy sent successfully', 'success');
            } else {
                this.showToastOrAlert(`Error: ${data.message}`, 'error');
            }
        })
        .catch(error => {
            this.showToastOrAlert(`Error: ${error.message}`, 'error');
        })
        .finally(() => {
            // Restore original button content
            testBtn.innerHTML = originalText;
            testBtn.disabled = false;
        });
    }
    
    /**
     * Process the test request for a given config row
     * @private
     */
    _processTestRequest(configId, configRow) {
        // Get all buttons in the row
        const buttons = configRow.querySelectorAll('button');
        console.log(`Found ${buttons.length} buttons in the row`);
        
        // Try to find the test button by text content or icon
        let testBtn = null;
        for (const btn of buttons) {
            if (btn.textContent.trim().includes('Test') || 
                btn.innerHTML.includes('fa-paper-plane') ||
                btn.classList.contains('test-btn')) {
                testBtn = btn;
                break;
            }
        }
        
        if (!testBtn) {
            console.error(`Could not identify test button in row. Making direct API call...`);
            this._sendDirectTestRequest(configId);
            return;
        }
        
        console.log(`Test button identified:`, testBtn);
        
        // Save original button content
        const originalText = testBtn.innerHTML;
        
        // Show loading state
        testBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Testing...';
        testBtn.disabled = true;
        
        // Send the test notification
        fetch(`/api/ntfy/test/${configId}`, {
            method: 'POST'
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                this.showToastOrAlert('Test ntfy sent successfully', 'success');
            } else {
                this.showToastOrAlert(`Error: ${data.message}`, 'error');
            }
        })
        .catch(error => {
            this.showToastOrAlert(`Error: ${error.message}`, 'error');
        })
        .finally(() => {
            // Restore original button content
            testBtn.innerHTML = originalText;
            testBtn.disabled = false;
        });
    }
    
    /**
     * Send a test request directly without UI updates
     * @private
     */
    _sendDirectTestRequest(configId) {
        console.log(`Sending direct test request for config ID: ${configId}`);
        
        // Send the test notification
        fetch(`/api/ntfy/test/${configId}`, {
            method: 'POST'
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                this.showToastOrAlert('Test ntfy sent successfully', 'success');
            } else {
                this.showToastOrAlert(`Error: ${data.message}`, 'error');
            }
        })
        .catch(error => {
            this.showToastOrAlert(`Error: ${error.message}`, 'error');
        });
    }

    /**
     * Set a configuration as the default
     * @param {number} configId - Configuration ID
     */
    setDefaultNtfyConfig(configId) {
        fetch(`/api/ntfy/config/${configId}/default`, {
            method: 'POST'
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                this.showToastOrAlert('Default configuration updated', 'success');
                this.loadNtfyConfig();
            } else {
                this.showToastOrAlert(`Error: ${data.message}`, 'error');
            }
        })
        .catch(error => {
            this.showToastOrAlert(`Error: ${error.message}`, 'error');
        });
    }

    /**
     * Load notification settings from the server
     */
    async loadNtfySettings() {
        try {
            console.log("Loading Ntfy notification settings...");
            
            // Get notification settings from the server
            const response = await fetch('/api/ntfy/settings');
            
            if (!response.ok) {
                console.error(`Failed to load Ntfy settings: ${response.status} ${response.statusText}`);
                return false;
            }
            
            const data = await response.json();
            
            if (!data.success) {
                console.error("Failed to load Ntfy settings: Server reported failure");
                return false;
            }
            
            const settings = data.settings || {};
            console.log("Ntfy settings loaded:", settings);
            
            // Define the event types we handle
            const eventTypes = ['ONLINE', 'ONBATT', 'LOWBATT', 'COMMOK', 'COMMBAD', 'SHUTDOWN', 'REPLBATT', 'NOCOMM', 'NOPARENT'];
            
            // For each event type, update the UI
            for (const eventType of eventTypes) {
                const checkbox = document.getElementById(`ntfy_${eventType.toLowerCase()}`);
                const dropdown = document.querySelector(`.options_ntfy_select[data-event-type="${eventType}"]`);
                const testButton = document.querySelector(`.options_ntfy_test[data-event-type="${eventType}"]`);
                
                if (!checkbox || !dropdown) {
                    console.warn(`Missing UI elements for ${eventType}`);
                    continue;
                }
                
                console.log(`Processing ${eventType} notification settings`);
                
                // Get the setting for this event type
                const setting = settings[eventType];
                
                // If no setting or not enabled, ensure checkbox is unchecked and hidden
                if (!setting || !setting.enabled) {
                    dropdown.value = setting && setting.config_id ? setting.config_id : '';
                    checkbox.checked = false;
                    
                    // Only show the checkbox if a config is selected
                    if (dropdown.value) {
                        checkbox.style.display = 'inline-block';
                        if (testButton) testButton.style.display = 'inline-block';
                    } else {
                        checkbox.style.display = 'none';
                        if (testButton) testButton.style.display = 'none';
                    }
                    continue;
                }
                
                // If the setting exists and is enabled, update dropdown and check the checkbox
                if (setting.config_id) {
                    console.log(`${eventType} is enabled for config ${setting.config_id}`);
                    
                    // Check if the option exists in dropdown
                    const optionExists = Array.from(dropdown.options).some(opt => 
                        opt.value === setting.config_id.toString());
                    
                    if (optionExists) {
                        // Set the dropdown to the correct config
                        dropdown.value = setting.config_id.toString();
                        
                        // Show and check the checkbox
                        checkbox.style.display = 'inline-block';
                        checkbox.checked = true;
                        
                        // Show the test button
                        if (testButton) testButton.style.display = 'inline-block';
                    } else {
                        console.warn(`Config ${setting.config_id} for ${eventType} not found in dropdown`);
                        dropdown.value = '';
                        checkbox.checked = false;
                        checkbox.style.display = 'none';
                        if (testButton) testButton.style.display = 'none';
                    }
                } else {
                    // No config ID but event is enabled - invalid state
                    console.warn(`${eventType} is enabled but has no config ID - invalid state`);
                    dropdown.value = '';
                    checkbox.checked = false;
                    checkbox.style.display = 'none';
                    if (testButton) testButton.style.display = 'none';
                }
            }
            
            // Re-enable all checkboxes (in case they were disabled during updates)
            document.querySelectorAll('.options_ntfy_checkbox').forEach(cb => {
                cb.disabled = false;
            });
            
            return true;
        } catch (error) {
            console.error("Error loading Ntfy settings:", error);
            return false;
        }
    }

    /**
     * Populate Ntfy dropdowns with available configurations
     */
    async populateNtfyDropdowns() {
        try {
            console.log("Populating Ntfy dropdowns with configuration options...");
            
            // Use the configurations stored in this.ntfyConfigs
            if (!this.ntfyConfigs || this.ntfyConfigs.length === 0) {
                console.warn("No Ntfy configurations available to populate dropdowns");
                return false;
            }
            
            const configs = this.ntfyConfigs;
            const dropdowns = document.querySelectorAll('.options_ntfy_select');
            
            if (!dropdowns.length) {
                console.warn("No Ntfy dropdown elements found in the DOM");
                return false;
            }
            
            // Populate each dropdown with the available configs
            dropdowns.forEach(dropdown => {
                const eventType = dropdown.getAttribute('data-event-type');
                
                // Save the current selection before clearing options
                const currentSelection = dropdown.value;
                console.log(`Populating dropdown for ${eventType}, current selection: ${currentSelection}`);
                
                // Clear existing options except the first one (placeholder)
                while (dropdown.options.length > 1) {
                    dropdown.remove(1);
                }
                
                // Add options for each config
                configs.forEach(config => {
                    const option = document.createElement('option');
                    option.value = config.id.toString();
                    
                    const serverDisplay = config.server_type === 'ntfy.sh' ? 'ntfy.sh' : config.server;
                    option.textContent = `${serverDisplay} - ${config.topic}`;
                    
                    if (config.is_default) {
                        option.textContent += ' (Default)';
                    }
                    
                    dropdown.appendChild(option);
                });
                
                // Restore the previous selection if it exists
                if (currentSelection) {
                    const optionExists = Array.from(dropdown.options).some(opt => 
                        opt.value === currentSelection);
                        
                    if (optionExists) {
                        dropdown.value = currentSelection;
                        console.log(`Restored previous selection: ${dropdown.value}`);
                    } else {
                        dropdown.value = '';
                        console.log(`Previous selection no longer exists, reset to default`);
                    }
                }
            });
            
            return true;
        } catch (error) {
            console.error("Error populating Ntfy dropdowns:", error);
            return false;
        }
    }

    /**
     * Show an alert in the Ntfy tab
     * @param {string} message - Alert message
     * @param {string} type - Alert type (success, error, warning)
     */
    showNtfyAlert(message, type = 'success') {
        this.showAlert('options_ntfy_status', message, type);
    }

    /**
     * Show an alert in a specific container
     * @param {string} containerId - Container ID
     * @param {string} message - Alert message
     * @param {string} type - Alert type (success, error, warning)
     */
    showAlert(containerId, message, type) {
        const container = document.getElementById(containerId);
        if (!container) {
            
            // Fallback to toast if container not found
            if (typeof showToast === 'function') {
                showToast(message, type);
            } else {
                
            }
            return;
        }
        
        container.textContent = message;
        container.className = `options_alert ${type}`;
        container.classList.remove('hidden');
        
        // Hide after 5 seconds for success messages
        if (type === 'success') {
            setTimeout(() => {
                container.classList.add('hidden');
            }, 5000);
        }
    }
}

// Initialize Ntfy functionality for the Extranotifs tab
function initializeNtfyModule() {
    console.log('Initializing Ntfy module...');
    
    // Check if already initialized
    if (window.ntfyManager) {
        console.log('Ntfy module already initialized, refreshing settings...');
        // Force refresh if already initialized
        window.ntfyManager.populateNtfyDropdowns().then(() => {
            window.ntfyManager.loadNtfySettings().then(() => {
                console.log('Ntfy settings refreshed successfully');
            }).catch(err => {
                console.error('Failed to refresh Ntfy settings:', err);
            });
        }).catch(err => {
            console.error('Failed to refresh Ntfy dropdowns:', err);
        });
        return window.ntfyManager;
    }
    
    try {
        window.ntfyManager = new NtfyManager();
        console.log('Ntfy module initialized successfully');
        return window.ntfyManager;
    } catch (error) {
        console.error('Failed to initialize Ntfy module:', error);
        // Show error in UI
        const errorContainer = document.getElementById('options_ntfy_status');
        if (errorContainer) {
            errorContainer.textContent = 'Failed to initialize Ntfy module: ' + error.message;
            errorContainer.className = 'options_alert error';
            errorContainer.classList.remove('hidden');
        }
        return null;
    }
}

// Auto-initialize when script is loaded
document.addEventListener('DOMContentLoaded', () => {
    // Don't auto-initialize on load, wait for tab click
    console.log('Ntfy module ready to initialize on tab click');
});

// Make functions available globally
window.initializeNtfyModule = initializeNtfyModule; 