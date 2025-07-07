/**
 * Admin Tab Functionality
 * Handles user authentication management with different levels of access:
 * - Admin users: Can manage all users (create, edit, delete)
 * - Regular users: Can only change their own password and username
 */

class AdminTab {
    constructor() {
        this.currentUser = null;
        this.isAdmin = false;
        this.users = [];
        this.init();
    }

    init() {
        this.loadCurrentUser();
        this.bindEvents();
    }

    /**
     * Load current user information and check admin status
     */
    async loadCurrentUser() {
        try {
            const response = await fetch('/auth/api/status');
            const data = await response.json();
            
            if (data.is_authenticated && data.current_user) {
                this.currentUser = data.current_user;
                this.isAdmin = data.is_admin || false;
                this.updateUserInfo();
                this.setupAdminInterface();
                
                if (this.isAdmin) {
                    this.loadUsers();
                }
            } else {
                this.showNotLoggedIn();
            }
        } catch (error) {
            console.error('Error loading user info:', error);
            this.showNotLoggedIn();
        }
    }

    /**
     * Update user information display
     */
    updateUserInfo() {
        if (!this.currentUser) return;

        document.getElementById('currentUsername').textContent = this.currentUser.username || 'N/A';
        document.getElementById('currentUserId').textContent = this.currentUser.id || 'N/A';
        
        // Display user role
        let role;
        if (this.currentUser.role) {
            switch (this.currentUser.role) {
                case 'administrator':
                    role = 'Administrator';
                    break;
                case 'operator':
                    role = 'Operator';
                    break;
                case 'monitor':
                    role = 'Monitor';
                    break;
                case 'viewer':
                    role = 'Viewer';
                    break;
                case 'user':
                    role = 'User';
                    break;
                default:
                    role = 'User';
            }
        } else {
            // Fallback for old is_admin system
            role = this.currentUser.is_admin ? 'Administrator' : 'User';
        }
        document.getElementById('currentUserRole').textContent = role;
        
        const lastLogin = this.currentUser.last_login ? 
            new Date(this.currentUser.last_login).toLocaleString() : 'Never';
        document.getElementById('currentUserLastLogin').textContent = lastLogin;
    }

    /**
     * Setup admin interface based on user privileges
     */
    setupAdminInterface() {
        const adminUserManagement = document.getElementById('adminUserManagement');
        const regularUserSection = document.getElementById('regularUserSection');
        const personalAccountCard = document.querySelector('#regularUserSection .options_card:nth-child(2)'); // Personal Account card

        if (this.isAdmin) {
            // Show admin sections
            if (adminUserManagement) {
                adminUserManagement.style.display = 'block';
            }
            if (regularUserSection) {
                regularUserSection.style.display = 'block';
            }
            
            // Hide Personal Account section for admins (they can manage from User Management table)
            if (personalAccountCard) {
                personalAccountCard.style.display = 'none';
            }
            
            // Update page title to indicate admin access
            const adminHeader = document.querySelector('#Admin_tab .card_header h2');
            if (adminHeader) {
                adminHeader.innerHTML = '<i class="fas fa-user-shield"></i> Admin Management';
            }
        } else {
            // Hide admin sections for regular users
            if (adminUserManagement) {
                adminUserManagement.style.display = 'none';
            }
            if (regularUserSection) {
                regularUserSection.style.display = 'block';
            }
            
            // Show Personal Account section for regular users
            if (personalAccountCard) {
                personalAccountCard.style.display = 'block';
            }
            
            // Update page title for regular users
            const adminHeader = document.querySelector('#Admin_tab .card_header h2');
            if (adminHeader) {
                adminHeader.innerHTML = '<i class="fas fa-user"></i> User Profile';
            }
        }
    }

