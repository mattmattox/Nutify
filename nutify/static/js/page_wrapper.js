// BasePage class for application pages
class BasePage {
    constructor() {
        // Get timezone from the centralized timezone.js
        this._timezone = cache_timezone_js();
        
        // Initialize common properties
        this.isRealTimeMode = true;
        this.initialLoadTime = new Date();
        this.REALTIME_DURATION = 5 * 60 * 1000; // 5 minutes in milliseconds
        this.initializeWebSocket();
    }

    startRealTimeMode() {
        this.isRealTimeMode = true;
        this.initialLoadTime = new Date();
        
        // Set the UI immediately in realtime mode
        document.querySelectorAll('.range-options a').forEach(option => {
            option.classList.remove('active');
            if (option.dataset.range === 'realtime') {
                option.classList.add('active');
            }
        });
        this.updateDisplayedRange('Real Time');
        
        // Start the realtime updates
        this.startRealTimeUpdates();
        
        // Start the timer for the mode check
        this.modeCheckInterval = setInterval(() => {
            this.checkInitialMode();
        }, 30000);
    }

    async checkInitialMode() {
        const now = new Date();
        const timeElapsed = now - this.initialLoadTime;

        if (this.isRealTimeMode && timeElapsed >= this.REALTIME_DURATION) {
            webLogger.page('Switching to Today mode after 5 minutes');
            
            // First stop the realtime
            this.stopRealTimeUpdates();
            this.isRealTimeMode = false;
            
            // Then update the UI
            const currentTime = format_time_js(now);

            // Update the input fields with the correct values
            const fromTimeInput = document.getElementById('fromTime');
            const toTimeInput = document.getElementById('toTime');
            if (fromTimeInput) fromTimeInput.value = '00:00';
            if (toTimeInput) toTimeInput.value = currentTime;

            document.querySelectorAll('.range-options a').forEach(option => {
                option.classList.remove('active');
                if (option.dataset.range === 'today') {
                    option.classList.add('active');
                }
            });

            this.updateDisplayedRange(`Today (00:00 - ${currentTime})`);
            
            // Load the data with the correct parameters
            await this.loadData('day', '00:00', currentTime);
            return false;
        }
        return this.isRealTimeMode;
    }

    stopRealTimeMode() {
        if (this.modeCheckInterval) {
            clearInterval(this.modeCheckInterval);
        }
        this.isRealTimeMode = false;
    }

    initializeWebSocket() {
        try {
            this.socket = io();
            this.socket.on('connect', () => {
                webLogger.data('Connected to WebSocket');
            });
        } catch (error) {
            webLogger.error('WebSocket initialization error:', error);
        }
    }
}

class StaticPage {
    constructor() {
        // Get timezone from the centralized timezone.js
        this._timezone = cache_timezone_js();
    }
}

// Global Permissions Manager
class PermissionsManager {
    constructor() {
        this.userPermissions = {};
        this.isAuthenticated = false;
        this.isAdmin = false;
    }

    async loadUserPermissions() {
        try {
            const response = await fetch('/auth/api/status');
            const data = await response.json();
            
            this.isAuthenticated = data.is_authenticated;
            this.isAdmin = data.is_admin;
            this.userPermissions = data.permissions || {};
            
            console.log('🔐 User permissions loaded:', {
                authenticated: this.isAuthenticated,
                admin: this.isAdmin,
                permissions: this.userPermissions
            });
            
            return data;
        } catch (error) {
            console.error('Error loading user permissions:', error);
            return null;
        }
    }

    hasPermission(page) {
        // Admin can access everything
        if (this.isAdmin) {
            console.log(`🔐 Admin access granted for ${page}`);
            return true;
        }
        
        // Check specific permission
        const hasAccess = this.userPermissions[page] === true;
        console.log(`🔐 Permission check for ${page}: ${hasAccess}`, this.userPermissions);
        return hasAccess;
    }

    applyPermissionsToNavigation() {
        const navItems = document.querySelectorAll('.nav-item[data-page]');
        
        console.log('🔍 Found navigation items:', navItems.length);
        
        if (navItems.length === 0) {
            console.warn('⚠️ No navigation items found. Retrying in 500ms...');
            setTimeout(() => this.applyPermissionsToNavigation(), 500);
            return;
        }
        
        navItems.forEach(item => {
            const page = item.dataset.page;
            const hasAccess = this.hasPermission(page);
            
            console.log(`📄 Page: ${page}, Access: ${hasAccess}`);
            
            if (!hasAccess) {
                item.style.display = 'none';
                item.classList.add('permission-denied');
            } else {
                item.style.display = 'block';
                item.classList.remove('permission-denied');
            }
        });
        
        console.log('✅ Navigation permissions applied');
    }

