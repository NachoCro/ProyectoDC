/* ======================================================================
   Sidebar Toggle + Dark Mode
   Admin UI — PrestaShop ↔ Icecat
   ====================================================================== */

(function() {
  'use strict';

  // ─── DOM Elements ──────────────────────────────────────────────────
  const sidebar = document.querySelector('.sidebar');
  const toggleBtn = document.querySelector('.sidebar__toggle');
  const mobileMenuBtn = document.querySelector('.mobile-menu-btn');
  const sidebarOverlay = document.querySelector('.sidebar-overlay');
  const themeToggle = document.querySelector('.sidebar__theme-toggle');
  const themeIcon = document.querySelector('.sidebar__theme-icon');
  const themeText = document.querySelector('.sidebar__theme-toggle-text');

  // ─── State ─────────────────────────────────────────────────────────
  const STORAGE_KEY_SIDEBAR = 'sidebar_collapsed';
  const STORAGE_KEY_THEME = 'theme_preference';

  // ─── Initialize ────────────────────────────────────────────────────
  function init() {
    // Disable transitions on initial load to prevent flash
    document.body.classList.add('no-transition');

    // Restore sidebar state
    const sidebarCollapsed = localStorage.getItem(STORAGE_KEY_SIDEBAR);
    if (sidebarCollapsed === 'true') {
      sidebar.classList.add('collapsed');
    }

    // Initialize theme
    initTheme();

    // Bind events
    bindEvents();

    // Re-enable transitions after a short delay
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        document.body.classList.remove('no-transition');
      });
    });
  }

  // ─── Theme Management ──────────────────────────────────────────────
  function initTheme() {
    const savedTheme = localStorage.getItem(STORAGE_KEY_THEME);
    
    if (savedTheme) {
      // User has explicitly set a preference
      setTheme(savedTheme);
    } else {
      // Use system preference
      const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
      setTheme(prefersDark ? 'dark' : 'light');
    }

    // Listen for system theme changes
    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', (e) => {
      if (!localStorage.getItem(STORAGE_KEY_THEME)) {
        setTheme(e.matches ? 'dark' : 'light');
      }
    });
  }

  function setTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    updateThemeUI(theme);
  }

  function updateThemeUI(theme) {
    if (!themeIcon || !themeText) return;

    if (theme === 'dark') {
      themeIcon.textContent = '☀️';
      themeText.textContent = 'Modo claro';
    } else {
      themeIcon.textContent = '🌙';
      themeText.textContent = 'Modo oscuro';
    }
  }

  function toggleTheme() {
    const currentTheme = document.documentElement.getAttribute('data-theme');
    const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
    
    localStorage.setItem(STORAGE_KEY_THEME, newTheme);
    setTheme(newTheme);
  }

  // ─── Sidebar Toggle ────────────────────────────────────────────────
  function toggleSidebar() {
    sidebar.classList.toggle('collapsed');
    localStorage.setItem(STORAGE_KEY_SIDEBAR, sidebar.classList.contains('collapsed'));
  }

  // ─── Mobile Menu ───────────────────────────────────────────────────
  function openMobileMenu() {
    sidebar.classList.add('mobile-open');
    sidebarOverlay.classList.add('active');
    document.body.style.overflow = 'hidden';
  }

  function closeMobileMenu() {
    sidebar.classList.remove('mobile-open');
    sidebarOverlay.classList.remove('active');
    document.body.style.overflow = '';
  }

  // ─── Event Binding ─────────────────────────────────────────────────
  function bindEvents() {
    // Sidebar toggle
    if (toggleBtn) {
      toggleBtn.addEventListener('click', toggleSidebar);
    }

    // Mobile menu
    if (mobileMenuBtn) {
      mobileMenuBtn.addEventListener('click', openMobileMenu);
    }

    if (sidebarOverlay) {
      sidebarOverlay.addEventListener('click', closeMobileMenu);
    }

    // Theme toggle
    if (themeToggle) {
      themeToggle.addEventListener('click', toggleTheme);
    }

    // Keyboard shortcuts
    document.addEventListener('keydown', (e) => {
      // Ctrl/Cmd + B to toggle sidebar
      if ((e.ctrlKey || e.metaKey) && e.key === 'b') {
        e.preventDefault();
        toggleSidebar();
      }

      // Escape to close mobile menu
      if (e.key === 'Escape') {
        closeMobileMenu();
      }
    });

    // Close mobile menu on window resize
    window.addEventListener('resize', () => {
      if (window.innerWidth > 768) {
        closeMobileMenu();
      }
    });
  }

  // ─── Initialize on DOM Ready ───────────────────────────────────────
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