    /**
     * Load all users (admin only)
     */
    async loadUsers() {
        if (!this.isAdmin) return;

        try {
            const response = await fetch('/auth/api/admin/users');
            const data = await response.json();
            
            if (data.success) {
                this.users = data.users;
                this.renderUsersTable();
            } else {
                notify(data.error || 'Failed to load users', 'error');
            }
        } catch (error) {
            console.error('Error loading users:', error);
            notify('Error loading users', 'error');
        }
    }

    /**
     * Render users table (admin only)
     */
    renderUsersTable() {
        const container = document.getElementById('usersTableContainer');
        if (!container || !this.isAdmin) return;

        let html = `
            <div class="users-table-wrapper">
                <div class="users-table-header">
                    <h3>System Users</h3>
                    <button type="button" id="addUserBtn" class="options_btn">
                        <i class="fas fa-plus"></i> Add User
                    </button>
                </div>
                <div class="users-table">
                    <table>
                        <thead>
                            <tr>
                                <th>ID</th>
                                <th>Username</th>
                                <th>Role</th>
                                <th>Last Login</th>
                                <th>Created</th>
                                <th>Actions</th>
                            </tr>
                        </thead>
                        <tbody>
        `;

        this.users.forEach(user => {
            const lastLogin = user.last_login ? 
                new Date(user.last_login).toLocaleString() : 'Never';
            const created = user.created_at ? 
                new Date(user.created_at).toLocaleString() : 'Unknown';
            
            // Determine role display and class
            let role, roleClass;
            if (user.role) {
                switch (user.role) {
                    case 'administrator':
                        role = 'Administrator';
                        roleClass = 'admin-role';
                        break;
                    case 'operator':
                        role = 'Operator';
                        roleClass = 'operator-role';
                        break;
                    case 'monitor':
                        role = 'Monitor';
                        roleClass = 'monitor-role';
                        break;
                    case 'viewer':
                        role = 'Viewer';
                        roleClass = 'viewer-role';
                        break;
                    case 'user':
                        role = 'User';
                        roleClass = 'user-role';
                        break;
                    default:
                        role = 'User';
                        roleClass = 'user-role';
                }
            } else {
                // Fallback for old is_admin system
                role = user.is_admin ? 'Administrator' : 'User';
                roleClass = user.is_admin ? 'admin-role' : 'user-role';
            }

            html += `
                <tr data-user-id="${user.id}">
                    <td>${user.id}</td>
                    <td>
                        ${user.id === 1 ? `
                            <span class="non-clickable-username">${user.username}</span>
                        ` : `
                            <a href="#" class="clickable-username" 
                               onclick="adminTab.showUserPermissionsModal(${user.id}, '${user.username}')">
                                ${user.username}
                            </a>
                        `}
                    </td>
                    <td><span class="role-badge ${roleClass}">${role}</span></td>
                    <td>${lastLogin}</td>
                    <td>${created}</td>
                    <td class="actions">
                        <button type="button" class="options_btn options_btn_small" 
                                onclick="adminTab.showChangePasswordModal(${user.id}, '${user.username}')">
                            <i class="fas fa-key"></i> Change Password
                        </button>
                        ${user.id !== 1 ? `
                            <button type="button" class="options_btn options_btn_small" 
                                    onclick="adminTab.showChangeRoleModal(${user.id}, '${user.username}', '${user.role}')">
                                <i class="fas fa-user-tag"></i> Change Role
                            </button>
                        ` : ''}
                        ${user.id !== 1 && user.id !== this.currentUser.id ? `
                            <button type="button" class="options_btn options_btn_small options_btn_danger" 
                                    onclick="adminTab.deleteUser(${user.id}, '${user.username}')">
                                <i class="fas fa-trash"></i> Delete
                            </button>
                        ` : ''}
                    </td>
                </tr>
            `;
        });

        html += `
                        </tbody>
                    </table>
                </div>
            </div>
        `;

        container.innerHTML = html;

        // Bind add user button
        const addUserBtn = document.getElementById('addUserBtn');
        if (addUserBtn) {
            addUserBtn.addEventListener('click', () => this.showAddUserModal());
        }
    }