    checkCurrentPageAccess() {
        const currentPath = window.location.pathname;
        let currentPage = null;
        
        // Map current path to page permission
        if (currentPath === '/' || currentPath === '/index') {
            currentPage = 'home';
        } else if (currentPath.startsWith('/energy')) {
            currentPage = 'energy';
        } else if (currentPath.startsWith('/power')) {
            currentPage = 'power';
        } else if (currentPath.startsWith('/battery')) {
            currentPage = 'battery';
        } else if (currentPath.startsWith('/voltage')) {
            currentPage = 'voltage';
        } else if (currentPath.startsWith('/ups_info')) {
            currentPage = 'info';
        } else if (currentPath.startsWith('/upscmd')) {
            currentPage = 'command';
        } else if (currentPath.startsWith('/upsrw')) {
            currentPage = 'settings';
        } else if (currentPath.startsWith('/events')) {
            currentPage = 'events';
        }
        
        // Check if user has access to current page
        if (currentPage && !this.hasPermission(currentPage)) {
            this.showAccessDenied();
            return false;
        }
        
        return true;
    }

    showAccessDenied() {
        // Create and show access denied message
        const accessDeniedHTML = `
            <div style="display: flex; flex-direction: column; align-items: center; justify-content: center; 
                        height: 60vh; text-align: center; padding: 2rem;">
                <i class="fas fa-lock" style="font-size: 4rem; color: #dc3545; margin-bottom: 1rem;"></i>
                <h2 style="color: #dc3545; margin-bottom: 1rem;">Access Denied</h2>
                <p style="color: #666; margin-bottom: 2rem;">You don't have permission to access this page.</p>
                <a href="/" class="options_btn" style="text-decoration: none;">
                    <i class="fas fa-home"></i> Back to Home
                </a>
            </div>
        `;
        
        // Find main content area and replace it
        const mainContent = document.querySelector('.main-content') || document.querySelector('main') || document.querySelector('.content');
        if (mainContent) {
            mainContent.innerHTML = accessDeniedHTML;
        }
    }
}

// Global permissions manager instance
const permissionsManager = new PermissionsManager();

// Add security CSS to ensure permission-denied elements are hidden
const securityStyle = document.createElement('style');
securityStyle.textContent = `
    .nav-item.permission-denied {
        display: none !important;
        visibility: hidden !important;
    }
`;
document.head.appendChild(securityStyle);

// Global event listener: Dark Mode toggle and Permissions
document.addEventListener('DOMContentLoaded', async function() {
    // Load user permissions first
    const authData = await permissionsManager.loadUserPermissions();
    
    if (authData && authData.is_authenticated) {
        // Apply permissions to navigation
        permissionsManager.applyPermissionsToNavigation();
        
        // Check current page access
        permissionsManager.checkCurrentPageAccess();
        
        // Also apply permissions after window load to catch any delayed elements
        window.addEventListener('load', () => {
            setTimeout(() => {
                permissionsManager.applyPermissionsToNavigation();
            }, 100);
        });
    } else {
        console.log('🔐 User not authenticated, skipping permission checks');
    }
    
    // When the page loads, check if a theme is stored in localStorage
    const storedTheme = localStorage.getItem('theme');
    if (storedTheme && storedTheme === 'dark') {
        document.body.classList.add('dark');
    }

    // Updated the ID from darkToggle to themeToggle
    const themeToggle = document.getElementById('themeToggle');
    if (themeToggle) {
        themeToggle.addEventListener('click', function() {
            // Toggle the "dark" class on the body element
            document.body.classList.toggle('dark');
            
            // Persist the theme selection in localStorage
            if (document.body.classList.contains('dark')) {
                localStorage.setItem('theme', 'dark');
                // Optional: update the icon for the dark theme
                this.querySelector('i').classList.add('fa-rotate-180');
            } else {
                localStorage.setItem('theme', 'light');
                // Optional: restore the icon for the light theme
                this.querySelector('i').classList.remove('fa-rotate-180');
            }
        });

        // Set the initial rotation of the icon based on the current theme
        if (document.body.classList.contains('dark')) {
            themeToggle.querySelector('i').classList.add('fa-rotate-180');
        }
    }
});

// Expose permissions manager globally for debugging
window.permissionsManager = permissionsManager;

// Test function for debugging permissions
window.testPermissions = function() {
    console.log('🧪 Testing permissions system:');
    console.log('- Authenticated:', permissionsManager.isAuthenticated);
    console.log('- Admin:', permissionsManager.isAdmin);
    console.log('- Permissions:', permissionsManager.userPermissions);
    
    const pages = ['home', 'energy', 'power', 'battery', 'voltage', 'info', 'command', 'settings', 'events'];
    pages.forEach(page => {
        console.log(`- ${page}: ${permissionsManager.hasPermission(page)}`);
    });
    
    const navItems = document.querySelectorAll('.nav-item[data-page]');
    console.log(`- Navigation items found: ${navItems.length}`);
    navItems.forEach(item => {
        const page = item.dataset.page;
        const isVisible = item.style.display !== 'none' && !item.classList.contains('permission-denied');
        console.log(`- ${page} visible: ${isVisible}`);
    });
}; 