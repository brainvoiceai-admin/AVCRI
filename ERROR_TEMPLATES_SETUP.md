# Error Templates Setup - Verdant Theme

## Overview
Custom error templates have been created for AVCRI with a Verdant (green-based) color theme. These templates provide a professional and user-friendly error experience instead of Django's default error pages.

## Files Created

### Templates
- `templates/errortemplates/400.html` - Bad Request error
- `templates/errortemplates/403.html` - Forbidden/Access Denied error
- `templates/errortemplates/404.html` - Page Not Found error
- `templates/errortemplates/500.html` - Internal Server Error
- `templates/errortemplates/csrf_failure.html` - CSRF Verification Failed

### Static Files
- `static/css/errortemplates_error.css` - Verdant theme CSS with animations
- `static/js/errortemplates_error.js` - Interactive JavaScript features

### Configuration Files
- `AVCRI/error_handlers.py` - Custom error handler views
- Updated `AVCRI/urls.py` - Error handler configuration
- Updated `AVCRI/settings.py` - CSRF failure view configuration

## Color Theme - Verdant

The Verdant theme uses a green-based color palette:
- **Primary Green**: `#2d8659` - Main brand color
- **Primary Dark**: `#1a5c3a` - Darker shade for contrast
- **Primary Light**: `#3d9b6f`, `#4fb883` - Lighter shades
- **Accent Colors**: `#7fc9a3`, `#a8dcc4`, `#d4ede4` - Light accents
- **Neutral**: White, light gray backgrounds

## Features

### Visual Features
- ✅ Modern, clean design with Verdant green theme
- ✅ Animated error code numbers
- ✅ Floating icon animations
- ✅ Smooth fade-in animations
- ✅ Responsive design (mobile-friendly)
- ✅ Gradient buttons with hover effects
- ✅ Ripple effect on button clicks

### Functional Features
- ✅ Clear error messages for each error type
- ✅ Helpful suggestions for users
- ✅ Navigation buttons (Go Back, Go Home, Login)
- ✅ Error details section with actionable items
- ✅ Auto-redirect capability (if needed)
- ✅ Copy error info to clipboard (via JS)

## Error Types Handled

### 400 - Bad Request
- Invalid or malformed requests
- Missing required parameters
- Invalid data submission

### 403 - Forbidden
- Access denied
- Insufficient permissions
- Session expired

### 404 - Not Found
- Page doesn't exist
- URL typos
- Moved or removed pages

### 500 - Internal Server Error
- Server-side errors
- Database issues
- Application errors

### CSRF Failure
- Session expiration
- Security token invalidation
- Form submission issues

## Configuration

### Error Handlers
Error handlers are configured in `AVCRI/urls.py`:
```python
handler400 = 'AVCRI.error_handlers.handler400'
handler403 = 'AVCRI.error_handlers.handler403'
handler404 = 'AVCRI.error_handlers.handler404'
handler500 = 'AVCRI.error_handlers.handler500'
```

### CSRF Failure Handler
Configured in `AVCRI/settings.py`:
```python
CSRF_FAILURE_VIEW = 'AVCRI.error_handlers.csrf_failure'
```

## Testing

### Test 404 Error
1. Navigate to a non-existent URL: `http://localhost:8000/nonexistent-page/`
2. Should see custom 404 page with Verdant theme

### Test 403 Error
1. Try accessing a restricted page without proper permissions
2. Should see custom 403 page

### Test 500 Error
1. Temporarily break something in code (e.g., raise Exception in a view)
2. Should see custom 500 page

### Test CSRF Error
1. Submit a form after session expires
2. Should see custom CSRF failure page

## File Structure

```
AVCRI/
├── error_handlers.py          # Error handler views
├── urls.py                    # Error handler configuration
└── settings.py                # CSRF failure view

templates/
└── errortemplates/
    ├── 400.html
    ├── 403.html
    ├── 404.html
    ├── 500.html
    └── csrf_failure.html

static/
├── css/
│   └── errortemplates_error.css
└── js/
    └── errortemplates_error.js
```

## Notes

- Error templates use direct URL paths (`/`, `/authentication/login/`) instead of `{% url %}` tags to avoid URL resolution errors during error conditions
- Templates are fully responsive and work on mobile devices
- CSS includes animations and hover effects for better UX
- JavaScript provides interactive features like ripple effects and notifications

## Customization

To customize the error templates:
1. Edit CSS in `static/css/errortemplates_error.css` to change colors/styling
2. Edit templates in `templates/errortemplates/` to change content
3. Edit JavaScript in `static/js/errortemplates_error.js` to add/remove features

## Browser Compatibility

- Modern browsers (Chrome, Firefox, Safari, Edge)
- CSS animations and transitions
- JavaScript ES6+ features
- Responsive design for mobile devices