    /**
     * Show add user modal (admin only)
     */
    showAddUserModal() {
        if (!this.isAdmin) return;

        const modal = this.createModal('Add New User', `
            <form id="addUserForm">
                <div class="modal-form-group">
                    <label for="newUserUsername">Username</label>
                    <input type="text" id="newUserUsername" name="username" required 
                           placeholder="Enter username (min 3 characters)">
                </div>
                <div class="modal-form-group">
                    <label for="newUserPassword">Password</label>
                    <input type="password" id="newUserPassword" name="password" required 
                           placeholder="Enter password (min 6 characters)">
                </div>
                <div class="modal-form-group">
                    <label for="newUserRole">User Role</label>
                    <select id="newUserRole" name="role" required>
                        <option value="user">User</option>
                        <option value="administrator">Administrator</option>
                    </select>
                </div>
                <div class="modal-actions">
                    <button type="button" class="options_btn options_btn_secondary" onclick="adminTab.closeModal()">
                        Cancel
                    </button>
                    <button type="submit" class="options_btn">
                        <i class="fas fa-plus"></i> Create User
                    </button>
                </div>
            </form>
        `);

        document.body.appendChild(modal);

        // Bind form submission
        const form = document.getElementById('addUserForm');
        if (form) {
            form.addEventListener('submit', (e) => this.handleCreateUser(e));
        }
    }

