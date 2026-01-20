function toggleSidebar() {
        const sidebar = document.getElementById('sidebar');
        sidebar.classList.toggle('open');
    }

    function toggleSection(sectionId) {
        // Prevent Account section from being collapsed
        if (sectionId === 'account-section') {
            return;
        }
        
        const section = document.getElementById(sectionId);
        const header = section.previousElementSibling;
        const arrow = header.querySelector('.section-arrow');
        
        section.classList.toggle('collapsed');
        header.classList.toggle('collapsed');
        
        // Save state to localStorage
        const isCollapsed = section.classList.contains('collapsed');
        localStorage.setItem(sectionId + '-collapsed', isCollapsed);
    }

    // Restore collapsed state from localStorage
    document.addEventListener('DOMContentLoaded', function() {
        console.log('=== ACCOUNT SECTION DEBUG ===');
        
        // Force Account section to be visible
        const accountSection = document.getElementById('account-section');
        const accountWrapper = document.getElementById('account-section-debug');
        
        console.log('Account section element:', accountSection);
        console.log('Account wrapper element:', accountWrapper);
        
        if (accountSection) {
            console.log('Account section found!');
            console.log('Current display:', window.getComputedStyle(accountSection).display);
            console.log('Current visibility:', window.getComputedStyle(accountSection).visibility);
            console.log('Current opacity:', window.getComputedStyle(accountSection).opacity);
            console.log('Current max-height:', window.getComputedStyle(accountSection).maxHeight);
            
            accountSection.style.display = 'block';
            accountSection.style.maxHeight = 'none';
            accountSection.style.opacity = '1';
            accountSection.style.visibility = 'visible';
            accountSection.classList.remove('collapsed');
            
            const accountHeader = accountSection.previousElementSibling;
            if (accountHeader) {
                accountHeader.classList.remove('collapsed');
            }
            
            console.log('After setting styles - display:', accountSection.style.display);
            console.log('Account section parent:', accountSection.parentElement);
            console.log('Account section offsetHeight:', accountSection.offsetHeight);
            console.log('Account section offsetTop:', accountSection.offsetTop);
        } else {
            console.error('ERROR: Account section element NOT FOUND in DOM!');
        }
        
        if (accountWrapper) {
            console.log('Account wrapper found!');
            console.log('Wrapper offsetHeight:', accountWrapper.offsetHeight);
            console.log('Wrapper offsetTop:', accountWrapper.offsetTop);
            accountWrapper.style.display = 'block';
            accountWrapper.style.visibility = 'visible';
        } else {
            console.error('ERROR: Account wrapper element NOT FOUND in DOM!');
        }
        
        console.log('=== END DEBUG ===');
        
        const sections = document.querySelectorAll('.menu-subsection');
        sections.forEach(section => {
            const sectionId = section.id;
            // Always keep Account section expanded
            if (sectionId === 'account-section') {
                section.classList.remove('collapsed');
                section.style.display = 'block';
                section.style.maxHeight = 'none';
                section.style.opacity = '1';
                const header = section.previousElementSibling;
                if (header) {
                    header.classList.remove('collapsed');
                }
            } else {
                const isCollapsed = localStorage.getItem(sectionId + '-collapsed') === 'true';
                if (isCollapsed) {
                    section.classList.add('collapsed');
                    const header = section.previousElementSibling;
                    if (header) {
                        header.classList.add('collapsed');
                    }
                }
            }
        });
        
        setActiveMenuItem();
    });

    document.addEventListener('click', function(event) {
        const sidebar = document.getElementById('sidebar');
        const hamburger = document.querySelector('.hamburger');
        if (window.innerWidth <= 768 &&
            !sidebar.contains(event.target) &&
            !hamburger.contains(event.target) &&
            sidebar.classList.contains('open')) {
            sidebar.classList.remove('open');
        }
    });

    function setActiveMenuItem() {
        const currentUrl = window.location.href;
        const menuItems = document.querySelectorAll('.menu-item');

        menuItems.forEach(item => {
            item.classList.remove('active');
            const itemUrl = item.getAttribute('href');
            if (currentUrl.includes(itemUrl) || currentUrl === itemUrl) {
                item.classList.add('active');
            }
        });
    }

    // Enhanced menu item handling - maintain active state and smooth navigation
    document.addEventListener('DOMContentLoaded', function() {
        const menuItems = document.querySelectorAll('.menu-item[data-url]');
        
        menuItems.forEach(item => {
            // Skip logout link - it should work normally
            if (item.id === 'logout') return;
            
            item.addEventListener('click', function(e) {
                const url = this.getAttribute('data-url');
                
                // Remove active class from all items
                menuItems.forEach(i => i.classList.remove('active'));
                // Add active class to clicked item
                this.classList.add('active');
                
                // Store active menu state
                localStorage.setItem('activeMenuItem', url);
                
                // Allow normal navigation but ensure menu stays active
                // The page will load normally, and setActiveMenuItem will handle highlighting
            });
        });
        
        // Restore active menu item from localStorage
        const activeMenuItem = localStorage.getItem('activeMenuItem');
        if (activeMenuItem) {
            menuItems.forEach(item => {
                if (item.getAttribute('data-url') === activeMenuItem) {
                    item.classList.add('active');
                }
            });
        }
    });