    /**
     * Handle create user form submission (admin only)
     */
    async handleCreateUser(e) {
        e.preventDefault();
        
        const formData = new FormData(e.target);
        const username = formData.get('username').trim();
        const password = formData.get('password');
        const role = formData.get('role');

        if (!username || !password || !role) {
            notify('All fields are required', 'error');
            return;
        }

        if (username.length < 3) {
            notify('Username must be at least 3 characters long', 'error');
            return;
        }

        if (password.length < 6) {
            notify('Password must be at least 6 characters long', 'error');
            return;
        }

        try {
            const response = await fetch('/auth/api/admin/users', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    username: username,
                    password: password,
                    role: role
                })
            });

            const data = await response.json();

            if (data.success) {
                notify('User created successfully', 'success');
                this.closeModal();
                this.loadUsers(); // Refresh users list
            } else {
                notify(data.error || 'Failed to create user', 'error');
            }
        } catch (error) {
            console.error('Error creating user:', error);
            notify('Error creating user', 'error');
        }
    }

    /**
     * Show change password modal for a user (admin only)
     */
    showChangePasswordModal(userId, username) {
        if (!this.isAdmin) return;

        const modal = this.createModal(`Change Password for ${username}`, `
            <form id="changeUserPasswordForm" data-user-id="${userId}">
                <div class="modal-form-group">
                    <label for="userNewPassword">New Password</label>
                    <input type="password" id="userNewPassword" name="new_password" required 
                           placeholder="Enter new password (min 6 characters)">
                </div>
                <div class="modal-actions">
                    <button type="button" class="options_btn options_btn_secondary" onclick="adminTab.closeModal()">
                        Cancel
                    </button>
                    <button type="submit" class="options_btn">
                        <i class="fas fa-key"></i> Update Password
                    </button>
                </div>
            </form>
        `);

        document.body.appendChild(modal);

        // Bind form submission
        const form = document.getElementById('changeUserPasswordForm');
        if (form) {
            form.addEventListener('submit', (e) => this.handleChangeUserPassword(e));
        }
    }

    /**
     * Handle change user password (admin only)
     */
    async handleChangeUserPassword(e) {
        e.preventDefault();
        
        const form = e.target;
        const userId = form.dataset.userId;
        const formData = new FormData(form);
        const newPassword = formData.get('new_password');

        if (!newPassword) {
            notify('Password is required', 'error');
            return;
        }

        if (newPassword.length < 6) {
            notify('Password must be at least 6 characters long', 'error');
            return;
        }

        try {
            const response = await fetch(`/auth/api/admin/users/${userId}/password`, {
                method: 'PUT',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    new_password: newPassword
                })
            });

            const data = await response.json();

            if (data.success) {
                notify('Password updated successfully', 'success');
                this.closeModal();
            } else {
                notify(data.error || 'Failed to update password', 'error');
            }
        } catch (error) {
            console.error('Error updating password:', error);
            notify('Error updating password', 'error');
        }
    }

    /**
     * Show change role modal for a user (admin only)
     */
    showChangeRoleModal(userId, username, currentRole) {
        if (!this.isAdmin) return;

        const modal = this.createModal(`Change Role for ${username}`, `
            <form id="changeUserRoleForm" data-user-id="${userId}">
                <div class="modal-form-group">
                    <label for="userNewRole">User Role</label>
                    <select id="userNewRole" name="role" required>
                        <option value="user" ${currentRole === 'user' ? 'selected' : ''}>User</option>
                        <option value="administrator" ${currentRole === 'administrator' ? 'selected' : ''}>Administrator</option>
                    </select>
                </div>
                <div class="modal-actions">
                    <button type="button" class="options_btn options_btn_secondary" onclick="adminTab.closeModal()">
                        Cancel
                    </button>
                    <button type="submit" class="options_btn">
                        <i class="fas fa-user-tag"></i> Update Role
                    </button>
                </div>
            </form>
        `);

        document.body.appendChild(modal);

        // Bind form submission
        const form = document.getElementById('changeUserRoleForm');
        if (form) {
            form.addEventListener('submit', (e) => this.handleChangeUserRole(e));
        }
    }

    /**
     * Handle change user role (admin only)
     */
    async handleChangeUserRole(e) {
        e.preventDefault();
        
        const form = e.target;
        const userId = form.dataset.userId;
        const formData = new FormData(form);
        const newRole = formData.get('role');

        if (!newRole) {
            notify('Role is required', 'error');
            return;
        }

        try {
            const response = await fetch(`/auth/api/admin/users/${userId}/role`, {
                method: 'PUT',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    role: newRole
                })
            });

            const data = await response.json();

            if (data.success) {
                notify('Role updated successfully', 'success');
                this.closeModal();
                this.loadUsers(); // Refresh users list
            } else {
                notify(data.error || 'Failed to update role', 'error');
            }
        } catch (error) {
            console.error('Error updating role:', error);
            notify('Error updating role', 'error');
        }
    }

    /**
     * Delete user (admin only)
     */
    async deleteUser(userId, username) {
        if (!this.isAdmin) return;

        if (userId === 1) {
            notify('Cannot delete the main admin account', 'error');
            return;
        }

        if (userId === this.currentUser.id) {
            notify('Cannot delete your own account', 'error');
            return;
        }

        if (!confirm(`Are you sure you want to delete user "${username}"?`)) {
            return;
        }

        try {
            const response = await fetch(`/auth/api/admin/users/${userId}`, {
                method: 'DELETE'
            });

            const data = await response.json();

            if (data.success) {
                notify('User deleted successfully', 'success');
                this.loadUsers(); // Refresh users list
            } else {
                notify(data.error || 'Failed to delete user', 'error');
            }
        } catch (error) {
            console.error('Error deleting user:', error);
            notify('Error deleting user', 'error');
        }
    }

    /**
     * Create modal dialog
     */
    createModal(title, content) {
        const modal = document.createElement('div');
        modal.className = 'modal admin-modal';
        modal.innerHTML = `
            <div class="modal-content">
                <div class="modal-header">
                    <h5 class="modal-title">${title}</h5>
                    <button type="button" class="modal-close" onclick="adminTab.closeModal()">
                        <i class="fas fa-times"></i>
                    </button>
                </div>
                <div class="modal-body">
                    ${content}
                </div>
            </div>
        `;
        return modal;
    }

    /**
     * Close modal dialog
     */
    closeModal() {
        // Close dynamically created modals
        const modal = document.querySelector('.admin-modal');
        if (modal) {
            modal.remove();
        }
        
        // Close permissions modal
        const permissionsModal = document.getElementById('userPermissionsModal');
        if (permissionsModal) {
            permissionsModal.style.display = 'none';
        }

        // Close options tabs modal
        const optionsTabsModal = document.getElementById('optionsTabsModal');
        if (optionsTabsModal) {
            optionsTabsModal.style.display = 'none';
        }

        // Reset current user ID only if both modals are closed
        if ((!permissionsModal || permissionsModal.style.display === 'none') &&
            (!optionsTabsModal || optionsTabsModal.style.display === 'none')) {
            this.currentPermissionUserId = null;
        }
    }

    /**
     * Show not logged in message
     */
    showNotLoggedIn() {
        const adminStatus = document.getElementById('options_admin_status');
        if (adminStatus) {
            adminStatus.className = 'options_alert';
            adminStatus.innerHTML = `
                <i class="fas fa-exclamation-triangle"></i>
                <strong>Not logged in</strong> - Please log in to access admin features.
            `;
            adminStatus.classList.remove('hidden');
        }
        
        // Update user info displays
        const currentUsername = document.getElementById('currentUsername');
        const currentUserId = document.getElementById('currentUserId');
        const currentUserRole = document.getElementById('currentUserRole');
        const currentUserLastLogin = document.getElementById('currentUserLastLogin');
        
        if (currentUsername) currentUsername.textContent = 'Not logged in';
        if (currentUserId) currentUserId.textContent = 'N/A';
        if (currentUserRole) currentUserRole.textContent = 'N/A';
        if (currentUserLastLogin) currentUserLastLogin.textContent = 'N/A';
    }

    /**
     * Bind event listeners
     */
    bindEvents() {
        // Logout button
        const logoutBtn = document.getElementById('logoutBtn');
        if (logoutBtn) {
            logoutBtn.addEventListener('click', () => this.handleLogout());
        }
    }

    /**
     * Show user permissions modal (admin only)
     */
    async showUserPermissionsModal(userId, username) {
        if (!this.isAdmin) return;

        this.currentPermissionUserId = userId;
        
        // Show the modal
        const modal = document.getElementById('userPermissionsModal');
        if (modal) {
            document.getElementById('permissionUserName').textContent = username;
            modal.style.display = 'block';
            
            // Load current permissions for this user
            await this.loadUserPermissions(userId);
            
            // Check if this user is an admin to determine settings checkbox behavior
            await this.checkUserRole(userId);
        }
    }
    
    /**
     * Check user role and adjust permissions accordingly
     */
    async checkUserRole(userId) {
        try {
            const response = await fetch(`/auth/api/admin/users`);
            const data = await response.json();
            
            if (data.success) {
                const user = data.users.find(u => u.id === userId);
                const optionsCheckbox = document.getElementById('perm_options');
                const configureBtn = document.querySelector('.configure-settings-btn');
                
                if (user && optionsCheckbox && configureBtn) {
                    if (user.role === 'administrator') {
                        // Admin users always have access to options
                        optionsCheckbox.disabled = false;
                        optionsCheckbox.checked = true;
                        configureBtn.style.display = 'none'; // Hide configure button for admins
                    } else {
                        // Non-admin users need configuration
                        configureBtn.style.display = 'inline-block';
                        // Options state will be managed by updateOptionsCheckboxState
                    }
                }
            }
        } catch (error) {
            console.error('Error checking user role:', error);
        }
    }

    /**
     * Load user permissions (admin only)
     */
    async loadUserPermissions(userId) {
        if (!this.isAdmin) return;

        try {
            const response = await fetch(`/auth/api/admin/users/${userId}/permissions`);
            const data = await response.json();
            
            // Default permissions if none exist
            const defaultPermissions = {
                home: true,
                energy: true,
                power: true,
                battery: true,
                voltage: true,
                info: true,
                command: false,
                settings: false,
                events: true,
                options: false
            };
            
            const permissions = data.success ? data.permissions : defaultPermissions;
            
            // Update checkboxes
            document.querySelectorAll('.permission-checkbox').forEach(checkbox => {
                const page = checkbox.dataset.page;
                if (page === 'options') {
                    // Special handling for options checkbox - will be updated later based on options tabs
                    checkbox.checked = false;
                    checkbox.disabled = true;
                } else {
                    checkbox.checked = permissions[page] !== false;
                }
            });
            
            // Update options checkbox state based on options tabs configuration
            await this.updateOptionsCheckboxState();
            
        } catch (error) {
            console.error('Error loading user permissions:', error);
            notify('Error loading user permissions', 'error');
            
            // Set default permissions on error
            document.querySelectorAll('.permission-checkbox').forEach(checkbox => {
                const page = checkbox.dataset.page;
                if (page === 'options') {
                    checkbox.checked = false;
                    checkbox.disabled = true;
                } else {
                    checkbox.checked = !['command', 'settings'].includes(page);
                }
            });
        }
    }

    /**
     * Save user permissions (admin only)
     */
    async saveUserPermissions() {
        if (!this.isAdmin || !this.currentPermissionUserId) return;

        const permissions = {};
        document.querySelectorAll('.permission-checkbox').forEach(checkbox => {
            permissions[checkbox.dataset.page] = checkbox.checked;
        });

        try {
            const response = await fetch(`/auth/api/admin/users/${this.currentPermissionUserId}/permissions`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ permissions: permissions })
            });

            const data = await response.json();

            if (data.success) {
                notify('User permissions updated successfully', 'success');
                this.closeModal();
                
                // Reload users table to reflect changes
                await this.loadUsers();
            } else {
                notify(data.error || 'Failed to update user permissions', 'error');
            }
        } catch (error) {
            console.error('Error saving user permissions:', error);
            notify('Error saving user permissions', 'error');
        }
    }

    /**
     * Show options tabs configuration modal
     */
    async showOptionsTabsModal() {
        if (!this.isAdmin || !this.currentPermissionUserId) {
            notify('Please select a user first', 'error');
            return;
        }

        // Show the modal
        const modal = document.getElementById('optionsTabsModal');
        if (modal) {
            // Get current user name
            const userName = document.getElementById('permissionUserName').textContent;
            document.getElementById('optionsTabsUserName').textContent = userName;
            
            modal.style.display = 'block';
            
            // Load current options tabs configuration for this user
            await this.loadUserOptionsTabsConfiguration(this.currentPermissionUserId);
        }
    }

    /**
     * Load user options tabs configuration
     */
    async loadUserOptionsTabsConfiguration(userId) {
        if (!this.isAdmin) return;

        try {
            const response = await fetch(`/auth/api/admin/users/${userId}/options-tabs`);
            const data = await response.json();
            
            // Default tabs configuration (all disabled for non-admin)
            const defaultTabs = {
                email: false,
                extranotifs: false,
                webhook: false,
                powerflow: false,
                database: false,
                log: false,
                advanced: false,
                admin: false
            };
            
            const optionsTabs = data.success ? data.options_tabs : defaultTabs;
            
            // Update checkboxes
            document.querySelectorAll('.options-tab-checkbox').forEach(checkbox => {
                const tab = checkbox.dataset.tab;
                checkbox.checked = optionsTabs[tab] === true;
            });
            
        } catch (error) {
            console.error('Error loading user options tabs:', error);
            notify('Error loading options tabs configuration', 'error');
            
            // Set default tabs on error (all disabled)
            document.querySelectorAll('.options-tab-checkbox').forEach(checkbox => {
                checkbox.checked = false;
            });
        }
    }

    /**
     * Save options tabs configuration
     */
    async saveOptionsTabsConfiguration() {
        if (!this.isAdmin || !this.currentPermissionUserId) return;

        const optionsTabs = {};
        document.querySelectorAll('.options-tab-checkbox').forEach(checkbox => {
            optionsTabs[checkbox.dataset.tab] = checkbox.checked;
        });

        try {
            const response = await fetch(`/auth/api/admin/users/${this.currentPermissionUserId}/options-tabs`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ options_tabs: optionsTabs })
            });

            const data = await response.json();

            if (data.success) {
                notify('Options tabs configuration saved successfully', 'success');
                this.closeOptionsTabsModal();
                
                // Update the options checkbox state based on tabs configuration
                await this.updateOptionsCheckboxState();
                
            } else {
                notify(data.error || 'Failed to save options tabs configuration', 'error');
            }
        } catch (error) {
            console.error('Error saving options tabs configuration:', error);
            notify('Error saving options tabs configuration', 'error');
        }
    }

    /**
     * Close options tabs modal
     */
    closeOptionsTabsModal() {
        const modal = document.getElementById('optionsTabsModal');
        if (modal) {
            modal.style.display = 'none';
        }
    }

    /**
     * Update options checkbox state based on options tabs configuration
     */
    async updateOptionsCheckboxState() {
        if (!this.isAdmin || !this.currentPermissionUserId) return;

        try {
            const response = await fetch(`/auth/api/admin/users/${this.currentPermissionUserId}/options-tabs`);
            const data = await response.json();
            
            if (data.success) {
                const optionsTabs = data.options_tabs;
                const hasAnyTabEnabled = Object.values(optionsTabs).some(enabled => enabled === true);
                
                // Get the options checkbox
                const optionsCheckbox = document.getElementById('perm_options');
                const configureBtn = document.querySelector('.configure-settings-btn');
                
                if (optionsCheckbox && configureBtn) {
                    // Enable/disable options checkbox based on tabs configuration
                    optionsCheckbox.disabled = !hasAnyTabEnabled;
                    
                    // Update button state
                    if (hasAnyTabEnabled) {
                        configureBtn.title = 'Modify Options Tabs Access';
                        optionsCheckbox.checked = true; // Auto-enable options if tabs are configured
                    } else {
                        configureBtn.title = 'Configure Options Tabs Access';
                        optionsCheckbox.checked = false;
                    }
                }
            }
        } catch (error) {
            console.error('Error updating options checkbox state:', error);
        }
    }

    /**
     * Show change personal password modal
     */
    showChangePersonalPasswordModal() {
        const modal = this.createModal('Change Your Password', `
            <form id="changePersonalPasswordForm">
                <div class="modal-form-group">
                    <label for="currentPersonalPassword">Current Password</label>
                    <input type="password" id="currentPersonalPassword" name="currentPassword" required 
                           placeholder="Enter your current password">
                </div>
                <div class="modal-form-group">
                    <label for="newPersonalPassword">New Password</label>
                    <input type="password" id="newPersonalPassword" name="newPassword" required 
                           placeholder="Enter new password (min 6 characters)">
                </div>
                <div class="modal-form-group">
                    <label for="confirmPersonalPassword">Confirm New Password</label>
                    <input type="password" id="confirmPersonalPassword" name="confirmPassword" required 
                           placeholder="Confirm new password">
                </div>
                <div class="modal-actions">
                    <button type="button" class="options_btn options_btn_secondary" onclick="adminTab.closeModal()">
                        Cancel
                    </button>
                    <button type="submit" class="options_btn">
                        <i class="fas fa-save"></i> Update Password
                    </button>
                </div>
            </form>
        `);

        document.body.appendChild(modal);

        // Bind form submission
        const form = document.getElementById('changePersonalPasswordForm');
        if (form) {
            form.addEventListener('submit', (e) => this.handlePersonalPasswordChange(e));
        }
    }

    /**
     * Show change personal username modal
     */
    showChangePersonalUsernameModal() {
        const modal = this.createModal('Change Your Username', `
            <form id="changePersonalUsernameForm">
                <div class="modal-form-group">
                    <label for="newPersonalUsername">New Username</label>
                    <input type="text" id="newPersonalUsername" name="newUsername" required 
                           placeholder="Enter new username (min 3 characters)">
                </div>
                <div class="modal-form-group">
                    <label for="personalUsernamePassword">Current Password</label>
                    <input type="password" id="personalUsernamePassword" name="password" required 
                           placeholder="Enter your current password">
                </div>
                <div class="modal-actions">
                    <button type="button" class="options_btn options_btn_secondary" onclick="adminTab.closeModal()">
                        Cancel
                    </button>
                    <button type="submit" class="options_btn">
                        <i class="fas fa-save"></i> Update Username
                    </button>
                </div>
            </form>
        `);

        document.body.appendChild(modal);

        // Bind form submission
        const form = document.getElementById('changePersonalUsernameForm');
        if (form) {
            form.addEventListener('submit', (e) => this.handlePersonalUsernameChange(e));
        }
    }

    /**
     * Handle personal password change
     */
    async handlePersonalPasswordChange(e) {
        e.preventDefault();
        
        const form = e.target;
        const formData = new FormData(form);
        
        const currentPassword = formData.get('currentPassword');
        const newPassword = formData.get('newPassword');
        const confirmPassword = formData.get('confirmPassword');

        // Validation
        if (!currentPassword || !newPassword || !confirmPassword) {
            notify('All fields are required', 'error');
            return;
        }

        if (newPassword.length < 6) {
            notify('New password must be at least 6 characters long', 'error');
            return;
        }

        if (newPassword !== confirmPassword) {
            notify('New passwords do not match', 'error');
            return;
        }

        try {
            const response = await fetch('/auth/api/change-password', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    current_password: currentPassword,
                    new_password: newPassword
                })
            });

            const data = await response.json();

            if (data.success) {
                notify('Password updated successfully', 'success');
                this.closeModal();
            } else {
                notify(data.error || 'Failed to update password', 'error');
            }
        } catch (error) {
            console.error('Error changing password:', error);
            notify('An error occurred while updating password', 'error');
        }
    }

    /**
     * Handle personal username change
     */
    async handlePersonalUsernameChange(e) {
        e.preventDefault();
        
        const form = e.target;
        const formData = new FormData(form);
        
        const newUsername = formData.get('newUsername').trim();
        const password = formData.get('password');

        // Validation
        if (!newUsername || !password) {
            notify('All fields are required', 'error');
            return;
        }

        if (newUsername.length < 3) {
            notify('Username must be at least 3 characters long', 'error');
            return;
        }

        try {
            const response = await fetch('/auth/api/change-username', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    new_username: newUsername,
                    password: password
                })
            });

            const data = await response.json();

            if (data.success) {
                notify('Username updated successfully', 'success');
                this.closeModal();
                // Update current user info
                if (this.currentUser) {
                    this.currentUser.username = newUsername;
                    this.updateUserInfo();
                }
            } else {
                notify(data.error || 'Failed to update username', 'error');
            }
        } catch (error) {
            console.error('Error changing username:', error);
            notify('An error occurred while updating username', 'error');
        }
    }

    /**
     * Handle logout
     */
    async handleLogout() {
        if (!confirm('Are you sure you want to logout?')) {
            return;
        }

        try {
            const response = await fetch('/auth/api/logout', {
                method: 'POST'
            });

            const data = await response.json();

            if (data.success) {
                notify('Logged out successfully', 'success');
                // Redirect to login page after a short delay
                setTimeout(() => {
                    window.location.href = '/auth/login';
                }, 1000);
            } else {
                notify('Error during logout', 'error');
            }
        } catch (error) {
            console.error('Error during logout:', error);
            notify('Error during logout', 'error');
        }
    }
}

// Initialize admin tab when DOM is loaded
let adminTab;
document.addEventListener('DOMContentLoaded', function() {
    if (document.getElementById('Admin_tab')) {
        adminTab = new AdminTab();
    }
});

// Export for use in other modules
if (typeof module !== 'undefined' && module.exports) {
    module.exports = AdminTab;
} 